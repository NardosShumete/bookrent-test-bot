"""Tests for financial ledger service, discrete transactions, and monetary precision."""

from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import CustomerStatus, LedgerTransactionType
from app.models.exceptions import InsufficientCollateralError
from app.services.ledger import (
    get_customer_collateral_balance,
    get_rental_ledger_summary,
    record_ledger_entry,
)


@pytest.fixture
def sample_customer(db_session: Session) -> Customer:
    """Fixture providing an approved customer for financial tests."""
    c = Customer(
        telegram_id=555666777,
        first_name="Dana",
        status=CustomerStatus.APPROVED.value,
    )
    db_session.add(c)
    db_session.flush()
    return c


def test_reject_floating_point_amounts(db_session: Session, sample_customer: Customer) -> None:
    """Verify that floating-point numbers are strictly forbidden and raise TypeError."""
    with pytest.raises(TypeError, match="never float"):
        record_ledger_entry(
            session=db_session,
            customer_id=sample_customer.id,
            transaction_type=LedgerTransactionType.COLLATERAL_DEPOSIT,
            amount=50.25,  # float is illegal
        )


def test_reject_non_positive_amounts(db_session: Session, sample_customer: Customer) -> None:
    """Verify zero or negative amounts are rejected."""
    with pytest.raises(ValueError, match="strictly positive"):
        record_ledger_entry(
            session=db_session,
            customer_id=sample_customer.id,
            transaction_type=LedgerTransactionType.COLLATERAL_DEPOSIT,
            amount=Decimal("0.00"),
        )

    with pytest.raises(ValueError, match="strictly positive"):
        record_ledger_entry(
            session=db_session,
            customer_id=sample_customer.id,
            transaction_type=LedgerTransactionType.COLLATERAL_DEPOSIT,
            amount=Decimal("-10.00"),
        )


def test_collateral_deposit_deduction_and_refund_lifecycle(
    db_session: Session, sample_customer: Customer
) -> None:
    """Verify distinct collateral transactions and accurate running balance tracking."""
    cid = sample_customer.id

    # 1. Initial balance is 0.00
    assert get_customer_collateral_balance(db_session, cid) == Decimal("0.00")

    # 2. Deposit 100.00 collateral
    e1 = record_ledger_entry(
        session=db_session,
        customer_id=cid,
        transaction_type=LedgerTransactionType.COLLATERAL_DEPOSIT,
        amount=Decimal("100.00"),
        notes="Initial rental deposit",
    )
    db_session.flush()
    assert e1.collateral_balance_after == Decimal("100.00")
    assert get_customer_collateral_balance(db_session, cid) == Decimal("100.00")

    # 3. Deduction of 25.50 (e.g. damaged cover)
    e2 = record_ledger_entry(
        session=db_session,
        customer_id=cid,
        transaction_type=LedgerTransactionType.COLLATERAL_DEDUCTION,
        amount=Decimal("25.50"),
        notes="Damage deduction for water spill",
    )
    db_session.flush()
    assert e2.collateral_balance_after == Decimal("74.50")
    assert get_customer_collateral_balance(db_session, cid) == Decimal("74.50")

    # 4. Refund of 50.00 to customer
    e3 = record_ledger_entry(
        session=db_session,
        customer_id=cid,
        transaction_type=LedgerTransactionType.COLLATERAL_REFUND,
        amount=Decimal("50.00"),
        notes="Partial refund on returned book",
    )
    db_session.flush()
    assert e3.collateral_balance_after == Decimal("24.50")
    assert get_customer_collateral_balance(db_session, cid) == Decimal("24.50")

    # 5. Attempting to refund 30.00 (which exceeds remaining 24.50) MUST raise InsufficientCollateralError
    with pytest.raises(InsufficientCollateralError, match="only has 24.50"):
        record_ledger_entry(
            session=db_session,
            customer_id=cid,
            transaction_type=LedgerTransactionType.COLLATERAL_REFUND,
            amount=Decimal("30.00"),
        )


def test_fees_and_penalties_as_distinct_transactions(
    db_session: Session, sample_customer: Customer
) -> None:
    """Verify rental fees, extension fees, and overdue penalties are recorded separately."""
    cid = sample_customer.id

    fee_entry = record_ledger_entry(
        session=db_session,
        customer_id=cid,
        transaction_type=LedgerTransactionType.RENTAL_FEE,
        amount=Decimal("12.50"),
        rental_id=1,
    )
    ext_entry = record_ledger_entry(
        session=db_session,
        customer_id=cid,
        transaction_type=LedgerTransactionType.EXTENSION_FEE,
        amount=Decimal("3.00"),
        rental_id=1,
    )
    penalty_entry = record_ledger_entry(
        session=db_session,
        customer_id=cid,
        transaction_type=LedgerTransactionType.OVERDUE_PENALTY,
        amount=Decimal("5.00"),
        rental_id=1,
    )
    db_session.flush()

    assert fee_entry.transaction_type == LedgerTransactionType.RENTAL_FEE.value
    assert ext_entry.transaction_type == LedgerTransactionType.EXTENSION_FEE.value
    assert penalty_entry.transaction_type == LedgerTransactionType.OVERDUE_PENALTY.value

    # Check summary aggregation
    summary = get_rental_ledger_summary(db_session, rental_id=1)
    assert summary[LedgerTransactionType.RENTAL_FEE.value] == Decimal("12.50")
    assert summary[LedgerTransactionType.EXTENSION_FEE.value] == Decimal("3.00")
    assert summary[LedgerTransactionType.OVERDUE_PENALTY.value] == Decimal("5.00")
    assert summary[LedgerTransactionType.COLLATERAL_DEPOSIT.value] == Decimal("0.00")


def test_monetary_precision_exactness(db_session: Session, sample_customer: Customer) -> None:
    """Verify that multiple fractional decimal additions retain absolute arithmetic precision."""
    cid = sample_customer.id

    # Add 10 transactions of 0.10 each
    for _ in range(10):
        record_ledger_entry(
            session=db_session,
            customer_id=cid,
            transaction_type=LedgerTransactionType.COLLATERAL_DEPOSIT,
            amount=Decimal("0.10"),
        )
    db_session.flush()

    balance = get_customer_collateral_balance(db_session, cid)
    # Floating point arithmetic would produce 0.9999999999999999; Decimal must be exactly 1.00
    assert balance == Decimal("1.00")
