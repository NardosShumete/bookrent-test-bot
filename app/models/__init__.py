"""Models package exporting all ORM models, enums, and exceptions."""

from app.models.audit import AuditLog
from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import (
    VALID_COPY_TRANSITIONS,
    BookCopyStatus,
    CollateralType,
    CustomerStatus,
    ExtensionStatus,
    LedgerTransactionType,
    PaymentMethod,
    PaymentType,
    PaymentVerificationStatus,
    RentalRequestStatus,
    RentalStatus,
)
from app.models.exceptions import (
    ActiveExtensionRequestExistsError,
    BookRentError,
    CheckoutConditionsNotMetError,
    CopyNotAvailableError,
    CopyNotFoundError,
    CustomerNotApprovedError,
    CustomerNotFoundError,
    ExtensionAlreadyAppliedError,
    ExtensionInvalidStatusError,
    ExtensionPaymentNotVerifiedError,
    InsufficientCollateralError,
    InvalidCustomerStatusError,
    InvalidISBNError,
    InvalidRentalRequestStatusError,
    InvalidReturnConditionError,
    InvalidStatusTransitionError,
    MissingBookDetailsError,
    PaymentAlreadyVerifiedError,
    PaymentNotFoundError,
    RentalAlreadyReturnedError,
    RentalNotActiveError,
    RentalNotFoundError,
    RentalRequestAlreadyCompletedError,
    RentalRequestNotFoundError,
    UnauthorizedError,
)
from app.models.ledger import CollateralLedger
from app.models.overdue import OverdueCharge
from app.models.rental import Rental, RentalExtension
from app.models.rental_request import Payment, RentalRequest

__all__ = [
    # Models
    "Book",
    "BookCopy",
    "Customer",
    "Rental",
    "RentalExtension",
    "RentalRequest",
    "Payment",
    "CollateralLedger",
    "AuditLog",
    "OverdueCharge",
    # Enums & Rules
    "BookCopyStatus",
    "CustomerStatus",
    "RentalStatus",
    "ExtensionStatus",
    "LedgerTransactionType",
    "RentalRequestStatus",
    "CollateralType",
    "PaymentType",
    "PaymentMethod",
    "PaymentVerificationStatus",
    "VALID_COPY_TRANSITIONS",
    # Exceptions
    "BookRentError",
    "InvalidISBNError",
    "InvalidStatusTransitionError",
    "CopyNotAvailableError",
    "CopyNotFoundError",
    "CustomerNotFoundError",
    "CustomerNotApprovedError",
    "ExtensionAlreadyAppliedError",
    "ExtensionInvalidStatusError",
    "ExtensionPaymentNotVerifiedError",
    "ActiveExtensionRequestExistsError",
    "RentalAlreadyReturnedError",
    "InvalidReturnConditionError",
    "RentalNotActiveError",
    "RentalNotFoundError",
    "InsufficientCollateralError",
    "MissingBookDetailsError",
    "UnauthorizedError",
    "InvalidCustomerStatusError",
    "RentalRequestNotFoundError",
    "InvalidRentalRequestStatusError",
    "RentalRequestAlreadyCompletedError",
    "PaymentAlreadyVerifiedError",
    "CheckoutConditionsNotMetError",
    "PaymentNotFoundError",
]

