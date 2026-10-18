"""Tests for book cataloguing, stock receiving, title deduplication, and search services."""

from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.book import Book, BookCopy
from app.models.enums import BookCopyStatus
from app.models.exceptions import (
    InvalidISBNError,
    MissingBookDetailsError,
    UnauthorizedError,
)
from app.services.book_catalog import (
    create_book,
    get_book_inventory_details,
    get_overall_inventory_summary,
    receive_stock_for_isbn,
    search_books,
)
from app.services.inventory import transition_copy_status


def test_create_book_owner_authorization(db_session: Session, valid_env_vars: dict) -> None:
    """Verify create_book enforces owner authorization."""
    owner_id = 12345
    non_owner_id = 99999

    # Non-owner blocked
    with pytest.raises(UnauthorizedError):
        create_book(
            session=db_session,
            isbn="978-0-306-40615-7",
            title="Title",
            author="Author",
            rental_price=Decimal("10.00"),
            actor_telegram_id=non_owner_id,
        )

    # Owner succeeds
    book = create_book(
        session=db_session,
        isbn="0-306-40615-2",  # ISBN-10 with dashes
        title="Principles of Neural Science",
        author="Eric R. Kandel",
        rental_price=Decimal("15.00"),
        page_count=1414,
        category="Neuroscience",
        description="Core neurobiology text.",
        actor_telegram_id=owner_id,
    )
    db_session.flush()

    assert book.id is not None
    assert book.isbn == "9780306406157"  # Normalized canonical ISBN
    assert book.title == "Principles of Neural Science"
    assert book.rental_price == Decimal("15.00")


def test_create_book_duplicate_title_prevention(db_session: Session, valid_env_vars: dict) -> None:
    """Verify create_book prevents duplicate titles for the same canonical ISBN."""
    owner_id = 12345

    create_book(
        session=db_session,
        isbn="978-0-306-40615-7",
        title="Title 1",
        author="Author 1",
        rental_price=Decimal("10.00"),
        actor_telegram_id=owner_id,
    )
    db_session.flush()

    # Attempting to catalogue again with an ISBN-10 variant MUST raise error
    with pytest.raises(ValueError, match="already catalogued"):
        create_book(
            session=db_session,
            isbn="0306406152",
            title="Title 2",
            author="Author 2",
            rental_price=Decimal("12.00"),
            actor_telegram_id=owner_id,
        )


def test_receive_stock_for_isbn_deduplication(db_session: Session, valid_env_vars: dict) -> None:
    """Verify receive_stock_for_isbn adds copies to existing title without duplication."""
    owner_id = 12345

    # 1. Catalogue title
    book = create_book(
        session=db_session,
        isbn="9780306406157",
        title="Cellular Biology",
        author="Bruce Alberts",
        rental_price=Decimal("14.00"),
        actor_telegram_id=owner_id,
    )
    db_session.flush()

    # 2. Receive first batch of 3 copies
    _, batch1 = receive_stock_for_isbn(
        session=db_session,
        isbn="0-306-40615-2",  # ISBN-10 variant
        quantity=3,
        actor_telegram_id=owner_id,
    )
    db_session.flush()

    assert len(batch1) == 3
    assert [c.copy_number for c in batch1] == [1, 2, 3]

    # 3. Receive second batch of 2 copies
    _, batch2 = receive_stock_for_isbn(
        session=db_session,
        isbn="978-0-306-40615-7",  # ISBN-13 variant
        quantity=2,
        actor_telegram_id=owner_id,
    )
    db_session.flush()

    assert len(batch2) == 2
    assert [c.copy_number for c in batch2] == [4, 5]

    # Confirm only 1 Book record exists with 5 total copies
    total_books = db_session.query(Book).filter_by(isbn="9780306406157").count()
    assert total_books == 1
    total_copies = db_session.query(BookCopy).filter_by(book_id=book.id).count()
    assert total_copies == 5


def test_receive_stock_uncatalogued_isbn_raises(db_session: Session, valid_env_vars: dict) -> None:
    """Verify receive_stock_for_isbn raises MissingBookDetailsError if title not yet catalogued."""
    with pytest.raises(MissingBookDetailsError, match="not catalogued yet"):
        receive_stock_for_isbn(
            session=db_session,
            isbn="9781861978769",
            quantity=2,
            actor_telegram_id=12345,
        )


def test_search_books_and_availability_distinction(db_session: Session, valid_env_vars: dict) -> None:
    """Verify search matches fields and available_copies counts strictly ON_SHELF copies."""
    owner_id = 12345

    # Create Book A: 3 copies (1 ON_SHELF, 1 RENTED, 1 DAMAGED)
    book_a = create_book(
        session=db_session,
        isbn="9780306406157",
        title="Introduction to Quantum Mechanics",
        author="David J. Griffiths",
        rental_price=Decimal("12.50"),
        category="Physics",
        actor_telegram_id=owner_id,
    )
    _, copies_a = receive_stock_for_isbn(db_session, "9780306406157", 3, actor_telegram_id=owner_id)
    db_session.flush()

    # Move copy 2 to RENTED, copy 3 to DAMAGED
    transition_copy_status(db_session, copies_a[1], BookCopyStatus.RENTED)
    transition_copy_status(db_session, copies_a[2], BookCopyStatus.DAMAGED)
    db_session.flush()

    # Create Book B: 2 copies (both ON_SHELF)
    book_b = create_book(
        session=db_session,
        isbn="9781861978769",
        title="The 48 Laws of Power",
        author="Robert Greene",
        rental_price=Decimal("9.00"),
        category="Self-Help",
        actor_telegram_id=owner_id,
    )
    receive_stock_for_isbn(db_session, "9781861978769", 2, actor_telegram_id=owner_id)
    db_session.flush()

    # Search by Title
    results_title = search_books(db_session, "Quantum")
    assert len(results_title) == 1
    assert results_title[0]["title"] == "Introduction to Quantum Mechanics"
    assert results_title[0]["total_copies"] == 3
    # Critical: available_copies must be strictly 1 because only copy 1 is ON_SHELF!
    assert results_title[0]["available_copies"] == 1

    # Search by Author
    results_author = search_books(db_session, "Greene")
    assert len(results_author) == 1
    assert results_author[0]["title"] == "The 48 Laws of Power"
    assert results_author[0]["available_copies"] == 2
    assert results_author[0]["total_copies"] == 2

    # Search by Category
    results_cat = search_books(db_session, "Physics")
    assert len(results_cat) == 1
    assert results_cat[0]["id"] == book_a.id

    # Search by ISBN
    results_isbn = search_books(db_session, "9780306406157")
    assert len(results_isbn) == 1
    assert results_isbn[0]["id"] == book_a.id


def test_get_book_inventory_details_and_overall_summary(
    db_session: Session, valid_env_vars: dict
) -> None:
    """Verify detailed copy inspection and global inventory summary."""
    owner_id = 12345

    create_book(
        session=db_session,
        isbn="9780306406157",
        title="Neuroscience Today",
        author="John Smith",
        rental_price=Decimal("11.00"),
        category="Medical",
        actor_telegram_id=owner_id,
    )
    _, copies = receive_stock_for_isbn(db_session, "9780306406157", 2, actor_telegram_id=owner_id)
    db_session.flush()

    # Inspect book inventory details
    details = get_book_inventory_details(db_session, "9780306406157")
    assert details is not None
    assert details["title"] == "Neuroscience Today"
    assert details["total_copies"] == 2
    assert details["available_copies"] == 2
    assert len(details["copies"]) == 2
    assert details["copies"][0]["barcode"] == "9780306406157-001"

    # Overall summary
    summary = get_overall_inventory_summary(db_session)
    assert summary["total_titles"] >= 1
    assert summary["total_copies"] >= 2
    assert summary["available_copies"] >= 2
