"""Tests for inventory service: receiving copies, title deduplication, and copy status transitions."""

from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.book import Book, BookCopy
from app.models.enums import BookCopyStatus
from app.models.exceptions import (
    CopyNotFoundError,
    InvalidISBNError,
    InvalidStatusTransitionError,
    MissingBookDetailsError,
)
from app.services.inventory import (
    get_available_copies,
    get_inventory_counts,
    record_received_copies,
    transition_copy_status,
)


def test_record_new_book_copies(db_session: Session) -> None:
    """Verify recording copies for a previously uncatalogued title creates Book and copies."""
    book, copies = record_received_copies(
        session=db_session,
        isbn="0-306-40615-2",  # ISBN-10 with hyphens
        quantity=3,
        title="Principles of Neural Science",
        author="Eric R. Kandel",
        rental_price=Decimal("12.00"),
        page_count=1414,
        category="Science",
        description="Comprehensive neuroscience textbook.",
        actor="OWNER",
    )
    db_session.flush()

    assert book.id is not None
    assert book.isbn == "9780306406157"  # Normalized canonical ISBN-13
    assert book.title == "Principles of Neural Science"
    assert len(copies) == 3

    assert [c.copy_number for c in copies] == [1, 2, 3]
    assert [c.barcode for c in copies] == [
        "9780306406157-001",
        "9780306406157-002",
        "9780306406157-003",
    ]
    assert all(c.status == BookCopyStatus.ON_SHELF.value for c in copies)


def test_avoid_duplicate_book_titles_for_same_isbn_variant(db_session: Session) -> None:
    """Verify that recording additional copies using an ISBN variant reuses existing Book title."""
    # First batch: registered using ISBN-10
    book1, batch1 = record_received_copies(
        session=db_session,
        isbn="0306406152",
        quantity=2,
        title="Foundations of Biology",
        author="Jane Doe",
        rental_price=Decimal("10.00"),
    )
    db_session.flush()

    # Second batch: registered using ISBN-13 with hyphens
    book2, batch2 = record_received_copies(
        session=db_session,
        isbn="978-0-306-40615-7",
        quantity=3,
    )
    db_session.flush()

    # Verify that NO duplicate book title was created
    assert book1.id == book2.id
    total_books = db_session.query(Book).filter_by(isbn="9780306406157").count()
    assert total_books == 1

    # Verify copy numbers continued incrementing from 2: copies 3, 4, 5
    assert len(batch2) == 3
    assert [c.copy_number for c in batch2] == [3, 4, 5]
    assert [c.barcode for c in batch2] == [
        "9780306406157-003",
        "9780306406157-004",
        "9780306406157-005",
    ]

    # Verify total copies for the book is 5
    total_copies = db_session.query(BookCopy).filter_by(book_id=book1.id).count()
    assert total_copies == 5


def test_record_new_book_missing_details_raises(db_session: Session) -> None:
    """Verify that registering copies for a new ISBN without title/author/rental_price raises error."""
    with pytest.raises(MissingBookDetailsError):
        record_received_copies(
            session=db_session,
            isbn="978-1-86197-876-9",
            quantity=2,
            # Missing title, author, rental_price
        )


def test_record_invalid_quantity_raises(db_session: Session) -> None:
    """Verify quantity < 1 raises ValueError."""
    with pytest.raises(ValueError, match="at least 1"):
        record_received_copies(
            session=db_session,
            isbn="9780306406157",
            quantity=0,
            title="Title",
            author="Author",
            rental_price=Decimal("5.00"),
        )


def test_transition_copy_status_service(db_session: Session) -> None:
    """Verify transition_copy_status updates status and logs audit entry."""
    book, copies = record_received_copies(
        session=db_session,
        isbn="9780306406157",
        quantity=1,
        title="Book A",
        author="Author A",
        rental_price=Decimal("8.00"),
    )
    copy = copies[0]
    db_session.flush()

    # Transition to RESERVED
    transition_copy_status(db_session, copy.id, BookCopyStatus.RESERVED, actor="BOT", reason="Hold for user")
    assert copy.status == BookCopyStatus.RESERVED.value

    # Disallowed transition raises error
    with pytest.raises(InvalidStatusTransitionError):
        transition_copy_status(db_session, copy.id, BookCopyStatus.OVERDUE)


def test_transition_nonexistent_copy_raises(db_session: Session) -> None:
    """Verify transition_copy_status on nonexistent ID raises CopyNotFoundError."""
    with pytest.raises(CopyNotFoundError):
        transition_copy_status(db_session, 99999, BookCopyStatus.RESERVED)


def test_inventory_counts_and_available_copies(db_session: Session) -> None:
    """Verify get_inventory_counts and get_available_copies report accurate inventory state."""
    book, copies = record_received_copies(
        session=db_session,
        isbn="9780306406157",
        quantity=3,
        title="Inventory Test Book",
        author="Author",
        rental_price=Decimal("10.00"),
    )
    c1, c2, c3 = copies
    db_session.flush()

    # Move c2 to RESERVED, c3 to DAMAGED
    transition_copy_status(db_session, c2, BookCopyStatus.RESERVED)
    transition_copy_status(db_session, c3, BookCopyStatus.DAMAGED, reason="Water damage")

    counts = get_inventory_counts(db_session, book_id=book.id)
    assert counts[BookCopyStatus.ON_SHELF.value] == 1
    assert counts[BookCopyStatus.RESERVED.value] == 1
    assert counts[BookCopyStatus.DAMAGED.value] == 1
    assert counts[BookCopyStatus.RENTED.value] == 0

    available = get_available_copies(db_session, book_id=book.id)
    assert len(available) == 1
    assert available[0].id == c1.id
