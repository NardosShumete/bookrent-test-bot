"""Collateral and financial ledger service managing discrete monetary transactions."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.enums import LedgerTransactionType
from app.models.exceptions import (
    CustomerNotFoundError,
    InsufficientCollateralError,
)
from app.models.ledger import CollateralLedger
from app.services.audit import record_audit_log

TWO_PLACES = Decimal("0.01")


def get_customer_collateral_balance(session: Session, customer_id: int) -> Decimal:
    """Calculate the current available net monetary collateral for a customer.

    Formula:
        Net Collateral = Total Deposits - Total Deductions - Total Refunds

    Args:
        session: Active SQLAlchemy database session.
        customer_id: ID of the Customer.

    Returns:
        Available collateral as a Decimal with 2 decimal places.
    """
    entries = (
        session.query(CollateralLedger.transaction_type, func.sum(CollateralLedger.amount))
        .filter(CollateralLedger.customer_id == customer_id)
        .filter(
            CollateralLedger.transaction_type.in_(
                [
                    LedgerTransactionType.COLLATERAL_DEPOSIT.value,
                    LedgerTransactionType.COLLATERAL_DEDUCTION.value,
                    LedgerTransactionType.COLLATERAL_REFUND.value,
                ]
            )
        )
        .group_by(CollateralLedger.transaction_type)
        .all()
    )

    totals = {row[0]: Decimal(str(row[1] or 0)) for row in entries}
    deposits = totals.get(LedgerTransactionType.COLLATERAL_DEPOSIT.value, Decimal("0.00"))
    deductions = totals.get(LedgerTransactionType.COLLATERAL_DEDUCTION.value, Decimal("0.00"))
    refunds = totals.get(LedgerTransactionType.COLLATERAL_REFUND.value, Decimal("0.00"))

    net = (deposits - deductions - refunds).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return net


def record_ledger_entry(
    session: Session,
    customer_id: int,
    transaction_type: LedgerTransactionType | str,
    amount: Decimal | str | int,
    rental_id: Optional[int] = None,
    notes: Optional[str] = None,
    actor: str = "SYSTEM",
) -> CollateralLedger:
    """Record a discrete financial ledger transaction using strict Decimal precision.

    Prevents floating-point inputs, validates positive amounts, checks that
    deductions and refunds do not exceed available collateral, and maintains
    a reliable running balance snapshot.

    Args:
        session: Active SQLAlchemy database session.
        customer_id: ID of Customer.
        transaction_type: LedgerTransactionType enum or string.
        amount: Monetary value (Decimal, integer, or numeric string).
        rental_id: Optional ID of associated Rental.
        notes: Optional narrative context or receipt note.
        actor: Identity of actor creating the ledger transaction.

    Returns:
        Persisted CollateralLedger record.

    Raises:
        TypeError: If amount is a float (floating-point arithmetic strictly forbidden).
        ValueError: If amount <= 0 or invalid transaction type.
        CustomerNotFoundError: If customer does not exist.
        InsufficientCollateralError: If deduction or refund exceeds available collateral balance.
    """
    if isinstance(amount, float):
        raise TypeError(
            f"Monetary amounts must be Decimal or numeric string, never float (received: {amount!r})"
        )

    try:
        dec_amount = Decimal(str(amount)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise ValueError(f"Invalid monetary amount '{amount}': {exc}") from exc

    if dec_amount <= Decimal("0.00"):
        raise ValueError(f"Ledger amount must be strictly positive (> 0.00), got {dec_amount}")

    ttype = (
        transaction_type
        if isinstance(transaction_type, LedgerTransactionType)
        else LedgerTransactionType(transaction_type)
    )

    # Verify customer exists
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise CustomerNotFoundError(f"Customer with ID {customer_id} not found")

    current_collateral = get_customer_collateral_balance(session, customer_id)

    if ttype in (LedgerTransactionType.COLLATERAL_DEDUCTION, LedgerTransactionType.COLLATERAL_REFUND):
        if dec_amount > current_collateral:
            raise InsufficientCollateralError(
                f"Cannot process {ttype.value} of {dec_amount}: customer #{customer_id} "
                f"only has {current_collateral} in collateral"
            )
        new_balance = (current_collateral - dec_amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    elif ttype == LedgerTransactionType.COLLATERAL_DEPOSIT:
        new_balance = (current_collateral + dec_amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    else:
        # Rental fee, extension fee, or penalty do not alter collateral deposit pool
        new_balance = current_collateral

    entry = CollateralLedger(
        customer_id=customer_id,
        rental_id=rental_id,
        transaction_type=ttype.value,
        amount=dec_amount,
        collateral_balance_after=new_balance,
        notes=notes,
        actor=actor,
    )
    session.add(entry)
    session.flush([entry])

    record_audit_log(
        session=session,
        entity_type="LEDGER",
        entity_id=entry.id,
        action="POST_TRANSACTION",
        actor=actor,
        new_values={
            "customer_id": customer_id,
            "rental_id": rental_id,
            "type": ttype.value,
            "amount": str(dec_amount),
            "balance_after": str(new_balance),
        },
    )

    return entry


def get_rental_ledger_summary(session: Session, rental_id: int) -> dict[str, Decimal]:
    """Calculate totals of all ledger transactions associated with a specific rental.

    Args:
        session: Active SQLAlchemy database session.
        rental_id: ID of the Rental.

    Returns:
        Dictionary mapping transaction type to total Decimal sum for that rental.
    """
    rows = (
        session.query(CollateralLedger.transaction_type, func.sum(CollateralLedger.amount))
        .filter(CollateralLedger.rental_id == rental_id)
        .group_by(CollateralLedger.transaction_type)
        .all()
    )

    summary = {t.value: Decimal("0.00") for t in LedgerTransactionType}
    for ttype, total in rows:
        summary[ttype] = Decimal(str(total or 0)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    return summary
