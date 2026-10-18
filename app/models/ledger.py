"""SQLAlchemy model for CollateralLedger."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import LedgerTransactionType


class CollateralLedger(Base):
    """Represents a distinct financial transaction for collateral and fees.

    Tracks rental fees, collateral deposits, extension charges, overdue penalties,
    collateral deductions, and collateral refunds as discrete ledger transactions.
    Monetary amounts are stored strictly as NUMERIC/Decimal with fixed 2-decimal
    scale; floating point values are forbidden.
    """

    __tablename__ = "collateral_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    rental_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rentals.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    collateral_balance_after: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(100), default="SYSTEM", nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="ledger_entries")  # type: ignore[name-defined]
    rental: Mapped[Optional["Rental"]] = relationship("Rental", back_populates="ledger_entries")  # type: ignore[name-defined]

    __table_args__ = (
        CheckConstraint(
            f"transaction_type IN ('{LedgerTransactionType.RENTAL_FEE.value}', "
            f"'{LedgerTransactionType.COLLATERAL_DEPOSIT.value}', "
            f"'{LedgerTransactionType.EXTENSION_FEE.value}', "
            f"'{LedgerTransactionType.OVERDUE_PENALTY.value}', "
            f"'{LedgerTransactionType.COLLATERAL_DEDUCTION.value}', "
            f"'{LedgerTransactionType.COLLATERAL_REFUND.value}')",
            name="ck_collateral_ledger_type_valid",
        ),
        CheckConstraint("amount > 0", name="ck_collateral_ledger_amount_positive"),
        CheckConstraint(
            "collateral_balance_after IS NULL OR collateral_balance_after >= 0",
            name="ck_collateral_ledger_balance_non_negative",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CollateralLedger id={self.id} customer_id={self.customer_id} "
            f"type='{self.transaction_type}' amount={self.amount}>"
        )
