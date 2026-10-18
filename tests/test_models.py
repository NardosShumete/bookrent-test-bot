"""Tests for SQLAlchemy ORM models, relationships, and constraints."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import (
    BookCopyStatus,
    CustomerStatus,
    ExtensionStatus,
    LedgerTransactionType,
    RentalStatus,
)
from app.models.exceptions import (
    ExtensionAlreadyAppliedError,
    ExtensionInvalidStatusError,
    InvalidStatusTransitionError,
    RentalNotActiveError,
)
from app.models.ledger import CollateralLedger
from app.models.rental import Rental, RentalExtension


def test_book_and_copy_creation_and_cascade(db_session: Session) -> None:
    """Verify Book and BookCopy creation, relationship traversal, and cascade delete."""
    book = Book(
        isbn="9780306406157",
        title="Mechanisms of Memory",
        author="E. R. Kandel",
        page_count=350,
        category="Neuroscience",
        description="Foundational textbook on cellular memory mechanisms.",
        rental_price=Decimal("15.50"),
    )
    db_session.add(book)
    db_session.flush()

    copy1 = BookCopy(
        book_id=book.id,
        copy_number=1,
        barcode="9780306406157-001",
        status=BookCopyStatus.ON_SHELF.value,
    )
    copy2 = BookCopy(
        book_id=book.id,
        copy_number=2,
        barcode="9780306406157-002",
        status=BookCopyStatus.ON_SHELF.value,
    )
    db_session.add_all([copy1, copy2])
    db_session.flush()

    assert len(book.copies) == 2
    assert copy1.book.title == "Mechanisms of Memory"
    assert copy2.barcode == "9780306406157-002"

    # Test cascade delete: deleting book deletes its copies
    db_session.delete(book)
    db_session.flush()

    queried_copies = db_session.query(BookCopy).filter_by(book_id=book.id).all()
    assert len(queried_copies) == 0


def test_book_isbn_uniqueness(db_session: Session) -> None:
    """Verify database enforces unique constraint on ISBN."""
    b1 = Book(
        isbn="9780306406157",
        title="Title One",
        author="Author One",
        rental_price=Decimal("10.00"),
    )
    b2 = Book(
        isbn="9780306406157",
        title="Title Two",
        author="Author Two",
        rental_price=Decimal("12.00"),
    )
    db_session.add(b1)
    db_session.flush()

    db_session.add(b2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_book_copy_number_unique_per_book(db_session: Session) -> None:
    """Verify unique constraint on (book_id, copy_number)."""
    book = Book(
        isbn="9780306406157",
        title="Title",
        author="Author",
        rental_price=Decimal("5.00"),
    )
    db_session.add(book)
    db_session.flush()

    c1 = BookCopy(book_id=book.id, copy_number=1, barcode="B-001", status=BookCopyStatus.ON_SHELF.value)
    c2 = BookCopy(book_id=book.id, copy_number=1, barcode="B-002", status=BookCopyStatus.ON_SHELF.value)
    db_session.add(c1)
    db_session.flush()

    db_session.add(c2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_customer_status_defaults_and_approval(db_session: Session) -> None:
    """Verify customer account defaults to PENDING and supports APPROVED."""
    c = Customer(
        telegram_id=987654321,
        username="reader_bob",
        first_name="Bob",
        last_name="Reader",
    )
    db_session.add(c)
    db_session.flush()

    assert c.status == CustomerStatus.PENDING.value
    assert c.is_approved is False

    c.status = CustomerStatus.APPROVED.value
    db_session.flush()
    assert c.is_approved is True


def test_customer_telegram_id_uniqueness(db_session: Session) -> None:
    """Verify telegram_id uniqueness is strictly enforced."""
    c1 = Customer(telegram_id=111222, first_name="User 1")
    c2 = Customer(telegram_id=111222, first_name="User 2")
    db_session.add(c1)
    db_session.flush()

    db_session.add(c2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_book_copy_status_transitions_valid_and_invalid(db_session: Session) -> None:
    """Verify allowed state machine transitions on physical hardcopies."""
    book = Book(isbn="9780306406157", title="Test", author="Test", rental_price=Decimal("10.00"))
    db_session.add(book)
    db_session.flush()

    copy = BookCopy(book_id=book.id, copy_number=1, barcode="BAR-1", status=BookCopyStatus.ON_SHELF.value)
    db_session.add(copy)
    db_session.flush()

    # Allowed: ON_SHELF -> RESERVED
    copy.transition_to(BookCopyStatus.RESERVED, reason="Reserved for Alice")
    assert copy.status == BookCopyStatus.RESERVED.value
    assert "Alice" in copy.condition_notes

    # Allowed: RESERVED -> RENTED
    copy.transition_to(BookCopyStatus.RENTED)
    assert copy.status == BookCopyStatus.RENTED.value

    # Allowed: RENTED -> OVERDUE
    copy.transition_to(BookCopyStatus.OVERDUE)
    assert copy.status == BookCopyStatus.OVERDUE.value

    # Allowed: OVERDUE -> ON_SHELF (late return)
    copy.transition_to(BookCopyStatus.ON_SHELF)
    assert copy.status == BookCopyStatus.ON_SHELF.value

    # Disallowed: ON_SHELF cannot jump directly to OVERDUE without being rented!
    with pytest.raises(InvalidStatusTransitionError):
        copy.transition_to(BookCopyStatus.OVERDUE)

    # Disallowed: DAMAGED cannot jump directly to RENTED without repair
    copy.transition_to(BookCopyStatus.DAMAGED, reason="Torn spine")
    assert copy.status == BookCopyStatus.DAMAGED.value
    with pytest.raises(InvalidStatusTransitionError):
        copy.transition_to(BookCopyStatus.RENTED)

    # Allowed: DAMAGED -> ON_SHELF (repaired)
    copy.transition_to(BookCopyStatus.ON_SHELF, reason="Rebound and repaired")
    assert copy.status == BookCopyStatus.ON_SHELF.value


def test_rental_extension_cannot_be_applied_twice(db_session: Session) -> None:
    """Verify that an approved extension cannot be applied more than once."""
    book = Book(isbn="9780306406157", title="Title", author="Author", rental_price=Decimal("10.00"))
    customer = Customer(telegram_id=333444, first_name="Carl", status=CustomerStatus.APPROVED.value)
    db_session.add_all([book, customer])
    db_session.flush()

    copy = BookCopy(book_id=book.id, copy_number=1, barcode="BC-001", status=BookCopyStatus.RENTED.value)
    db_session.add(copy)
    db_session.flush()

    now = datetime.now(timezone.utc)
    original_due = now + timedelta(days=14)
    revised_due = now + timedelta(days=21)

    rental = Rental(
        copy_id=copy.id,
        customer_id=customer.id,
        checkout_time=now,
        due_date=original_due,
        status=RentalStatus.ACTIVE.value,
    )
    db_session.add(rental)
    db_session.flush()

    extension = RentalExtension(
        rental_id=rental.id,
        requested_days=7,
        previous_due_date=original_due,
        new_due_date=revised_due,
        fee=Decimal("5.00"),
        status=ExtensionStatus.REQUESTED.value,
        is_applied=False,
    )
    db_session.add(extension)
    db_session.flush()

    # First application: succeeds
    extension.apply_approval(reviewer="admin_1")
    assert extension.is_applied is True
    assert extension.status == ExtensionStatus.APPROVED.value
    assert rental.due_date == revised_due
    assert rental.status == RentalStatus.EXTENDED.value

    # Second application: MUST raise ExtensionAlreadyAppliedError
    with pytest.raises(ExtensionAlreadyAppliedError):
        extension.apply_approval(reviewer="admin_2")


def test_audit_log_model(db_session: Session) -> None:
    """Verify AuditLog stores entity mutation records with JSON payloads."""
    audit = AuditLog(
        entity_type="BOOK",
        entity_id="101",
        action="UPDATE_PRICE",
        actor="OWNER",
        old_values={"rental_price": "10.00"},
        new_values={"rental_price": "12.50"},
        reason="Annual rate revision",
    )
    db_session.add(audit)
    db_session.flush()

    queried = db_session.get(AuditLog, audit.id)
    assert queried is not None
    assert queried.entity_type == "BOOK"
    assert queried.entity_id == "101"
    assert queried.old_values["rental_price"] == "10.00"
    assert queried.new_values["rental_price"] == "12.50"
