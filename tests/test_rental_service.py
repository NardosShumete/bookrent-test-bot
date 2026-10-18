"""Tests for rental service: checkouts, customer approvals, extensions, and returns."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import BookCopyStatus, CustomerStatus, ExtensionStatus, RentalStatus
from app.models.exceptions import (
    CopyNotAvailableError,
    CustomerNotApprovedError,
    ExtensionAlreadyAppliedError,
    RentalNotActiveError,
)
from app.models.rental import Rental
from app.services.inventory import record_received_copies
from app.services.rental import (
    approve_extension,
    create_rental,
    reject_extension,
    request_extension,
    return_rental,
)


@pytest.fixture
def test_setup(db_session: Session):
    """Fixture providing a catalogued book with copies and customers."""
    book, copies = record_received_copies(
        session=db_session,
        isbn="9780306406157",
        quantity=2,
        title="Sample Book",
        author="Author",
        rental_price=Decimal("10.00"),
    )

    pending_cust = Customer(
        telegram_id=1001,
        first_name="Pending",
        last_name="User",
        status=CustomerStatus.PENDING.value,
    )
    approved_cust = Customer(
        telegram_id=1002,
        first_name="Approved",
        last_name="User",
        status=CustomerStatus.APPROVED.value,
    )
    db_session.add_all([pending_cust, approved_cust])
    db_session.flush()

    return book, copies, pending_cust, approved_cust


def test_pending_customer_cannot_rent(db_session: Session, test_setup) -> None:
    """Verify that unapproved (PENDING) customer accounts cannot check out books."""
    book, copies, pending_cust, _ = test_setup
    now = datetime.now(timezone.utc)

    with pytest.raises(CustomerNotApprovedError, match="must be APPROVED"):
        create_rental(
            session=db_session,
            copy_id=copies[0].id,
            customer_id=pending_cust.id,
            checkout_time=now,
            due_date=now + timedelta(days=14),
        )


def test_approved_customer_can_rent_and_copy_becomes_rented(db_session: Session, test_setup) -> None:
    """Verify approved customer can check out a copy and copy transitions to RENTED."""
    book, copies, _, approved_cust = test_setup
    copy = copies[0]
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=14)

    rental = create_rental(
        session=db_session,
        copy_id=copy.id,
        customer_id=approved_cust.id,
        checkout_time=now,
        due_date=due,
        actor="DESK_AGENT",
    )
    db_session.flush()

    assert rental.id is not None
    assert rental.copy_id == copy.id
    assert rental.customer_id == approved_cust.id
    assert rental.checkout_time == now
    assert rental.due_date == due
    assert rental.return_time is None
    assert rental.status == RentalStatus.ACTIVE.value

    # Physical copy status is RENTED
    assert copy.status == BookCopyStatus.RENTED.value


def test_cannot_rent_unavailable_copy(db_session: Session, test_setup) -> None:
    """Verify that attempting to rent an already rented copy raises CopyNotAvailableError."""
    book, copies, _, approved_cust = test_setup
    copy = copies[0]
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=14)

    # First checkout succeeds
    create_rental(
        session=db_session,
        copy_id=copy.id,
        customer_id=approved_cust.id,
        checkout_time=now,
        due_date=due,
    )
    db_session.flush()

    # Second checkout of the same copy fails
    with pytest.raises(CopyNotAvailableError):
        create_rental(
            session=db_session,
            copy_id=copy.id,
            customer_id=approved_cust.id,
            checkout_time=now,
            due_date=due,
        )


def test_extension_workflow_cannot_apply_twice(db_session: Session, test_setup) -> None:
    """Verify extension request, approval updates due date, and prevents duplicate application."""
    book, copies, _, approved_cust = test_setup
    now = datetime.now(timezone.utc)
    original_due = now + timedelta(days=14)
    revised_due = now + timedelta(days=21)

    rental = create_rental(
        session=db_session,
        copy_id=copies[0].id,
        customer_id=approved_cust.id,
        checkout_time=now,
        due_date=original_due,
    )
    db_session.flush()

    # Request extension
    ext = request_extension(
        session=db_session,
        rental_id=rental.id,
        requested_days=7,
        new_due_date=revised_due,
        fee=Decimal("4.50"),
        actor="CUSTOMER",
    )
    db_session.flush()

    assert ext.status == ExtensionStatus.REQUESTED.value
    assert ext.is_applied is False
    assert ext.previous_due_date == original_due
    assert ext.new_due_date == revised_due
    assert ext.fee == Decimal("4.50")

    # Approve extension
    approved_ext = approve_extension(db_session, ext.id, reviewer="ADMIN_BOB")
    db_session.flush()

    assert approved_ext.status == ExtensionStatus.APPROVED.value
    assert approved_ext.is_applied is True
    assert approved_ext.reviewed_by == "ADMIN_BOB"
    assert rental.due_date == revised_due
    assert rental.status == RentalStatus.EXTENDED.value

    # Re-approving MUST fail
    with pytest.raises(ExtensionAlreadyAppliedError):
        approve_extension(db_session, ext.id, reviewer="ADMIN_ALICE")


def test_reject_extension_leaves_due_date_unchanged(db_session: Session, test_setup) -> None:
    """Verify rejecting an extension does not change rental due date."""
    book, copies, _, approved_cust = test_setup
    now = datetime.now(timezone.utc)
    original_due = now + timedelta(days=14)

    rental = create_rental(
        session=db_session,
        copy_id=copies[0].id,
        customer_id=approved_cust.id,
        checkout_time=now,
        due_date=original_due,
    )
    db_session.flush()

    ext = request_extension(
        session=db_session,
        rental_id=rental.id,
        requested_days=7,
        new_due_date=now + timedelta(days=21),
    )
    db_session.flush()

    rejected = reject_extension(db_session, ext.id, reviewer="OWNER", reason="Book is reserved by another reader")
    db_session.flush()

    assert rejected.status == ExtensionStatus.REJECTED.value
    assert rejected.is_applied is False
    assert rental.due_date == original_due
    assert rental.status == RentalStatus.ACTIVE.value


def test_return_rental_success_and_copy_restored(db_session: Session, test_setup) -> None:
    """Verify return_rental closes rental and transitions copy back to ON_SHELF."""
    book, copies, _, approved_cust = test_setup
    copy = copies[0]
    now = datetime.now(timezone.utc)

    rental = create_rental(
        session=db_session,
        copy_id=copy.id,
        customer_id=approved_cust.id,
        checkout_time=now,
        due_date=now + timedelta(days=7),
    )
    db_session.flush()

    return_time = now + timedelta(days=5)
    closed = return_rental(
        session=db_session,
        rental_id=rental.id,
        return_time=return_time,
        copy_condition_status=BookCopyStatus.ON_SHELF,
    )
    db_session.flush()

    assert closed.return_time == return_time
    assert closed.status == RentalStatus.RETURNED.value
    assert closed.is_active is False
    assert copy.status == BookCopyStatus.ON_SHELF.value

    # Trying to return again raises RentalNotActiveError
    with pytest.raises(RentalNotActiveError):
        return_rental(session=db_session, rental_id=rental.id)
