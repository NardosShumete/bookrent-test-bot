"""Tests verifying concurrent allocation prevention and partial unique constraints on rentals."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import BookCopyStatus, CustomerStatus, RentalStatus
from app.models.rental import Rental


def test_cannot_allocate_one_copy_to_multiple_active_rentals(db_session: Session) -> None:
    """Verify that database partial unique index prevents double-booking a physical copy."""
    book = Book(isbn="9780306406157", title="Test Book", author="Author", rental_price=Decimal("10.00"))
    cust1 = Customer(telegram_id=111, first_name="Cust 1", status=CustomerStatus.APPROVED.value)
    cust2 = Customer(telegram_id=222, first_name="Cust 2", status=CustomerStatus.APPROVED.value)
    db_session.add_all([book, cust1, cust2])
    db_session.flush()

    copy = BookCopy(book_id=book.id, copy_number=1, barcode="C-001", status=BookCopyStatus.RENTED.value)
    db_session.add(copy)
    db_session.flush()

    now = datetime.now(timezone.utc)

    # First active rental on this copy
    rental1 = Rental(
        copy_id=copy.id,
        customer_id=cust1.id,
        checkout_time=now,
        due_date=now + timedelta(days=7),
        return_time=None,  # Active rental
        status=RentalStatus.ACTIVE.value,
    )
    db_session.add(rental1)
    db_session.flush()

    # Second active rental on the SAME copy concurrently attempted
    rental2 = Rental(
        copy_id=copy.id,
        customer_id=cust2.id,
        checkout_time=now,
        due_date=now + timedelta(days=7),
        return_time=None,  # Active rental
        status=RentalStatus.ACTIVE.value,
    )
    db_session.add(rental2)

    # Database partial unique index uq_active_rental_per_copy MUST abort with IntegrityError
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_returned_rental_permits_subsequent_active_rental(db_session: Session) -> None:
    """Verify that once return_time is set, a subsequent active rental on the same copy succeeds."""
    book = Book(isbn="9780306406157", title="Test Book", author="Author", rental_price=Decimal("10.00"))
    cust1 = Customer(telegram_id=333, first_name="Cust 1", status=CustomerStatus.APPROVED.value)
    cust2 = Customer(telegram_id=444, first_name="Cust 2", status=CustomerStatus.APPROVED.value)
    db_session.add_all([book, cust1, cust2])
    db_session.flush()

    copy = BookCopy(book_id=book.id, copy_number=1, barcode="C-002", status=BookCopyStatus.ON_SHELF.value)
    db_session.add(copy)
    db_session.flush()

    now = datetime.now(timezone.utc)

    # First rental has already been completed and returned
    rental1 = Rental(
        copy_id=copy.id,
        customer_id=cust1.id,
        checkout_time=now - timedelta(days=10),
        due_date=now - timedelta(days=3),
        return_time=now - timedelta(days=4),  # Returned!
        status=RentalStatus.RETURNED.value,
    )
    db_session.add(rental1)
    db_session.flush()

    # Second rental is active on the same copy now that the previous one is closed
    rental2 = Rental(
        copy_id=copy.id,
        customer_id=cust2.id,
        checkout_time=now,
        due_date=now + timedelta(days=7),
        return_time=None,  # Active
        status=RentalStatus.ACTIVE.value,
    )
    db_session.add(rental2)
    db_session.flush()

    assert rental1.id is not None
    assert rental2.id is not None
    assert rental1.id != rental2.id
