"""SQLAlchemy models for Rental and RentalExtension."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import ExtensionStatus, RentalStatus
from app.models.exceptions import (
    ExtensionAlreadyAppliedError,
    ExtensionInvalidStatusError,
    ExtensionPaymentNotVerifiedError,
    RentalNotActiveError,
)


class Rental(Base):
    """Represents a rental transaction linking a physical copy to a customer.

    Enforces that concurrent operations cannot allocate one copy to multiple
    active rentals via the partial unique index `uq_active_rental_per_copy`.
    """

    __tablename__ = "rentals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    copy_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("book_copies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    checkout_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    return_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default=RentalStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    copy: Mapped["BookCopy"] = relationship("BookCopy", back_populates="rentals")  # type: ignore[name-defined]
    customer: Mapped["Customer"] = relationship("Customer", back_populates="rentals")  # type: ignore[name-defined]
    extensions: Mapped[List["RentalExtension"]] = relationship(
        "RentalExtension",
        back_populates="rental",
        cascade="all, delete-orphan",
        order_by="RentalExtension.requested_at",
    )
    ledger_entries: Mapped[List["CollateralLedger"]] = relationship(  # type: ignore[name-defined]
        "CollateralLedger",
        back_populates="rental",
        order_by="CollateralLedger.created_at.desc(), CollateralLedger.id.desc()",
    )
    overdue_charges: Mapped[List["OverdueCharge"]] = relationship(  # type: ignore[name-defined]
        "OverdueCharge",
        back_populates="rental",
        cascade="all, delete-orphan",
        order_by="OverdueCharge.overdue_date",
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{RentalStatus.ACTIVE.value}', '{RentalStatus.EXTENDED.value}', "
            f"'{RentalStatus.RETURNED.value}', '{RentalStatus.OVERDUE.value}', '{RentalStatus.CANCELLED.value}')",
            name="ck_rentals_status_valid",
        ),
        CheckConstraint("due_date >= checkout_time", name="ck_rentals_due_date_after_checkout"),
        # Partial unique index guarantees that at most ONE active rental can exist per copy
        Index(
            "uq_active_rental_per_copy",
            "copy_id",
            unique=True,
            postgresql_where=text("return_time IS NULL AND status != 'CANCELLED'"),
            sqlite_where=text("return_time IS NULL AND status != 'CANCELLED'"),
        ),
    )

    @property
    def is_active(self) -> bool:
        """True if rental is currently active (checked out and not returned or cancelled)."""
        return self.return_time is None and self.status in (
            RentalStatus.ACTIVE.value,
            RentalStatus.EXTENDED.value,
            RentalStatus.OVERDUE.value,
        )

    def __repr__(self) -> str:
        return f"<Rental id={self.id} copy_id={self.copy_id} customer_id={self.customer_id} status='{self.status}'>"


class RentalExtension(Base):
    """Represents an extension request for a rental's due date.

    Guarantees that a revised due date cannot be applied more than once
    via the `is_applied` flag and validation methods.
    """

    __tablename__ = "rental_extensions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rental_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rentals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_days: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    new_due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default=ExtensionStatus.REQUESTED.value,
        nullable=False,
        index=True,
    )
    is_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payment_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_verified_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    rental: Mapped["Rental"] = relationship("Rental", back_populates="extensions")

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{ExtensionStatus.REQUESTED.value}', '{ExtensionStatus.APPROVED.value}', '{ExtensionStatus.REJECTED.value}')",
            name="ck_rental_extensions_status_valid",
        ),

        CheckConstraint("requested_days > 0", name="ck_rental_extensions_days_positive"),
        CheckConstraint(
            "new_due_date > previous_due_date",
            name="ck_rental_extensions_new_due_date_later",
        ),
        CheckConstraint("fee >= 0", name="ck_rental_extensions_fee_non_negative"),
    )

    def apply_approval(self, reviewer: Optional[str] = None, require_payment_verified: bool = False) -> None:
        """Approve and apply the extension to the parent rental.

        Updates rental.due_date and rental.status, while preventing multiple applications.

        Raises:
            ExtensionAlreadyAppliedError: If this extension was already applied.
            ExtensionInvalidStatusError: If this extension is not in REQUESTED status.
            ExtensionPaymentNotVerifiedError: If require_payment_verified is True and payment is not verified.
            RentalNotActiveError: If the parent rental is not currently active.
        """
        if self.is_applied:
            raise ExtensionAlreadyAppliedError(
                f"Extension #{self.id} for rental #{self.rental_id} has already been applied."
            )
        if self.status != ExtensionStatus.REQUESTED.value:
            raise ExtensionInvalidStatusError(
                f"Extension #{self.id} is in status '{self.status}', cannot approve."
            )
        if require_payment_verified and not self.payment_verified:
            raise ExtensionPaymentNotVerifiedError(
                f"Extension #{self.id} cannot be approved before payment verification."
            )
        if not self.rental or not self.rental.is_active:
            raise RentalNotActiveError(
                f"Cannot apply extension to inactive or missing rental #{self.rental_id}."
            )

        self.status = ExtensionStatus.APPROVED.value
        self.is_applied = True
        self.reviewed_at = datetime.now(timezone.utc)
        self.reviewed_by = reviewer
        self.rental.due_date = self.new_due_date
        self.rental.status = RentalStatus.EXTENDED.value

    def apply_rejection(self, reviewer: Optional[str] = None) -> None:
        """Reject the extension request.

        Raises:
            ExtensionAlreadyAppliedError: If this extension was already applied.
            ExtensionInvalidStatusError: If this extension is not in REQUESTED status.
        """
        if self.is_applied:
            raise ExtensionAlreadyAppliedError(
                f"Extension #{self.id} has already been applied and cannot be rejected."
            )
        if self.status != ExtensionStatus.REQUESTED.value:
            raise ExtensionInvalidStatusError(
                f"Extension #{self.id} is in status '{self.status}', cannot reject."
            )

        self.status = ExtensionStatus.REJECTED.value
        self.reviewed_at = datetime.now(timezone.utc)
        self.reviewed_by = reviewer

    def __repr__(self) -> str:
        return (
            f"<RentalExtension id={self.id} rental_id={self.rental_id} "
            f"days={self.requested_days} status='{self.status}' applied={self.is_applied}>"
        )
