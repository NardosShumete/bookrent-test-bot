"""Tests for customer registration, approval/rejection workflows, and owner authorization."""

import pytest
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import CustomerStatus
from app.models.exceptions import (
    CustomerNotFoundError,
    InvalidCustomerStatusError,
    UnauthorizedError,
)
from app.services.customer import (
    approve_customer,
    get_customer_by_telegram_id,
    get_pending_customers,
    is_owner,
    register_customer,
    reject_customer,
    require_owner,
)


def test_is_owner_and_require_owner(valid_env_vars: dict) -> None:
    """Verify owner authorization checks against configured ADMIN_USER_IDS."""
    # From valid_env_vars: ADMIN_USER_IDS = "12345,67890"
    assert is_owner(12345) is True
    assert is_owner(67890) is True
    assert is_owner(99999) is False
    assert is_owner(None) is False

    # require_owner should pass for owner
    require_owner(12345)

    # require_owner should raise UnauthorizedError for non-owner
    with pytest.raises(UnauthorizedError, match="not an authorized library owner"):
        require_owner(99999)

    with pytest.raises(UnauthorizedError):
        require_owner(None)


def test_customer_registration_creates_pending_account(db_session: Session) -> None:
    """Verify new registration creates customer with PENDING status."""
    customer, created = register_customer(
        session=db_session,
        telegram_id=5001,
        first_name="Alice",
        last_name="Smith",
        username="alice_reader",
    )
    db_session.flush()

    assert created is True
    assert customer.id is not None
    assert customer.telegram_id == 5001
    assert customer.status == CustomerStatus.PENDING.value
    assert customer.is_approved is False


def test_customer_registration_idempotency_does_not_duplicate(db_session: Session) -> None:
    """Verify registering the same Telegram ID twice updates names and does not create duplicates."""
    cust1, created1 = register_customer(
        session=db_session,
        telegram_id=5002,
        first_name="Bob",
        username="bob1",
    )
    db_session.flush()
    assert created1 is True

    # Second registration with same Telegram ID
    cust2, created2 = register_customer(
        session=db_session,
        telegram_id=5002,
        first_name="Robert",
        username="bob_new",
    )
    db_session.flush()

    assert created2 is False
    assert cust1.id == cust2.id
    assert cust2.first_name == "Robert"
    assert cust2.username == "bob_new"

    # Confirm only one customer exists in DB
    total = db_session.query(Customer).filter_by(telegram_id=5002).count()
    assert total == 1


def test_get_pending_customers_authorization(db_session: Session, valid_env_vars: dict) -> None:
    """Verify get_pending_customers enforces owner authorization."""
    register_customer(db_session, telegram_id=5003, first_name="Pending1")
    register_customer(db_session, telegram_id=5004, first_name="Pending2")
    db_session.flush()

    # Non-owner caller must be rejected
    with pytest.raises(UnauthorizedError):
        get_pending_customers(db_session, actor_telegram_id=99999)

    # Owner caller retrieves pending customers
    pending = get_pending_customers(db_session, actor_telegram_id=12345)
    assert len(pending) >= 2
    assert all(c.status == CustomerStatus.PENDING.value for c in pending)


def test_approve_customer_lifecycle(db_session: Session, valid_env_vars: dict) -> None:
    """Verify customer approval workflow, status transition, and repeated approval protection."""
    customer, _ = register_customer(db_session, telegram_id=5005, first_name="Charlie")
    db_session.flush()

    owner_id = 12345
    non_owner_id = 99999

    # Non-owner cannot approve
    with pytest.raises(UnauthorizedError):
        approve_customer(db_session, customer.id, actor_telegram_id=non_owner_id)

    # Owner approves customer
    approved = approve_customer(db_session, customer.id, actor_telegram_id=owner_id)
    db_session.flush()

    assert approved.status == CustomerStatus.APPROVED.value
    assert approved.is_approved is True

    # Repeated approval on already approved customer raises InvalidCustomerStatusError
    with pytest.raises(InvalidCustomerStatusError, match="status 'APPROVED'"):
        approve_customer(db_session, customer.id, actor_telegram_id=owner_id)


def test_reject_customer_lifecycle(db_session: Session, valid_env_vars: dict) -> None:
    """Verify customer rejection workflow and repeated action protection."""
    customer, _ = register_customer(db_session, telegram_id=5006, first_name="Dave")
    db_session.flush()

    owner_id = 12345
    non_owner_id = 99999

    # Non-owner cannot reject
    with pytest.raises(UnauthorizedError):
        reject_customer(db_session, customer.id, actor_telegram_id=non_owner_id)

    # Owner rejects customer
    rejected = reject_customer(db_session, customer.id, actor_telegram_id=owner_id, reason="Incomplete profile")
    db_session.flush()

    assert rejected.status == CustomerStatus.REJECTED.value
    assert rejected.is_approved is False

    # Repeated rejection on already rejected customer raises InvalidCustomerStatusError
    with pytest.raises(InvalidCustomerStatusError, match="status 'REJECTED'"):
        reject_customer(db_session, customer.id, actor_telegram_id=owner_id)


def test_approve_or_reject_nonexistent_customer(db_session: Session, valid_env_vars: dict) -> None:
    """Verify CustomerNotFoundError when target customer does not exist."""
    with pytest.raises(CustomerNotFoundError):
        approve_customer(db_session, 88888, actor_telegram_id=12345)

    with pytest.raises(CustomerNotFoundError):
        reject_customer(db_session, 88888, actor_telegram_id=12345)
