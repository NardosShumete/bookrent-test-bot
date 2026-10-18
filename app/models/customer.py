"""SQLAlchemy model for Customer."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    Numeric,
    String,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import CustomerStatus


class Customer(Base):
    """Represents a registered library customer associated with a Telegram user.

    Customer accounts default to PENDING status and must be approved by an
    administrator before rental checkouts are permitted.
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    phone_source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    latitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 7), nullable=True)
    national_id_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    national_id_uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_given: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    consent_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_policy_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    registration_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=CustomerStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(
        String(10), default="en", server_default="en", nullable=False
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    rentals: Mapped[List["Rental"]] = relationship(  # type: ignore[name-defined]
        "Rental",
        back_populates="customer",
        order_by="Rental.checkout_time.desc()",
    )
    ledger_entries: Mapped[List["CollateralLedger"]] = relationship(  # type: ignore[name-defined]
        "CollateralLedger",
        back_populates="customer",
        order_by="CollateralLedger.created_at.desc()",
    )
    overdue_charges: Mapped[List["OverdueCharge"]] = relationship(  # type: ignore[name-defined]
        "OverdueCharge",
        back_populates="customer",
        order_by="OverdueCharge.overdue_date.desc()",
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ('{CustomerStatus.PENDING.value}', '{CustomerStatus.APPROVED.value}', "
            f"'{CustomerStatus.SUSPENDED.value}', '{CustomerStatus.REJECTED.value}')",
            name="ck_customers_status_valid",
        ),
    )

    @property
    def is_approved(self) -> bool:
        """True if customer account is APPROVED and permitted to borrow books."""
        return self.status == CustomerStatus.APPROVED.value

    @property
    def is_rejected(self) -> bool:
        """True if customer account is REJECTED."""
        return self.status == CustomerStatus.REJECTED.value

    @property
    def is_pending(self) -> bool:
        """True if customer account is PENDING approval."""
        return self.status == CustomerStatus.PENDING.value

    @property
    def is_verification_complete(self) -> bool:
        """True if customer has submitted all required verification artifacts."""
        return bool(
            self.national_id_file_id
            and self.phone_number
            and (self.address or (self.latitude is not None and self.longitude is not None))
        )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} telegram_id={self.telegram_id} status='{self.status}'>"
