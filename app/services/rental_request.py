"""Rental request, approval, payment/guarantee verification, and physical checkout service."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import (
    BookCopyStatus,
    CollateralType,
    CustomerStatus,
    LedgerTransactionType,
    PaymentMethod,
    PaymentType,
    PaymentVerificationStatus,
    RentalRequestStatus,
    RentalStatus,
)
from app.models.exceptions import (
    CheckoutConditionsNotMetError,
    CopyNotAvailableError,
    CustomerNotApprovedError,
    CustomerNotFoundError,
    InvalidRentalRequestStatusError,
    PaymentAlreadyVerifiedError,
    RentalRequestAlreadyCompletedError,
    RentalRequestNotFoundError,
    UnauthorizedError,
)
from app.models.rental import Rental
from app.models.rental_request import Payment, RentalRequest
from app.services.audit import record_audit_log
from app.services.customer import require_owner
from app.services.due_date import calculate_due_date
from app.services.ledger import record_ledger_entry

TWO_PLACES = Decimal("0.01")


def submit_rental_request(
    session: Session,
    customer_id: int,
    book_id: int,
    collateral_type: CollateralType | str = CollateralType.MONETARY,
    guarantee_details: Optional[str] = None,
    collateral_amount: Optional[Decimal | str] = None,
) -> RentalRequest:
    """Submit a new rental request by an approved customer.

    Args:
        session: Active SQLAlchemy database session.
        customer_id: ID of the Customer requesting the rental.
        book_id: ID of the catalogued Book title.
        collateral_type: CollateralType (MONETARY or GUARANTEE).
        guarantee_details: Optional documentation if collateral is a non-cash guarantee.
        collateral_amount: Optional explicit monetary collateral amount.

    Returns:
        The newly created RentalRequest in SUBMITTED status.

    Raises:
        CustomerNotFoundError: If customer does not exist.
        CustomerNotApprovedError: If customer is not APPROVED.
        CopyNotAvailableError: If no copies of the book are currently ON_SHELF.
    """
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise CustomerNotFoundError(f"Customer #{customer_id} not found")

    if not customer.is_approved:
        raise CustomerNotApprovedError(
            f"Customer #{customer.id} has status '{customer.status}'; must be APPROVED to request rentals."
        )

    book = session.get(Book, book_id)
    if book is None:
        raise ValueError(f"Book #{book_id} not found in catalogue")

    # Check that at least one copy is currently ON_SHELF
    available_copy = (
        session.query(BookCopy)
        .filter(BookCopy.book_id == book.id, BookCopy.status == BookCopyStatus.ON_SHELF.value)
        .first()
    )
    if not available_copy:
        raise CopyNotAvailableError(
            f"No copies of '{book.title}' are currently available on shelf."
        )

    ctype = collateral_type if isinstance(collateral_type, CollateralType) else CollateralType(collateral_type)

    dec_collat: Optional[Decimal] = None
    if collateral_amount is not None:
        dec_collat = Decimal(str(collateral_amount)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    request = RentalRequest(
        customer_id=customer.id,
        book_id=book.id,
        status=RentalRequestStatus.SUBMITTED.value,
        collateral_type=ctype.value,
        guarantee_details=guarantee_details.strip() if guarantee_details else None,
        rental_fee=book.rental_price,
        rental_fee_paid=False,
        collateral_amount=dec_collat,
        collateral_received=False,
    )
    session.add(request)
    session.flush([request])

    record_audit_log(
        session=session,
        entity_type="RENTAL_REQUEST",
        entity_id=request.id,
        action="SUBMIT",
        actor=str(customer.telegram_id),
        new_values={
            "customer_id": customer.id,
            "book_id": book.id,
            "rental_fee": str(request.rental_fee),
            "collateral_type": ctype.value,
        },
    )

    return request


def approve_rental_request(
    session: Session,
    request_id: int,
    actor_telegram_id: int,
    copy_id: Optional[int] = None,
) -> RentalRequest:
    """Owner-only action to approve a rental request and atomically reserve a physical copy.

    Guarantees concurrency safety by row-locking the allocated copy and transitioning
    it from ON_SHELF to RESERVED.

    Args:
        session: Active SQLAlchemy database session.
        request_id: ID of the RentalRequest.
        actor_telegram_id: Telegram user ID of approving owner.
        copy_id: Optional specific copy ID. If omitted, picks an available ON_SHELF copy.

    Returns:
        Approved RentalRequest with allocated copy_id.

    Raises:
        UnauthorizedError: If actor is not an authorized owner.
        RentalRequestNotFoundError: If request does not exist.
        InvalidRentalRequestStatusError: If request is not in SUBMITTED status.
        CopyNotAvailableError: If target or any copy is not ON_SHELF.
    """
    require_owner(actor_telegram_id)

    request = (
        session.query(RentalRequest)
        .filter(RentalRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise RentalRequestNotFoundError(f"RentalRequest #{request_id} not found")

    if request.status != RentalRequestStatus.SUBMITTED.value:
        raise InvalidRentalRequestStatusError(
            f"RentalRequest #{request.id} is in status '{request.status}'; only SUBMITTED requests can be approved."
        )

    # Allocate and lock physical copy
    if copy_id is not None:
        copy = (
            session.query(BookCopy)
            .filter(BookCopy.id == copy_id, BookCopy.book_id == request.book_id)
            .with_for_update()
            .first()
        )
    else:
        copy = (
            session.query(BookCopy)
            .filter(BookCopy.book_id == request.book_id, BookCopy.status == BookCopyStatus.ON_SHELF.value)
            .order_by(BookCopy.copy_number.asc())
            .with_for_update()
            .first()
        )

    if copy is None or copy.status != BookCopyStatus.ON_SHELF.value:
        raise CopyNotAvailableError(
            f"No physical copy of '{request.book.title}' is currently available for allocation."
        )

    # Transition copy to RESERVED
    copy.transition_to(BookCopyStatus.RESERVED, reason=f"Allocated to request #{request.id}")

    request.copy_id = copy.id
    request.status = RentalRequestStatus.APPROVED.value
    request.reviewed_at = datetime.now(timezone.utc)
    request.reviewed_by = str(actor_telegram_id)

    session.flush([request, copy])

    record_audit_log(
        session=session,
        entity_type="RENTAL_REQUEST",
        entity_id=request.id,
        action="APPROVE",
        actor=str(actor_telegram_id),
        new_values={
            "copy_id": copy.id,
            "copy_barcode": copy.barcode,
            "status": request.status,
        },
    )

    return request


def reject_rental_request(
    session: Session,
    request_id: int,
    actor_telegram_id: int,
    reason: Optional[str] = None,
) -> RentalRequest:
    """Owner-only action to reject a rental request, releasing any reserved copy.

    Args:
        session: Active SQLAlchemy database session.
        request_id: ID of RentalRequest.
        actor_telegram_id: Telegram user ID of rejecting owner.
        reason: Optional justification for rejection.

    Returns:
        Updated RentalRequest with REJECTED status.

    Raises:
        UnauthorizedError: If actor is not an owner.
        RentalRequestNotFoundError: If request does not exist.
        InvalidRentalRequestStatusError: If request was already completed.
    """
    require_owner(actor_telegram_id)

    request = (
        session.query(RentalRequest)
        .filter(RentalRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise RentalRequestNotFoundError(f"RentalRequest #{request_id} not found")

    if request.status in (
        RentalRequestStatus.COMPLETED.value,
        RentalRequestStatus.REJECTED.value,
        RentalRequestStatus.CANCELLED.value,
    ):
        raise InvalidRentalRequestStatusError(
            f"RentalRequest #{request.id} is in status '{request.status}' and cannot be rejected."
        )

    # If a physical copy was allocated and reserved, release it back to ON_SHELF
    if request.copy_id:
        copy = session.query(BookCopy).filter_by(id=request.copy_id).with_for_update().first()
        if copy and copy.status == BookCopyStatus.RESERVED.value:
            copy.transition_to(BookCopyStatus.ON_SHELF, reason=f"Released from rejected request #{request.id}")
        request.copy_id = None

    request.status = RentalRequestStatus.REJECTED.value
    request.rejection_reason = reason
    request.reviewed_at = datetime.now(timezone.utc)
    request.reviewed_by = str(actor_telegram_id)

    session.flush([request])

    record_audit_log(
        session=session,
        entity_type="RENTAL_REQUEST",
        entity_id=request.id,
        action="REJECT",
        actor=str(actor_telegram_id),
        reason=reason,
    )

    return request


def cancel_rental_request(
    session: Session,
    request_id: int,
    actor_telegram_id: int,
    reason: Optional[str] = None,
) -> RentalRequest:
    """Cancel a rental request by either the customer or owner, releasing any reserved copy.

    Args:
        session: Active SQLAlchemy database session.
        request_id: ID of RentalRequest.
        actor_telegram_id: Telegram user ID of caller.
        reason: Optional cancellation reason.

    Returns:
        Updated RentalRequest with CANCELLED status.
    """
    request = (
        session.query(RentalRequest)
        .filter(RentalRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise RentalRequestNotFoundError(f"RentalRequest #{request_id} not found")

    # Verify actor is either the requesting customer or an owner
    if request.customer.telegram_id != actor_telegram_id:
        require_owner(actor_telegram_id)

    if request.status in (
        RentalRequestStatus.COMPLETED.value,
        RentalRequestStatus.REJECTED.value,
        RentalRequestStatus.CANCELLED.value,
    ):
        raise InvalidRentalRequestStatusError(
            f"RentalRequest #{request.id} is in status '{request.status}' and cannot be cancelled."
        )

    # Release any reserved copy
    if request.copy_id:
        copy = session.query(BookCopy).filter_by(id=request.copy_id).with_for_update().first()
        if copy and copy.status == BookCopyStatus.RESERVED.value:
            copy.transition_to(BookCopyStatus.ON_SHELF, reason=f"Released from cancelled request #{request.id}")
        request.copy_id = None

    request.status = RentalRequestStatus.CANCELLED.value
    session.flush([request])

    record_audit_log(
        session=session,
        entity_type="RENTAL_REQUEST",
        entity_id=request.id,
        action="CANCEL",
        actor=str(actor_telegram_id),
        reason=reason,
    )

    return request


def record_payment_verification(
    session: Session,
    request_id: int,
    payment_type: PaymentType | str,
    payment_method: PaymentMethod | str,
    amount: Decimal | str | int,
    actor_telegram_id: int,
    reference: Optional[str] = None,
) -> Payment:
    """Owner-only recording of a manually verified cash or bank transfer payment.

    Enforces that:
    1. Caller is an authorized owner.
    2. Payment amount is strictly Decimal and positive.
    3. Cash and bank transfers are manually verified by staff identity.
    4. Discrete ledger transaction is recorded in CollateralLedger.
    5. Duplicate payments for the same fee/collateral are blocked.

    Args:
        session: Active SQLAlchemy database session.
        request_id: ID of the RentalRequest.
        payment_type: PaymentType (RENTAL_FEE or COLLATERAL_DEPOSIT).
        payment_method: PaymentMethod (CASH, BANK_TRANSFER, OTHER).
        amount: Monetary value.
        actor_telegram_id: Telegram user ID of verifying owner.
        reference: Optional receipt or bank reference.

    Returns:
        Verified Payment instance.

    Raises:
        UnauthorizedError: If actor is not an owner.
        TypeError: If amount is float.
        PaymentAlreadyVerifiedError: If fee/collateral is already verified.
    """
    require_owner(actor_telegram_id)

    if isinstance(amount, float):
        raise TypeError("Payment amount must be Decimal or integer string, never float")

    dec_amount = Decimal(str(amount)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if dec_amount <= Decimal("0.00"):
        raise ValueError("Payment amount must be strictly positive")

    request = (
        session.query(RentalRequest)
        .filter(RentalRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise RentalRequestNotFoundError(f"RentalRequest #{request_id} not found")

    ptype = payment_type if isinstance(payment_type, PaymentType) else PaymentType(payment_type)
    pmethod = payment_method if isinstance(payment_method, PaymentMethod) else PaymentMethod(payment_method)

    # Check for duplicate verification
    if ptype == PaymentType.RENTAL_FEE and request.rental_fee_paid:
        raise PaymentAlreadyVerifiedError(f"Rental fee for request #{request.id} has already been verified.")
    if ptype == PaymentType.COLLATERAL_DEPOSIT and request.collateral_received:
        raise PaymentAlreadyVerifiedError(f"Collateral for request #{request.id} has already been verified.")

    now = datetime.now(timezone.utc)
    payment = Payment(
        request_id=request.id,
        customer_id=request.customer_id,
        payment_type=ptype.value,
        payment_method=pmethod.value,
        amount=dec_amount,
        verification_status=PaymentVerificationStatus.VERIFIED.value,
        verified_at=now,
        verified_by=str(actor_telegram_id),
        reference=reference,
    )
    session.add(payment)

    # Update request state & record discrete transaction in financial ledger
    if ptype == PaymentType.RENTAL_FEE:
        request.rental_fee_paid = True
        record_ledger_entry(
            session=session,
            customer_id=request.customer_id,
            transaction_type=LedgerTransactionType.RENTAL_FEE,
            amount=dec_amount,
            notes=f"Verified rental fee payment for request #{request.id} via {pmethod.value}",
            actor=f"OWNER:{actor_telegram_id}",
        )
    else:
        request.collateral_received = True
        request.collateral_amount = dec_amount
        record_ledger_entry(
            session=session,
            customer_id=request.customer_id,
            transaction_type=LedgerTransactionType.COLLATERAL_DEPOSIT,
            amount=dec_amount,
            notes=f"Verified collateral deposit for request #{request.id} via {pmethod.value}",
            actor=f"OWNER:{actor_telegram_id}",
        )

    session.flush([payment, request])

    record_audit_log(
        session=session,
        entity_type="PAYMENT",
        entity_id=payment.id,
        action="VERIFY_PAYMENT",
        actor=str(actor_telegram_id),
        new_values={
            "request_id": request.id,
            "type": ptype.value,
            "method": pmethod.value,
            "amount": str(dec_amount),
            "reference": reference,
        },
    )

    return payment


def record_non_cash_guarantee(
    session: Session,
    request_id: int,
    guarantee_details: str,
    actor_telegram_id: int,
) -> Payment:
    """Owner-only action to record a non-cash collateral guarantee (e.g. passport, student ID).

    Crucial: Non-cash guarantees are recorded as verified arrangements without
    adding monetary funds to the cash ledger.

    Args:
        session: Active SQLAlchemy database session.
        request_id: ID of RentalRequest.
        guarantee_details: Documentation of guarantee held (e.g. 'National ID #123456 held at counter').
        actor_telegram_id: Telegram user ID of verifying owner.

    Returns:
        Payment record documenting the guarantee arrangement.

    Raises:
        UnauthorizedError: If actor is not an owner.
        PaymentAlreadyVerifiedError: If collateral requirement was already satisfied.
    """
    require_owner(actor_telegram_id)

    if not guarantee_details or not guarantee_details.strip():
        raise ValueError("Guarantee details cannot be empty")

    request = (
        session.query(RentalRequest)
        .filter(RentalRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise RentalRequestNotFoundError(f"RentalRequest #{request_id} not found")

    if request.collateral_received:
        raise PaymentAlreadyVerifiedError(f"Collateral requirement for request #{request.id} is already satisfied.")

    now = datetime.now(timezone.utc)
    payment = Payment(
        request_id=request.id,
        customer_id=request.customer_id,
        payment_type=PaymentType.COLLATERAL_DEPOSIT.value,
        payment_method=PaymentMethod.NON_CASH_GUARANTEE.value,
        amount=Decimal("0.00"),
        verification_status=PaymentVerificationStatus.VERIFIED.value,
        verified_at=now,
        verified_by=str(actor_telegram_id),
        reference=guarantee_details.strip(),
    )
    session.add(payment)

    request.collateral_type = CollateralType.GUARANTEE.value
    request.guarantee_details = guarantee_details.strip()
    request.collateral_received = True

    session.flush([payment, request])

    record_audit_log(
        session=session,
        entity_type="RENTAL_REQUEST",
        entity_id=request.id,
        action="RECORD_GUARANTEE",
        actor=str(actor_telegram_id),
        new_values={
            "details": request.guarantee_details,
            "verified_by": str(actor_telegram_id),
        },
    )

    return payment


def confirm_physical_handover(
    session: Session,
    request_id: int,
    actor_telegram_id: int,
    checkout_time: Optional[datetime] = None,
    calendar_days: int = 10,
) -> Rental:
    """Owner-only confirmation of physical book handover to customer.

    This is the ONLY action that:
    1. Starts the official rental period.
    2. Transitions the physical copy from RESERVED to RENTED.
    3. Records checkout time and calculates the 10-calendar-day return deadline.
    4. Creates the official Rental record.

    Preconditions:
    - Request must be APPROVED.
    - Copy must be allocated.
    - Rental fee must be verified as paid.
    - Collateral must be verified (monetary deposit or non-cash guarantee).

    Args:
        session: Active SQLAlchemy database session.
        request_id: ID of the RentalRequest.
        actor_telegram_id: Telegram user ID of owner handing over the book.
        checkout_time: Optional explicit handover timestamp (defaults to current UTC time).
        calendar_days: Default rental calendar days (default: 10).

    Returns:
        The newly created and activated Rental instance.

    Raises:
        UnauthorizedError: If actor is not an owner.
        RentalRequestNotFoundError: If request does not exist.
        RentalRequestAlreadyCompletedError: If handover was already completed.
        CheckoutConditionsNotMetError: If preconditions (payment, approval, copy) are unmet.
    """
    require_owner(actor_telegram_id)

    request = (
        session.query(RentalRequest)
        .filter(RentalRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise RentalRequestNotFoundError(f"RentalRequest #{request_id} not found")

    if request.status == RentalRequestStatus.COMPLETED.value:
        raise RentalRequestAlreadyCompletedError(
            f"Physical handover for request #{request.id} has already been completed."
        )

    can_checkout, reason = request.can_checkout()
    if not can_checkout:
        raise CheckoutConditionsNotMetError(f"Cannot proceed with handover: {reason}")

    # Row-lock copy
    copy = session.query(BookCopy).filter_by(id=request.copy_id).with_for_update().first()
    if copy is None:
        raise CopyNotAvailableError(f"Allocated physical copy #{request.copy_id} was not found")

    ts = checkout_time or datetime.now(timezone.utc)
    due_date = calculate_due_date(checkout_time=ts, calendar_days=calendar_days)

    # Transition copy from RESERVED to RENTED
    copy.transition_to(
        BookCopyStatus.RENTED,
        reason=f"Handed over to customer #{request.customer_id} (Request #{request.id})",
    )

    rental = Rental(
        copy_id=copy.id,
        customer_id=request.customer_id,
        checkout_time=ts,
        due_date=due_date,
        return_time=None,
        status=RentalStatus.ACTIVE.value,
    )
    session.add(rental)
    session.flush([rental])

    request.rental_id = rental.id
    request.status = RentalRequestStatus.COMPLETED.value

    # Associate any previous ledger fee/collateral entries with this new rental record
    from app.models.ledger import CollateralLedger

    session.query(CollateralLedger).filter(
        CollateralLedger.customer_id == request.customer_id,
        CollateralLedger.rental_id.is_(None),
        CollateralLedger.notes.like(f"%request #{request.id}%"),
    ).update({"rental_id": rental.id}, synchronize_session="fetch")

    session.flush([request, copy])

    record_audit_log(
        session=session,
        entity_type="RENTAL",
        entity_id=rental.id,
        action="PHYSICAL_HANDOVER",
        actor=str(actor_telegram_id),
        new_values={
            "request_id": request.id,
            "copy_id": copy.id,
            "barcode": copy.barcode,
            "checkout_time": ts.isoformat(),
            "due_date": due_date.isoformat(),
        },
    )

    return rental


def get_active_rental_requests(
    session: Session,
    customer_id: Optional[int] = None,
    status: Optional[RentalRequestStatus | str] = None,
) -> List[RentalRequest]:
    """Retrieve rental requests filtered by customer or status."""
    query = session.query(RentalRequest)
    if customer_id is not None:
        query = query.filter(RentalRequest.customer_id == customer_id)
    if status is not None:
        st_val = status.value if isinstance(status, RentalRequestStatus) else str(status)
        query = query.filter(RentalRequest.status == st_val)

    return query.order_by(RentalRequest.created_at.desc()).all()
