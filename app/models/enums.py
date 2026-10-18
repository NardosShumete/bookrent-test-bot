"""Enums and status transition rules for BookRent Bot database models."""

from enum import Enum


class BookCopyStatus(str, Enum):
    """Lifecycle status of an individual physical book hardcopy."""

    ON_SHELF = "ON_SHELF"
    RESERVED = "RESERVED"
    RENTED = "RENTED"
    OVERDUE = "OVERDUE"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class CustomerStatus(str, Enum):
    """Account status for customers in the system."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


class RentalStatus(str, Enum):
    """Status of a rental checkout record."""

    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class ExtensionStatus(str, Enum):
    """Status of a rental due date extension request."""

    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LedgerTransactionType(str, Enum):
    """Distinct financial transaction types recorded in the collateral ledger."""

    RENTAL_FEE = "RENTAL_FEE"
    COLLATERAL_DEPOSIT = "COLLATERAL_DEPOSIT"
    EXTENSION_FEE = "EXTENSION_FEE"
    OVERDUE_PENALTY = "OVERDUE_PENALTY"
    COLLATERAL_DEDUCTION = "COLLATERAL_DEDUCTION"
    COLLATERAL_REFUND = "COLLATERAL_REFUND"


class RentalRequestStatus(str, Enum):
    """Lifecycle status of a rental request."""

    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class CollateralType(str, Enum):
    """Form of collateral provided for a rental."""

    MONETARY = "MONETARY"
    GUARANTEE = "GUARANTEE"


class PaymentType(str, Enum):
    """Purpose of a payment transaction."""

    RENTAL_FEE = "RENTAL_FEE"
    COLLATERAL_DEPOSIT = "COLLATERAL_DEPOSIT"
    EXTENSION_FEE = "EXTENSION_FEE"


class PaymentMethod(str, Enum):
    """Method by which a payment was tendered."""

    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    NON_CASH_GUARANTEE = "NON_CASH_GUARANTEE"
    OTHER = "OTHER"


class PaymentVerificationStatus(str, Enum):
    """Verification state of a recorded payment."""

    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# Allowed state transitions for physical copies
VALID_COPY_TRANSITIONS: dict[BookCopyStatus, set[BookCopyStatus]] = {
    BookCopyStatus.ON_SHELF: {
        BookCopyStatus.RESERVED,
        BookCopyStatus.RENTED,
        BookCopyStatus.DAMAGED,
        BookCopyStatus.LOST,
    },
    BookCopyStatus.RESERVED: {
        BookCopyStatus.ON_SHELF,  # Reservation cancelled or expired
        BookCopyStatus.RENTED,    # Picked up / checked out
        BookCopyStatus.DAMAGED,   # Found damaged before pickup
        BookCopyStatus.LOST,      # Missing from reservation hold
    },
    BookCopyStatus.RENTED: {
        BookCopyStatus.ON_SHELF,  # Returned in good condition
        BookCopyStatus.OVERDUE,   # Due date passed without return
        BookCopyStatus.DAMAGED,   # Returned damaged
        BookCopyStatus.LOST,      # Lost by customer
    },
    BookCopyStatus.OVERDUE: {
        BookCopyStatus.ON_SHELF,  # Late return in good condition
        BookCopyStatus.DAMAGED,   # Late return with damage
        BookCopyStatus.LOST,      # Customer never returned / declared lost
    },
    BookCopyStatus.DAMAGED: {
        BookCopyStatus.ON_SHELF,  # Repaired / restored to shelf
        BookCopyStatus.LOST,      # Written off / discarded
    },
    BookCopyStatus.LOST: {
        BookCopyStatus.ON_SHELF,  # Recovered / found and returned to circulation
    },
}
