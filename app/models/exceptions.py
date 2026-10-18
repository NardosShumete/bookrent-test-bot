"""Domain and model-level exceptions for BookRent Bot."""


class BookRentError(Exception):
    """Base exception for all domain and model errors in BookRent Bot."""

    pass


class InvalidISBNError(BookRentError, ValueError):
    """Raised when an ISBN is malformed, invalid length, or fails checksum verification."""

    pass


class InvalidStatusTransitionError(BookRentError, ValueError):
    """Raised when an illegal status transition is attempted on a physical copy or entity."""

    pass


class CopyNotAvailableError(BookRentError, RuntimeError):
    """Raised when attempting to allocate or rent a copy that is not ON_SHELF."""

    pass


class CopyNotFoundError(BookRentError, LookupError):
    """Raised when a physical book copy cannot be found by ID or barcode."""

    pass


class CustomerNotFoundError(BookRentError, LookupError):
    """Raised when a customer cannot be found by ID or Telegram ID."""

    pass


class CustomerNotApprovedError(BookRentError, PermissionError):
    """Raised when an unapproved (e.g. PENDING, SUSPENDED, REJECTED) customer attempts to rent."""

    pass


class ExtensionNotFoundError(BookRentError, LookupError):
    """Raised when a rental extension request is not found."""

    pass


class ExtensionAlreadyAppliedError(BookRentError, RuntimeError):
    """Raised when an extension has already been applied and cannot be applied again."""

    pass


class ExtensionInvalidStatusError(BookRentError, ValueError):
    """Raised when an extension transition is invalid (e.g. approving a rejected request)."""

    pass


class RentalNotActiveError(BookRentError, RuntimeError):
    """Raised when attempting an operation that requires an active rental on an inactive one."""

    pass


class RentalNotFoundError(BookRentError, LookupError):
    """Raised when a rental record cannot be found."""

    pass


class InsufficientCollateralError(BookRentError, ValueError):
    """Raised when a collateral deduction or refund exceeds the available balance."""

    pass


class MissingBookDetailsError(BookRentError, ValueError):
    """Raised when registering newly received copies for an uncatalogued ISBN without title/author."""

    pass


class UnauthorizedError(BookRentError, PermissionError):
    """Raised when a user attempts an owner-only or privileged action without authorization."""

    pass


class InvalidCustomerStatusError(BookRentError, ValueError):
    """Raised when an illegal transition or operation is attempted on a customer account."""

    pass


class RentalRequestNotFoundError(BookRentError, LookupError):
    """Raised when a rental request is not found."""

    pass


class InvalidRentalRequestStatusError(BookRentError, ValueError):
    """Raised when an operation is invalid for the current status of a rental request."""

    pass


class RentalRequestAlreadyCompletedError(BookRentError, RuntimeError):
    """Raised when an operation is attempted on an already completed rental request."""

    pass


class PaymentAlreadyVerifiedError(BookRentError, RuntimeError):
    """Raised when attempting to re-verify an already verified payment."""

    pass


class CheckoutConditionsNotMetError(BookRentError, RuntimeError):
    """Raised when handover/checkout is attempted without meeting approval and payment conditions."""

    pass


class PaymentNotFoundError(BookRentError, LookupError):
    """Raised when a payment record is not found."""

    pass


class ExtensionPaymentNotVerifiedError(BookRentError, RuntimeError):
    """Raised when approving an extension whose fee payment has not been verified."""

    pass


class ActiveExtensionRequestExistsError(BookRentError, RuntimeError):
    """Raised when submitting an extension request while one is already pending for that rental."""

    pass


class RentalAlreadyReturnedError(BookRentError, RuntimeError):
    """Raised when attempting to return an already returned/closed rental."""

    pass


class InvalidReturnConditionError(BookRentError, ValueError):
    """Raised when an invalid copy condition status is specified for return."""

    pass


