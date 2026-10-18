"""SQLAlchemy models for RentalRequest and Payment."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple
from sqlalchemy import (
    Boolean,
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
from app.models.enums import (
    CollateralType,
    PaymentMethod,
    PaymentType,
    PaymentVerificationStatus,
    RentalRequestStatus,
)


class RentalRequest(Base):
    """Represents the pre-rental lifecycle of a customer borrowing request.

    Separates the request submission, owner review, copy reservation,
    and financial verification from the actual physical handover/checkout event.
    """

    __tablename__ = "rental_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    copy_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("book_copies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rental_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rentals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=RentalRequestStatus.SUBMITTED.value,
        nullable=False,
        index=True,
    )
    collateral_type: Mapped[str] = mapped_column(
        String(20),
        default=CollateralType.MONETARY.value,
        nullable=False,
    )
    guarantee_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rental_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    rental_fee_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    collateral_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    collateral_received: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    customer: Mapped["Customer"] = relationship("Customer")  # type: ignore[name-defined]
    book: Mapped["Book"] = relationship("Book")  # type: ignore[name-defined]
    copy: Mapped[Optional["BookCopy"]] = relationship("BookCopy")  # type: ignore[name-defined]
    rental: Mapped[Optional["Rental"]] = relationship("Rental")  # type: ignore[name-defined]
    payments: Mapped[List["Payment"]] = relationship(
        "Payment",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="Payment.created_at.desc()",
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{RentalRequestStatus.SUBMITTED.value}', '{RentalRequestStatus.APPROVED.value}', "
            f"'{RentalRequestStatus.REJECTED.value}', '{RentalRequestStatus.CANCELLED.value}', "
            f"'{RentalRequestStatus.COMPLETED.value}')",
            name="ck_rental_requests_status_valid",
        ),
        CheckConstraint(
            f"collateral_type IN ('{CollateralType.MONETARY.value}', '{CollateralType.GUARANTEE.value}')",
            name="ck_rental_requests_collateral_type_valid",
        ),
        CheckConstraint("rental_fee >= 0", name="ck_rental_requests_fee_non_negative"),
        CheckConstraint(
            "collateral_amount IS NULL OR collateral_amount >= 0",
            name="ck_rental_requests_collateral_non_negative",
        ),
    )

    def can_checkout(self) -> Tuple[bool, str]:
        """Validate whether all preconditions for physical handover/checkout are met.

        Conditions:
        1. Request is in APPROVED status.
        2. A specific physical hardcopy is allocated and reserved.
        3. Rental fee is verified as paid.
        4. Collateral requirement is satisfied (monetary deposit or non-cash guarantee verified).
        """
        if self.status != RentalRequestStatus.APPROVED.value:
            return False, f"Request status is '{self.status}', must be APPROVED."
        if not self.copy_id:
            return False, "No physical copy has been allocated."
        if not self.rental_fee_paid:
            return False, "Rental fee has not been verified."
        if not self.collateral_received:
            return False, "Collateral or guarantee requirement has not been verified."
        return True, ""

    def __repr__(self) -> str:
        return (
            f"<RentalRequest id={self.id} customer_id={self.customer_id} "
            f"book_id={self.book_id} status='{self.status}'>"
        )


class Payment(Base):
    """Represents a recorded and verified payment or non-cash collateral transaction."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rental_requests.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rental_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rentals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    extension_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("rental_extensions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payment_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(30),
        default=PaymentVerificationStatus.PENDING_VERIFICATION.value,
        nullable=False,
        index=True,
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    request: Mapped[Optional["RentalRequest"]] = relationship("RentalRequest", back_populates="payments")
    customer: Mapped["Customer"] = relationship("Customer")  # type: ignore[name-defined]
    rental: Mapped[Optional["Rental"]] = relationship("Rental")  # type: ignore[name-defined]
    extension: Mapped[Optional["RentalExtension"]] = relationship("RentalExtension")  # type: ignore[name-defined]

    __table_args__ = (
        CheckConstraint(
            f"payment_type IN ('{PaymentType.RENTAL_FEE.value}', '{PaymentType.COLLATERAL_DEPOSIT.value}', '{PaymentType.EXTENSION_FEE.value}')",
            name="ck_payments_type_valid",
        ),
        CheckConstraint(
            f"payment_method IN ('{PaymentMethod.CASH.value}', '{PaymentMethod.BANK_TRANSFER.value}', "
            f"'{PaymentMethod.NON_CASH_GUARANTEE.value}', '{PaymentMethod.OTHER.value}')",
            name="ck_payments_method_valid",
        ),
        CheckConstraint(
            f"verification_status IN ('{PaymentVerificationStatus.PENDING_VERIFICATION.value}', "
            f"'{PaymentVerificationStatus.VERIFIED.value}', '{PaymentVerificationStatus.REJECTED.value}')",
            name="ck_payments_status_valid",
        ),
        CheckConstraint("amount >= 0", name="ck_payments_amount_non_negative"),
    )


    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} request_id={self.request_id} type='{self.payment_type}' "
            f"amount={self.amount} status='{self.verification_status}'>"
        )
