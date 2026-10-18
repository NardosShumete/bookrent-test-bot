"""Book cataloguing, inventory inspection, and search service."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.book import Book, BookCopy
from app.models.enums import BookCopyStatus
from app.models.exceptions import (
    CopyNotFoundError,
    MissingBookDetailsError,
    UnauthorizedError,
)
from app.services.audit import record_audit_log
from app.services.customer import require_owner
from app.services.inventory import record_received_copies
from app.services.isbn import clean_isbn, normalize_isbn

TWO_PLACES = Decimal("0.01")


def create_book(
    session: Session,
    isbn: str,
    title: str,
    author: str,
    rental_price: Decimal | str | int,
    page_count: Optional[int] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    actor_telegram_id: Optional[int] = None,
) -> Book:
    """Owner-only creation of a new catalogued book title.

    Validates that the caller is an authorized owner and that the ISBN does
    not already exist in canonical form.

    Args:
        session: Active SQLAlchemy database session.
        isbn: Raw ISBN string (normalized to canonical 13 digits).
        title: Title of the book.
        author: Author of the book.
        rental_price: Configurable rental fee per borrowing period.
        page_count: Optional page count.
        category: Optional category / genre.
        description: Optional synopsis.
        actor_telegram_id: Telegram user ID of the caller (must be an owner).

    Returns:
        The newly created Book instance.

    Raises:
        UnauthorizedError: If caller is not an authorized owner.
        ValueError: If ISBN already catalogued, fields are empty, or rental_price is negative.
        TypeError: If rental_price is a float.
    """
    require_owner(actor_telegram_id)

    if not title or not title.strip():
        raise ValueError("Title cannot be empty")
    if not author or not author.strip():
        raise ValueError("Author cannot be empty")
    if isinstance(rental_price, float):
        raise TypeError("Rental price must be a Decimal or numeric string, never float")

    dec_price = Decimal(str(rental_price)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if dec_price < Decimal("0.00"):
        raise ValueError("Rental price cannot be negative")

    canonical_isbn = normalize_isbn(isbn)

    # Check if book already catalogued
    existing = session.query(Book).filter(Book.isbn == canonical_isbn).first()
    if existing is not None:
        raise ValueError(
            f"Book with ISBN '{canonical_isbn}' is already catalogued ('{existing.title}'). "
            f"Use /receive to add physical copies."
        )

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
        rental_price=dec_price,
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
        actor=str(actor_telegram_id),
        new_values={
            "isbn": book.isbn,
            "title": book.title,
            "author": book.author,
            "rental_price": str(book.rental_price),
            "category": book.category,
        },
    )

    return book


def receive_stock_for_isbn(
    session: Session,
    isbn: str,
    quantity: int,
    actor_telegram_id: Optional[int] = None,
) -> Tuple[Book, List[BookCopy]]:
    """Owner-only receiving of physical copies for an existing catalogued title.

    Reuses the existing Book title and creates sequential BookCopy records.

    Args:
        session: Active SQLAlchemy database session.
        isbn: Raw ISBN string.
        quantity: Number of copies received (must be >= 1).
        actor_telegram_id: Telegram user ID of the caller (must be an owner).

    Returns:
        Tuple of (Book instance, list of newly created BookCopy instances).

    Raises:
        UnauthorizedError: If caller is not an owner.
        MissingBookDetailsError: If the ISBN is not yet catalogued.
        ValueError: If quantity < 1.
    """
    require_owner(actor_telegram_id)

    if quantity < 1:
        raise ValueError(f"Quantity must be at least 1, got {quantity}")

    canonical_isbn = normalize_isbn(isbn)
    book = session.query(Book).filter(Book.isbn == canonical_isbn).with_for_update().first()
    if book is None:
        raise MissingBookDetailsError(
            f"Book with ISBN '{canonical_isbn}' is not catalogued yet. "
            f"Please catalogue the title first using /addbook."
        )

    return record_received_copies(
        session=session,
        isbn=canonical_isbn,
        quantity=quantity,
        actor=f"OWNER:{actor_telegram_id}",
    )


def search_books(
    session: Session,
    query: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search catalogued books by title, author, category, or ISBN.

    Calculates actual availability where a copy is counted as available
    ONLY when its status is strictly ON_SHELF.

    Args:
        session: Active SQLAlchemy database session.
        query: Search term.
        limit: Maximum results to return.

    Returns:
        List of dictionaries with book metadata, available_copies, and total_copies.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    # Attempt to clean or normalize if user provided an ISBN-like query
    search_term = f"%{cleaned_query}%"
    try:
        isbn_term = clean_isbn(cleaned_query)
    except Exception:
        isbn_term = cleaned_query

    books = (
        session.query(Book)
        .filter(
            or_(
                Book.title.ilike(search_term),
                Book.author.ilike(search_term),
                Book.category.ilike(search_term),
                Book.isbn.ilike(f"%{isbn_term}%"),
            )
        )
        .order_by(Book.title.asc())
        .limit(limit)
        .all()
    )

    results: List[Dict[str, Any]] = []
    for book in books:
        total_copies = (
            session.query(func.count(BookCopy.id))
            .filter(BookCopy.book_id == book.id)
            .scalar()
            or 0
        )
        available_copies = (
            session.query(func.count(BookCopy.id))
            .filter(
                BookCopy.book_id == book.id,
                BookCopy.status == BookCopyStatus.ON_SHELF.value,
            )
            .scalar()
            or 0
        )
        results.append(
            {
                "id": book.id,
                "isbn": book.isbn,
                "title": book.title,
                "author": book.author,
                "rental_price": book.rental_price,
                "page_count": book.page_count,
                "category": book.category,
                "description": book.description,
                "available_copies": available_copies,
                "total_copies": total_copies,
            }
        )

    return results


def get_book_inventory_details(
    session: Session, identifier: str | int
) -> Optional[Dict[str, Any]]:
    """Retrieve full inventory details for a book, including its individual physical copies.

    Args:
        session: Active SQLAlchemy database session.
        identifier: Either book integer ID or ISBN string.

    Returns:
        Dictionary with book metadata, status counts breakdown, and individual copies list.
    """
    book: Optional[Book] = None
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        book = session.get(Book, int(identifier))

    if book is None and isinstance(identifier, str):
        try:
            canonical = normalize_isbn(identifier)
            book = session.query(Book).filter(Book.isbn == canonical).first()
        except Exception:
            pass

    if book is None:
        return None

    copies = (
        session.query(BookCopy)
        .filter(BookCopy.book_id == book.id)
        .order_by(BookCopy.copy_number.asc())
        .all()
    )

    status_counts = {s.value: 0 for s in BookCopyStatus}
    copies_list = []
    for c in copies:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1
        copies_list.append(
            {
                "id": c.id,
                "copy_number": c.copy_number,
                "barcode": c.barcode,
                "status": c.status,
                "condition_notes": c.condition_notes,
            }
        )

    return {
        "id": book.id,
        "isbn": book.isbn,
        "title": book.title,
        "author": book.author,
        "rental_price": book.rental_price,
        "page_count": book.page_count,
        "category": book.category,
        "description": book.description,
        "status_counts": status_counts,
        "available_copies": status_counts.get(BookCopyStatus.ON_SHELF.value, 0),
        "total_copies": len(copies),
        "copies": copies_list,
    }


def get_overall_inventory_summary(session: Session) -> Dict[str, Any]:
    """Calculate system-wide inventory metrics across all titles and physical copies.

    Returns:
        Dictionary containing total titles, total copies, and counts by copy status.
    """
    total_titles = session.query(func.count(Book.id)).scalar() or 0
    total_copies = session.query(func.count(BookCopy.id)).scalar() or 0

    counts_by_status = {s.value: 0 for s in BookCopyStatus}
    rows = session.query(BookCopy.status, func.count(BookCopy.id)).group_by(BookCopy.status).all()
    for status_str, count in rows:
        counts_by_status[status_str] = count

    return {
        "total_titles": total_titles,
        "total_copies": total_copies,
        "available_copies": counts_by_status.get(BookCopyStatus.ON_SHELF.value, 0),
        "reserved_copies": counts_by_status.get(BookCopyStatus.RESERVED.value, 0),
        "rented_copies": counts_by_status.get(BookCopyStatus.RENTED.value, 0),
        "overdue_copies": counts_by_status.get(BookCopyStatus.OVERDUE.value, 0),
        "damaged_copies": counts_by_status.get(BookCopyStatus.DAMAGED.value, 0),
        "lost_copies": counts_by_status.get(BookCopyStatus.LOST.value, 0),
        "counts_by_status": counts_by_status,
    }
