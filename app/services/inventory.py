"""Inventory management service for book titles and physical copies."""

from decimal import Decimal
from typing import List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.book import Book, BookCopy
from app.models.enums import BookCopyStatus
from app.models.exceptions import (
    CopyNotFoundError,
    InvalidStatusTransitionError,
    MissingBookDetailsError,
)
from app.services.audit import record_audit_log
from app.services.isbn import normalize_isbn


def record_received_copies(
    session: Session,
    isbn: str,
    quantity: int,
    title: Optional[str] = None,
    author: Optional[str] = None,
    rental_price: Optional[Decimal] = None,
    page_count: Optional[int] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    actor: str = "OWNER",
) -> Tuple[Book, List[BookCopy]]:
    """Record newly received physical copies for an ISBN without creating duplicate titles.

    Normalizes the input ISBN to its canonical 13-digit format so that ISBN-10
    and ISBN-13 variants map to the identical Book record. If the title does not
    yet exist in the catalogue, it is created with the required metadata.

    Args:
        session: Active SQLAlchemy database session.
        isbn: Raw ISBN string (ISBN-10 or ISBN-13, with or without dashes).
        quantity: Number of physical copies received (must be >= 1).
        title: Title of the book (required if registering a new title).
        author: Author of the book (required if registering a new title).
        rental_price: Rental price per borrowing period (required if registering new title).
        page_count: Optional page count.
        category: Optional genre or classification category.
        description: Optional synopsis or catalogue notes.
        actor: Identity of user or system recording the batch.

    Returns:
        Tuple of (Book instance, list of newly created BookCopy instances).

    Raises:
        ValueError: If quantity < 1.
        InvalidISBNError: If ISBN is malformed or invalid.
        MissingBookDetailsError: If new book registration lacks title, author, or rental_price.
    """
    if quantity < 1:
        raise ValueError(f"Quantity of received copies must be at least 1, got {quantity}")

    canonical_isbn = normalize_isbn(isbn)

    # Check for existing title with row lock if supported
    book = (
        session.query(Book)
        .filter(Book.isbn == canonical_isbn)
        .with_for_update()
        .first()
    )

    if book is None:
        if not title or not author or rental_price is None:
            raise MissingBookDetailsError(
                f"Title, author, and rental_price are required to register newly catalogued ISBN '{canonical_isbn}'"
            )
        if isinstance(rental_price, float):
            raise TypeError("rental_price must be a Decimal or numeric string, never float")

        def _clean_nullable_str(val: Optional[str]) -> Optional[str]:
            if not val:
                return None
            s = str(val).strip()
            if s.lower() in ("null", "none", "n/a", "-"):
                return None
            return s

        book = Book(
            isbn=canonical_isbn,
            title=title.strip(),
            author=author.strip(),
            rental_price=Decimal(str(rental_price)),
            page_count=int(page_count) if page_count is not None else None,
            category=_clean_nullable_str(category),
            description=_clean_nullable_str(description),
        )
        session.add(book)
        session.flush([book])

        record_audit_log(
            session=session,
            entity_type="BOOK",
            entity_id=book.id,
            action="CREATE_TITLE",
            actor=actor,
            new_values={
                "isbn": book.isbn,
                "title": book.title,
                "author": book.author,
                "rental_price": str(book.rental_price),
            },
        )

    # Determine highest existing copy_number for this title
    highest_num = (
        session.query(func.max(BookCopy.copy_number))
        .filter(BookCopy.book_id == book.id)
        .scalar()
        or 0
    )

    new_copies: List[BookCopy] = []
    for i in range(1, quantity + 1):
        copy_num = highest_num + i
        barcode = f"{canonical_isbn}-{copy_num:03d}"
        copy = BookCopy(
            book_id=book.id,
            copy_number=copy_num,
            barcode=barcode,
            status=BookCopyStatus.ON_SHELF.value,
        )
        session.add(copy)
        new_copies.append(copy)

    session.flush(new_copies)

    record_audit_log(
        session=session,
        entity_type="BOOK",
        entity_id=book.id,
        action="RECEIVE_COPIES",
        actor=actor,
        new_values={
            "quantity_added": quantity,
            "copy_numbers": [c.copy_number for c in new_copies],
            "barcodes": [c.barcode for c in new_copies],
        },
    )

    return book, new_copies


def transition_copy_status(
    session: Session,
    copy_id_or_instance: int | BookCopy,
    target_status: BookCopyStatus | str,
    actor: str = "SYSTEM",
    reason: Optional[str] = None,
) -> BookCopy:
    """Transition a physical copy to a new status after enforcing allowed state transitions.

    Args:
        session: Active SQLAlchemy database session.
        copy_id_or_instance: Physical copy ID or BookCopy instance.
        target_status: Desired BookCopyStatus enum or string.
        actor: Identity of actor performing the transition.
        reason: Optional contextual note or explanation.

    Returns:
        Updated BookCopy instance.

    Raises:
        CopyNotFoundError: If the copy does not exist.
        InvalidStatusTransitionError: If the transition is disallowed.
    """
    if isinstance(copy_id_or_instance, BookCopy):
        copy = copy_id_or_instance
    else:
        copy = session.get(BookCopy, copy_id_or_instance)
        if copy is None:
            raise CopyNotFoundError(f"BookCopy with ID {copy_id_or_instance} not found")

    old_status = copy.status
    target = target_status if isinstance(target_status, BookCopyStatus) else BookCopyStatus(target_status)

    copy.transition_to(target, reason=reason)
    session.flush([copy])

    record_audit_log(
        session=session,
        entity_type="BOOK_COPY",
        entity_id=copy.id,
        action="STATUS_CHANGE",
        actor=actor,
        old_values={"status": old_status},
        new_values={"status": copy.status},
        reason=reason,
    )

    return copy


def get_inventory_counts(
    session: Session,
    book_id: Optional[int] = None,
    isbn: Optional[str] = None,
) -> dict[str, int]:
    """Calculate counts of copies grouped by status.

    Args:
        session: Active SQLAlchemy database session.
        book_id: Optional Book title ID filter.
        isbn: Optional ISBN filter (will be normalized).

    Returns:
        Dictionary mapping BookCopyStatus string value to count of copies.
    """
    query = session.query(BookCopy.status, func.count(BookCopy.id))

    if book_id is not None:
        query = query.filter(BookCopy.book_id == book_id)
    elif isbn is not None:
        canonical = normalize_isbn(isbn)
        query = query.join(Book).filter(Book.isbn == canonical)

    counts = {s.value: 0 for s in BookCopyStatus}
    for status_val, count in query.group_by(BookCopy.status).all():
        counts[status_val] = count

    return counts


def get_available_copies(
    session: Session,
    book_id: Optional[int] = None,
    isbn: Optional[str] = None,
) -> List[BookCopy]:
    """Retrieve all physical copies currently ON_SHELF and available for rental.

    Args:
        session: Active SQLAlchemy database session.
        book_id: Optional Book title ID filter.
        isbn: Optional ISBN filter.

    Returns:
        List of available BookCopy instances.
    """
    query = session.query(BookCopy).filter(BookCopy.status == BookCopyStatus.ON_SHELF.value)

    if book_id is not None:
        query = query.filter(BookCopy.book_id == book_id)
    elif isbn is not None:
        canonical = normalize_isbn(isbn)
        query = query.join(Book).filter(Book.isbn == canonical)

    return query.order_by(BookCopy.copy_number).all()
