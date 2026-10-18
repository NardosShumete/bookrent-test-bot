from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.book import BookCopy
from app.models.customer import Customer
from app.models.enums import (
    BookCopyStatus,
    CustomerStatus,
    ExtensionStatus,
    LedgerTransactionType,
    PaymentMethod,
    PaymentType,
    PaymentVerificationStatus,
    RentalStatus,
)
from app.models.exceptions import (
    ActiveExtensionRequestExistsError,
    CopyNotAvailableError,
    CopyNotFoundError,
    CustomerNotApprovedError,
    CustomerNotFoundError,
    ExtensionAlreadyAppliedError,
    ExtensionInvalidStatusError,
    ExtensionNotFoundError,
    ExtensionPaymentNotVerifiedError,
    InsufficientCollateralError,
    InvalidRentalRequestStatusError,
    InvalidReturnConditionError,
    PaymentAlreadyVerifiedError,
    RentalAlreadyReturnedError,
    RentalNotActiveError,
    RentalNotFoundError,
    UnauthorizedError,
)
from app.models.ledger import CollateralLedger
from app.models.overdue import OverdueCharge
from app.models.rental import Rental, RentalExtension
from app.models.rental_request import Payment, RentalRequest
from app.services.audit import record_audit_log
from app.services.customer import require_owner
from app.services.due_date import calculate_due_date, calculate_extension_due_date
from app.services.ledger import get_customer_collateral_balance, get_rental_ledger_summary, record_ledger_entry

TWO_PLACES = Decimal("0.01")



def create_rental(
    session: Session,
    copy_id: int,
    customer_id: int,
    checkout_time: datetime,
    due_date: datetime,
    actor: str = "SYSTEM",
) -> Rental:
    """Check out a physical book copy to an approved customer.

    Enforces that:
    1. Customer account exists and has status APPROVED.
    2. Physical copy exists, is ON_SHELF, and transitions atomically to RENTED.
    3. Due date is strictly on or after checkout time.
    4. Database partial unique index guarantees no double-allocation occurs.

    Args:
        session: Active SQLAlchemy database session.
        copy_id: ID of physical BookCopy to rent.
        customer_id: ID of Customer borrowing the copy.
        checkout_time: Timestamp when borrowing begins.
        due_date: Target return deadline.
        actor: Identity of actor performing the checkout.

    Returns:
        The newly created Rental instance.

    Raises:
        CustomerNotFoundError: If customer does not exist.
        CustomerNotApprovedError: If customer account is not APPROVED.
        CopyNotFoundError: If physical copy does not exist.
        CopyNotAvailableError: If physical copy is not ON_SHELF.
        ValueError: If due_date < checkout_time.
    """
    if due_date < checkout_time:
        raise ValueError(
            f"due_date ({due_date.isoformat()}) cannot be earlier than checkout_time ({checkout_time.isoformat()})"
        )

    customer = session.get(Customer, customer_id)
    if customer is None:
        raise CustomerNotFoundError(f"Customer with ID {customer_id} not found")

    if not customer.is_approved:
        raise CustomerNotApprovedError(
            f"Customer #{customer.id} has status '{customer.status}', but must be APPROVED to borrow books"
        )

    # Acquire row lock on the copy to prevent race conditions
    copy = (
        session.query(BookCopy)
        .filter(BookCopy.id == copy_id)
        .with_for_update()
        .first()
    )
    if copy is None:
        raise CopyNotFoundError(f"BookCopy with ID {copy_id} not found")

    if copy.status != BookCopyStatus.ON_SHELF.value:
        raise CopyNotAvailableError(
            f"Copy #{copy.id} (barcode: {copy.barcode}) is currently {copy.status}, not ON_SHELF"
        )

    # Transition copy status to RENTED
    copy.transition_to(BookCopyStatus.RENTED, reason=f"Rented to customer #{customer.id}")

    rental = Rental(
        copy_id=copy.id,
        customer_id=customer.id,
        checkout_time=checkout_time,
        due_date=due_date,
        return_time=None,
        status=RentalStatus.ACTIVE.value,
    )
    session.add(rental)
    session.flush([rental, copy])

    record_audit_log(
        session=session,
        entity_type="RENTAL",
        entity_id=rental.id,
        action="CHECKOUT",
        actor=actor,
        new_values={
            "copy_id": copy.id,
            "customer_id": customer.id,
            "checkout_time": checkout_time.isoformat(),
            "due_date": due_date.isoformat(),
        },
    )

    return rental


def request_extension(
    session: Session,
    rental_id: int,
    requested_days: int,
    new_due_date: datetime,
    fee: Decimal = Decimal("0.00"),
    actor: str = "CUSTOMER",
) -> RentalExtension:
    """Record a formal extension request for an active rental.

    Args:
        session: Active SQLAlchemy database session.
        rental_id: ID of the Rental to extend.
        requested_days: Number of days requested (must be > 0).
        new_due_date: Revised target due date (must be later than current due date).
        fee: Configured extension charge (defaults to 0.00).
        actor: Identity of actor making the request.

    Returns:
        Created RentalExtension in REQUESTED status.

    Raises:
        RentalNotFoundError: If rental does not exist.
        RentalNotActiveError: If rental is not currently active.
        ValueError: If days <= 0, new_due_date <= current due date, or fee is invalid.
    """
    if requested_days <= 0:
        raise ValueError("requested_days must be greater than zero")
    if isinstance(fee, float):
        raise TypeError("Extension fee must be Decimal or integer string, never float")
    if fee < 0:
        raise ValueError("Extension fee cannot be negative")

    rental = (
        session.query(Rental)
        .filter(Rental.id == rental_id)
        .with_for_update()
        .first()
    )
    if rental is None:
        raise RentalNotFoundError(f"Rental with ID {rental_id} not found")

    if not rental.is_active:
        raise RentalNotActiveError(
            f"Rental #{rental.id} has status '{rental.status}' and cannot be extended"
        )

    if new_due_date <= rental.due_date:
        raise ValueError(
            f"new_due_date ({new_due_date.isoformat()}) must be later than current due_date ({rental.due_date.isoformat()})"
        )

    extension = RentalExtension(
        rental_id=rental.id,
        requested_days=requested_days,
        previous_due_date=rental.due_date,
        new_due_date=new_due_date,
        fee=Decimal(str(fee)),
        status=ExtensionStatus.REQUESTED.value,
        is_applied=False,
    )
    session.add(extension)
    session.flush([extension])

    record_audit_log(
        session=session,
        entity_type="RENTAL_EXTENSION",
        entity_id=extension.id,
        action="REQUEST",
        actor=actor,
        new_values={
            "rental_id": rental.id,
            "requested_days": requested_days,
            "new_due_date": new_due_date.isoformat(),
            "fee": str(extension.fee),
        },
    )

    return extension


def approve_extension(
    session: Session,
    extension_id: int,
    reviewer: str = "OWNER",
) -> RentalExtension:
    """Approve a rental extension request and atomically update the rental due date.

    Guarantees that a revised due date cannot be applied more than once.

    Args:
        session: Active SQLAlchemy database session.
        extension_id: ID of the RentalExtension to approve.
        reviewer: Identifier of the approving owner or administrator.

    Returns:
        Approved RentalExtension instance.

    Raises:
        ExtensionNotFoundError: If extension does not exist.
        ExtensionAlreadyAppliedError: If extension has already been applied.
    """
    extension = (
        session.query(RentalExtension)
        .filter(RentalExtension.id == extension_id)
        .with_for_update()
        .first()
    )
    if extension is None:
        raise ExtensionNotFoundError(f"RentalExtension with ID {extension_id} not found")

    # Call model method which guards against duplicate application
    extension.apply_approval(reviewer=reviewer)
    session.flush([extension, extension.rental])

    record_audit_log(
        session=session,
        entity_type="RENTAL_EXTENSION",
        entity_id=extension.id,
        action="APPROVE",
        actor=reviewer,
        new_values={
            "rental_id": extension.rental_id,
            "new_due_date": extension.new_due_date.isoformat(),
            "is_applied": True,
        },
    )

    return extension


def reject_extension(
    session: Session,
    extension_id: int,
    reviewer: str = "OWNER",
    reason: Optional[str] = None,
) -> RentalExtension:
    """Reject a rental extension request without altering rental due date.

    Args:
        session: Active SQLAlchemy database session.
        extension_id: ID of the RentalExtension to reject.
        reviewer: Identifier of the rejecting owner or administrator.
        reason: Optional justification for rejection.

    Returns:
        Rejected RentalExtension instance.
    """
    extension = (
        session.query(RentalExtension)
        .filter(RentalExtension.id == extension_id)
        .with_for_update()
        .first()
    )
    if extension is None:
        raise ExtensionNotFoundError(f"RentalExtension with ID {extension_id} not found")

    extension.apply_rejection(reviewer=reviewer)
    session.flush([extension])

    record_audit_log(
        session=session,
        entity_type="RENTAL_EXTENSION",
        entity_id=extension.id,
        action="REJECT",
        actor=reviewer,
        reason=reason,
    )

    return extension


def return_rental(
    session: Session,
    rental_id: int,
    return_time: Optional[datetime] = None,
    copy_condition_status: BookCopyStatus | str = BookCopyStatus.ON_SHELF,
    damage_notes: Optional[str] = None,
    actor: str = "SYSTEM",
) -> Rental:
    """Process the return of a physical book copy, closing the rental record.

    Transitions the physical copy back to ON_SHELF (or DAMAGED if returned damaged).

    Args:
        session: Active SQLAlchemy database session.
        rental_id: ID of the active Rental to close.
        return_time: Optional explicit return timestamp (defaults to current UTC time).
        copy_condition_status: Target status for the copy (default: ON_SHELF).
        damage_notes: Optional notes regarding book condition upon return.
        actor: Identity of actor receiving the return.

    Returns:
        Closed Rental instance.

    Raises:
        RentalNotFoundError: If rental does not exist.
        RentalNotActiveError: If rental is already closed.
    """
    rental = (
        session.query(Rental)
        .filter(Rental.id == rental_id)
        .with_for_update()
        .first()
    )
    if rental is None:
        raise RentalNotFoundError(f"Rental with ID {rental_id} not found")

    if not rental.is_active:
        raise RentalNotActiveError(
            f"Rental #{rental.id} is already closed with status '{rental.status}'"
        )

    ts = return_time or datetime.now(timezone.utc)
    rental.return_time = ts
    rental.status = RentalStatus.RETURNED.value

    # Update copy status
    target = (
        copy_condition_status
        if isinstance(copy_condition_status, BookCopyStatus)
        else BookCopyStatus(copy_condition_status)
    )
    rental.copy.transition_to(target, reason=damage_notes or "Returned from rental")

    session.flush([rental, rental.copy])

    record_audit_log(
        session=session,
        entity_type="RENTAL",
        entity_id=rental.id,
        action="RETURN",
        actor=actor,
        new_values={
            "return_time": ts.isoformat(),
            "copy_status": rental.copy.status,
            "damage_notes": damage_notes,
        },
    )

    return rental


def submit_extension_request(
    session: Session,
    customer_telegram_id: int,
    rental_id: int,
) -> RentalExtension:
    """Submit a 5-calendar-day extension request for an active rental by an approved customer.

    Business Rules:
    - Customer must exist and have APPROVED status.
    - Rental must exist, belong to this customer, and be currently active.
    - Active rentals can request an extension whether overdue or not (accrued late fees are preserved).
    - Only one pending extension request may exist per rental at any given time.
    - Extension duration is exactly 5 calendar days.
    - Extension fee is exactly 10.00 ETB.

    Args:
        session: Active SQLAlchemy database session.
        customer_telegram_id: Telegram user ID of customer making request.
        rental_id: ID of the Rental to extend.

    Returns:
        Created RentalExtension instance in REQUESTED status.

    Raises:
        CustomerNotFoundError: If customer does not exist.
        CustomerNotApprovedError: If customer is not APPROVED.
        RentalNotFoundError: If rental does not exist.
        UnauthorizedError: If rental belongs to a different customer.
        RentalNotActiveError: If rental is already closed.
        ActiveExtensionRequestExistsError: If a pending extension request already exists.
    """
    customer = session.query(Customer).filter_by(telegram_id=customer_telegram_id).first()
    if customer is None:
        raise CustomerNotFoundError(f"Customer with Telegram ID {customer_telegram_id} not found")

    if not customer.is_approved:
        raise CustomerNotApprovedError(
            f"Customer #{customer.id} has status '{customer.status}'; must be APPROVED to request extensions."
        )

    rental = (
        session.query(Rental)
        .filter(Rental.id == rental_id)
        .with_for_update()
        .first()
    )
    if rental is None:
        raise RentalNotFoundError(f"Rental with ID {rental_id} not found")

    if rental.customer_id != customer.id:
        raise UnauthorizedError(
            f"Rental #{rental.id} does not belong to customer with Telegram ID {customer_telegram_id}"
        )

    if not rental.is_active:
        raise RentalNotActiveError(
            f"Rental #{rental.id} has status '{rental.status}' and cannot be extended"
        )

    # Prevent concurrent duplicate pending extension requests
    existing_pending = (
        session.query(RentalExtension)
        .filter(
            RentalExtension.rental_id == rental.id,
            RentalExtension.status == ExtensionStatus.REQUESTED.value,
        )
        .first()
    )
    if existing_pending:
        raise ActiveExtensionRequestExistsError(
            f"Rental #{rental.id} already has a pending extension request #{existing_pending.id}."
        )

    settings = get_settings()
    duration_days = getattr(settings, "extension_duration_days", 5)
    fee_amount = Decimal(str(getattr(settings, "extension_fee", Decimal("10.00")))).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )

    new_due_date = calculate_extension_due_date(
        current_due_date=rental.due_date,
        additional_days=duration_days,
        tz_name=settings.rental_timezone,
    )

    extension = RentalExtension(
        rental_id=rental.id,
        requested_days=duration_days,
        previous_due_date=rental.due_date,
        new_due_date=new_due_date,
        fee=fee_amount,
        status=ExtensionStatus.REQUESTED.value,
        is_applied=False,
        payment_verified=False,
    )
    session.add(extension)
    session.flush([extension])

    record_audit_log(
        session=session,
        entity_type="RENTAL_EXTENSION",
        entity_id=extension.id,
        action="REQUEST",
        actor=str(customer_telegram_id),
        new_values={
            "rental_id": rental.id,
            "requested_days": duration_days,
            "previous_due_date": rental.due_date.isoformat(),
            "new_due_date": new_due_date.isoformat(),
            "fee": str(fee_amount),
        },
    )

    return extension


def verify_extension_payment(
    session: Session,
    extension_id: int,
    payment_method: PaymentMethod | str,
    actor_telegram_id: int,
    reference: Optional[str] = None,
) -> Payment:
    """Owner-only manual verification of the 10 ETB extension fee payment.

    Args:
        session: Active SQLAlchemy database session.
        extension_id: ID of the RentalExtension.
        payment_method: PaymentMethod (CASH, BANK_TRANSFER, etc.).
        actor_telegram_id: Telegram user ID of verifying owner.
        reference: Optional receipt or bank transaction reference.

    Returns:
        Created and verified Payment instance.

    Raises:
        UnauthorizedError: If actor is not an owner.
        ExtensionNotFoundError: If extension does not exist.
        InvalidRentalRequestStatusError: If extension is not in REQUESTED status.
        PaymentAlreadyVerifiedError: If extension fee payment is already verified.
    """
    require_owner(actor_telegram_id)

    extension = (
        session.query(RentalExtension)
        .filter(RentalExtension.id == extension_id)
        .with_for_update()
        .first()
    )
    if extension is None:
        raise ExtensionNotFoundError(f"RentalExtension with ID {extension_id} not found")

    if extension.status != ExtensionStatus.REQUESTED.value:
        raise InvalidRentalRequestStatusError(
            f"Extension #{extension.id} is in status '{extension.status}' and cannot receive payment verification."
        )

    if extension.payment_verified:
        raise PaymentAlreadyVerifiedError(
            f"Payment for extension #{extension.id} has already been verified."
        )

    pmethod = (
        payment_method
        if isinstance(payment_method, PaymentMethod)
        else PaymentMethod(payment_method)
    )

    now = datetime.now(timezone.utc)
    payment = Payment(
        rental_id=extension.rental_id,
        extension_id=extension.id,
        customer_id=extension.rental.customer_id,
        payment_type=PaymentType.EXTENSION_FEE.value,
        payment_method=pmethod.value,
        amount=extension.fee,
        verification_status=PaymentVerificationStatus.VERIFIED.value,
        verified_at=now,
        verified_by=str(actor_telegram_id),
        reference=reference,
    )
    session.add(payment)

    extension.payment_verified = True
    extension.payment_method = pmethod.value
    extension.payment_reference = reference
    extension.payment_verified_at = now
    extension.payment_verified_by = str(actor_telegram_id)

    session.flush([payment, extension])

    record_audit_log(
        session=session,
        entity_type="PAYMENT",
        entity_id=payment.id,
        action="VERIFY_PAYMENT",
        actor=str(actor_telegram_id),
        new_values={
            "rental_id": extension.rental_id,
            "extension_id": extension.id,
            "type": PaymentType.EXTENSION_FEE.value,
            "method": pmethod.value,
            "amount": str(extension.fee),
            "reference": reference,
        },
    )

    return payment


def approve_rental_extension(
    session: Session,
    extension_id: int,
    actor_telegram_id: int,
) -> RentalExtension:
    """Owner-only approval of a rental extension whose payment is verified.

    Atomically updates the rental's due date by 5 calendar days.
    Guarantees that accrued overdue charges are preserved and never erased.

    Args:
        session: Active SQLAlchemy database session.
        extension_id: ID of the RentalExtension to approve.
        actor_telegram_id: Telegram user ID of approving owner.

    Returns:
        Approved RentalExtension instance.

    Raises:
        UnauthorizedError: If actor is not an owner.
        ExtensionNotFoundError: If extension does not exist.
        ExtensionPaymentNotVerifiedError: If fee payment has not been verified.
        ExtensionAlreadyAppliedError: If extension was already applied.
    """
    require_owner(actor_telegram_id)

    extension = (
        session.query(RentalExtension)
        .filter(RentalExtension.id == extension_id)
        .with_for_update()
        .first()
    )
    if extension is None:
        raise ExtensionNotFoundError(f"RentalExtension with ID {extension_id} not found")

    if not extension.payment_verified:
        raise ExtensionPaymentNotVerifiedError(
            f"Extension #{extension.id} fee payment has not been verified; cannot approve."
        )

    extension.apply_approval(reviewer=str(actor_telegram_id), require_payment_verified=True)
    session.flush([extension, extension.rental])

    record_audit_log(
        session=session,
        entity_type="RENTAL_EXTENSION",
        entity_id=extension.id,
        action="APPROVE",
        actor=str(actor_telegram_id),
        new_values={
            "rental_id": extension.rental_id,
            "new_due_date": extension.new_due_date.isoformat(),
            "is_applied": True,
        },
    )

    return extension


def verify_and_approve_extension(
    session: Session,
    extension_id: int,
    payment_method: PaymentMethod | str,
    actor_telegram_id: int,
    reference: Optional[str] = None,
) -> RentalExtension:
    """Atomic transaction boundary: verify extension payment and approve extension together.

    If any step fails, the entire transaction rolls back cleanly.

    Args:
        session: Active SQLAlchemy database session.
        extension_id: ID of the RentalExtension.
        payment_method: PaymentMethod (CASH, BANK_TRANSFER, etc.).
        actor_telegram_id: Telegram user ID of owner.
        reference: Optional payment receipt reference.

    Returns:
        Approved RentalExtension instance.
    """
    require_owner(actor_telegram_id)
    verify_extension_payment(
        session=session,
        extension_id=extension_id,
        payment_method=payment_method,
        actor_telegram_id=actor_telegram_id,
        reference=reference,
    )
    return approve_rental_extension(
        session=session,
        extension_id=extension_id,
        actor_telegram_id=actor_telegram_id,
    )


def reject_rental_extension(
    session: Session,
    extension_id: int,
    actor_telegram_id: int,
    reason: Optional[str] = None,
) -> RentalExtension:
    """Owner-only rejection of a rental extension request.

    Args:
        session: Active SQLAlchemy database session.
        extension_id: ID of the RentalExtension to reject.
        actor_telegram_id: Telegram user ID of rejecting owner.
        reason: Optional rejection reason.

    Returns:
        Rejected RentalExtension instance.

    Raises:
        UnauthorizedError: If actor is not an owner.
        ExtensionNotFoundError: If extension does not exist.
        ExtensionAlreadyAppliedError: If extension has already been applied.
    """
    require_owner(actor_telegram_id)

    extension = (
        session.query(RentalExtension)
        .filter(RentalExtension.id == extension_id)
        .with_for_update()
        .first()
    )
    if extension is None:
        raise ExtensionNotFoundError(f"RentalExtension with ID {extension_id} not found")

    extension.apply_rejection(reviewer=str(actor_telegram_id))
    session.flush([extension])

    record_audit_log(
        session=session,
        entity_type="RENTAL_EXTENSION",
        entity_id=extension.id,
        action="REJECT",
        actor=str(actor_telegram_id),
        reason=reason,
    )

    return extension


def confirm_rental_return(
    session: Session,
    rental_id: int,
    actor_telegram_id: int,
    condition_status: BookCopyStatus | str = BookCopyStatus.ON_SHELF,
    damage_notes: Optional[str] = None,
    return_time: Optional[datetime] = None,
    collateral_deduction: Optional[Decimal | str] = None,
    deduction_reason: Optional[str] = None,
    collateral_refund: Optional[Decimal | str] = None,
    refund_reason: Optional[str] = None,
) -> Rental:
    """Owner-only confirmation of physical book return and condition inspection.

    Responsibilities:
    1. Owner authorization enforcement.
    2. Idempotency: prevents already closed/returned rentals from being returned again.
    3. Records physical return timestamp and transitions rental to RETURNED.
    4. Freezes overdue accrual at the return timestamp and bills any unbilled overdue days prior to return.
    5. Validates physical book condition:
       - ON_SHELF: Returns usable, undamaged copy to shelf inventory.
       - DAMAGED: Moves copy to DAMAGED; copy is NOT made available on shelf.
       - LOST: Moves copy to LOST; copy is NOT made available on shelf.
    6. Collateral deductions require explicit owner authorization, non-zero amount, reason,
       and sufficient cash collateral (non-cash guarantees cannot be deducted as cash).
    7. Full audit trail recorded.

    Args:
        session: Active SQLAlchemy database session.
        rental_id: ID of active Rental.
        actor_telegram_id: Telegram user ID of owner.
        condition_status: Supported return condition (ON_SHELF, DAMAGED, LOST).
        damage_notes: Optional notes regarding condition or damage.
        return_time: Optional explicit physical return timestamp (defaults to UTC now).
        collateral_deduction: Optional owner-authorized deduction from monetary collateral.
        deduction_reason: Required reason if collateral_deduction > 0.
        collateral_refund: Optional collateral refund amount.
        refund_reason: Optional refund reason note.

    Returns:
        Closed Rental instance.

    Raises:
        UnauthorizedError: If actor is not an owner.
        RentalNotFoundError: If rental does not exist.
        RentalAlreadyReturnedError: If rental is already closed.
        InvalidReturnConditionError: If condition_status is not ON_SHELF, DAMAGED, or LOST.
        TypeError: If collateral_deduction or collateral_refund is a float.
        ValueError: If deduction > 0 without reason, or negative values.
        InsufficientCollateralError: If deduction/refund exceeds available cash collateral.
    """
    require_owner(actor_telegram_id)

    rental = (
        session.query(Rental)
        .filter(Rental.id == rental_id)
        .with_for_update()
        .first()
    )
    if rental is None:
        raise RentalNotFoundError(f"Rental with ID {rental_id} not found")

    if not rental.is_active:
        raise RentalAlreadyReturnedError(
            f"Rental #{rental.id} is already closed with status '{rental.status}'."
        )

    # Validate condition status
    valid_conditions = {
        BookCopyStatus.ON_SHELF.value: BookCopyStatus.ON_SHELF,
        BookCopyStatus.DAMAGED.value: BookCopyStatus.DAMAGED,
        BookCopyStatus.LOST.value: BookCopyStatus.LOST,
    }
    raw_status = condition_status.value if isinstance(condition_status, BookCopyStatus) else str(condition_status).upper()
    if raw_status not in valid_conditions:
        raise InvalidReturnConditionError(
            f"Invalid return condition '{condition_status}'. Must be ON_SHELF, DAMAGED, or LOST."
        )
    target_condition = valid_conditions[raw_status]

    ts = return_time or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    rental.return_time = ts
    rental.status = RentalStatus.RETURNED.value

    # Update physical copy status
    rental.copy.transition_to(target_condition, reason=damage_notes or f"Returned from rental #{rental.id}")

    # Accrue and record any unbilled overdue days prior to return_time
    from app.services.overdue import calculate_overdue_days_and_dates
    settings = get_settings()
    overdue_days, overdue_dates = calculate_overdue_days_and_dates(rental, as_of=ts)
    daily_fee = Decimal(str(getattr(settings, "overdue_daily_fee", Decimal("5.00")))).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    for dt in overdue_dates:
        existing = (
            session.query(OverdueCharge)
            .filter(OverdueCharge.rental_id == rental.id, OverdueCharge.overdue_date == dt)
            .first()
        )
        if not existing:
            charge = OverdueCharge(
                rental_id=rental.id,
                customer_id=rental.customer_id,
                overdue_date=dt,
                amount=daily_fee,
                notification_sent=False,
            )
            session.add(charge)

    # Process authorized collateral deduction
    if collateral_deduction is not None:
        if isinstance(collateral_deduction, float):
            raise TypeError("Collateral deduction must be Decimal or numeric string, never float")
        dec_deduct = Decimal(str(collateral_deduction)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if dec_deduct < Decimal("0.00"):
            raise ValueError("Collateral deduction cannot be negative")
        if dec_deduct > Decimal("0.00"):
            if not deduction_reason or not deduction_reason.strip():
                raise ValueError("deduction_reason is required when collateral_deduction is greater than zero.")
            record_ledger_entry(
                session=session,
                customer_id=rental.customer_id,
                transaction_type=LedgerTransactionType.COLLATERAL_DEDUCTION,
                amount=dec_deduct,
                rental_id=rental.id,
                notes=deduction_reason.strip(),
                actor=f"OWNER:{actor_telegram_id}",
            )

    # Process collateral refund
    if collateral_refund is not None:
        if isinstance(collateral_refund, float):
            raise TypeError("Collateral refund must be Decimal or numeric string, never float")
        dec_refund = Decimal(str(collateral_refund)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if dec_refund < Decimal("0.00"):
            raise ValueError("Collateral refund cannot be negative")
        if dec_refund > Decimal("0.00"):
            ref_notes = (refund_reason or f"Collateral refund for rental #{rental.id}").strip()
            record_ledger_entry(
                session=session,
                customer_id=rental.customer_id,
                transaction_type=LedgerTransactionType.COLLATERAL_REFUND,
                amount=dec_refund,
                rental_id=rental.id,
                notes=ref_notes,
                actor=f"OWNER:{actor_telegram_id}",
            )

    session.flush([rental, rental.copy])

    record_audit_log(
        session=session,
        entity_type="RENTAL",
        entity_id=rental.id,
        action="CONFIRM_RETURN",
        actor=str(actor_telegram_id),
        new_values={
            "return_time": ts.isoformat(),
            "copy_status": rental.copy.status,
            "damage_notes": damage_notes,
            "collateral_deduction": str(collateral_deduction) if collateral_deduction else None,
            "collateral_refund": str(collateral_refund) if collateral_refund else None,
        },
    )

    return rental


def get_rental_financial_reconciliation(session: Session, rental_id: int) -> dict:
    """Produce an exhaustive financial reconciliation summary for a rental.

    Keeps strictly separate:
    - Original rental fee
    - Monetary collateral received
    - Non-cash guarantees
    - Extension fee paid
    - Accrued overdue charges
    - Authorized collateral deductions
    - Collateral refunds
    - Net remaining collateral
    - Unpaid overdue balance

    Args:
        session: Active SQLAlchemy database session.
        rental_id: ID of the Rental.

    Returns:
        Structured reconciliation dictionary.

    Raises:
        RentalNotFoundError: If rental does not exist.
    """
    rental = session.get(Rental, rental_id)
    if rental is None:
        raise RentalNotFoundError(f"Rental with ID {rental_id} not found")

    # 1. Rental fee and initial collateral payments
    payments = (
        session.query(Payment)
        .filter(Payment.rental_id == rental.id)
        .all()
    )
    # Check if request has payments if none found directly
    request = session.query(RentalRequest).filter_by(rental_id=rental.id).first()
    if request:
        req_payments = session.query(Payment).filter_by(request_id=request.id).all()
        all_payments = list({p.id: p for p in payments + req_payments}.values())
    else:
        all_payments = payments

    original_rental_fee = Decimal("0.00")
    monetary_collateral = Decimal("0.00")
    has_non_cash_guarantee = False
    guarantee_details: Optional[str] = None
    extension_fee_paid = Decimal("0.00")

    for p in all_payments:
        if p.payment_type == PaymentType.RENTAL_FEE.value:
            original_rental_fee += p.amount
        elif p.payment_type == PaymentType.COLLATERAL_DEPOSIT.value:
            if p.payment_method == PaymentMethod.NON_CASH_GUARANTEE.value:
                has_non_cash_guarantee = True
                guarantee_details = p.reference
            else:
                monetary_collateral += p.amount
        elif p.payment_type == PaymentType.EXTENSION_FEE.value:
            extension_fee_paid += p.amount

    if request and request.guarantee_details:
        has_non_cash_guarantee = True
        guarantee_details = request.guarantee_details

    # 2. Overdue charges
    overdue_charges = (
        session.query(OverdueCharge)
        .filter(OverdueCharge.rental_id == rental.id)
        .order_by(OverdueCharge.overdue_date.asc())
        .all()
    )
    accrued_overdue_charges = sum((c.amount for c in overdue_charges), Decimal("0.00")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    overdue_days_count = len(overdue_charges)

    # 3. Ledger deductions and refunds
    ledger_summary = get_rental_ledger_summary(session, rental.id)
    collateral_deductions = ledger_summary.get(LedgerTransactionType.COLLATERAL_DEDUCTION.value, Decimal("0.00"))
    collateral_refunds = ledger_summary.get(LedgerTransactionType.COLLATERAL_REFUND.value, Decimal("0.00"))

    net_collateral_remaining = (monetary_collateral - collateral_deductions - collateral_refunds).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )

    return {
        "rental_id": rental.id,
        "customer_id": rental.customer_id,
        "book_title": rental.copy.book.title if rental.copy and rental.copy.book else "Unknown",
        "copy_barcode": rental.copy.barcode if rental.copy else "Unknown",
        "status": rental.status,
        "checkout_time": rental.checkout_time,
        "due_date": rental.due_date,
        "return_time": rental.return_time,
        "original_rental_fee": original_rental_fee.quantize(TWO_PLACES),
        "monetary_collateral_received": monetary_collateral.quantize(TWO_PLACES),
        "has_non_cash_guarantee": has_non_cash_guarantee,
        "guarantee_details": guarantee_details,
        "extension_fee_paid": extension_fee_paid.quantize(TWO_PLACES),
        "overdue_days": overdue_days_count,
        "accrued_overdue_charges": accrued_overdue_charges,
        "collateral_deductions": collateral_deductions,
        "collateral_refunds": collateral_refunds,
        "net_collateral_remaining": net_collateral_remaining,
        "unpaid_overdue_balance": accrued_overdue_charges,
    }


def get_customer_active_rentals(session: Session, customer_id: int) -> List[Rental]:
    """Retrieve all active or extended rentals for a customer."""
    return (
        session.query(Rental)
        .filter(
            Rental.customer_id == customer_id,
            Rental.status.in_([RentalStatus.ACTIVE.value, RentalStatus.EXTENDED.value]),
        )
        .order_by(Rental.checkout_time.desc())
        .all()
    )


def get_pending_extension_requests(session: Session) -> List[RentalExtension]:
    """Retrieve all pending rental extension requests requiring owner review."""
    return (
        session.query(RentalExtension)
        .filter(RentalExtension.status == ExtensionStatus.REQUESTED.value)
        .order_by(RentalExtension.requested_at.asc())
        .all()
    )

