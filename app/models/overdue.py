"""SQLAlchemy model for daily overdue charges and notification tracking."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class OverdueCharge(Base):
    """Represents a discrete daily overdue charge accrued on an active rental.

    Enforces that each overdue calendar day can only be charged once per rental
    via the database unique constraint `uq_overdue_charges_rental_date`.
    Maintains independent notification delivery tracking so failed notifications
    can be retried without re-charging.
    """

    __tablename__ = "overdue_charges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rental_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rentals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    overdue_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    day_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    notification_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rental: Mapped["Rental"] = relationship("Rental", back_populates="overdue_charges")  # type: ignore[name-defined]
    customer: Mapped["Customer"] = relationship("Customer")  # type: ignore[name-defined]

    __table_args__ = (
        UniqueConstraint("rental_id", "overdue_date", name="uq_overdue_charges_rental_date"),
        CheckConstraint("amount >= 0", name="ck_overdue_charges_amount_non_negative"),
        CheckConstraint("day_number >= 1", name="ck_overdue_charges_day_number_positive"),
    )

    def __repr__(self) -> str:
        return (
            f"<OverdueCharge id={self.id} rental_id={self.rental_id} "
            f"date={self.overdue_date} day={self.day_number} amount={self.amount}>"
        )
