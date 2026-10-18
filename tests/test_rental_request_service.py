"""Tests for rental request service, owner approvals, payment verification, and physical checkout."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
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
from app.models.ledger import CollateralLedger
from app.models.rental_request import Payment, RentalRequest
from app.services.due_date import calculate_due_date
from app.services.ledger import get_customer_collateral_balance
from app.services.rental_request import (
    approve_rental_request,
    cancel_rental_request,
    confirm_physical_handover,
    get_active_rental_requests,
    record_non_cash_guarantee,
    record_payment_verification,
    reject_rental_request,
    submit_rental_request,
)

OWNER_ID = 100000001
NON_OWNER_ID = 200000002


@pytest.fixture(autouse=True)
def setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure test environment with OWNER_ID authorized as admin."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ADMIN_USER_IDS", str(OWNER_ID))
    monkeypatch.setenv("RENTAL_TIMEZONE", "UTC")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def setup_customer_and_book(db_session: Session) -> tuple[Customer, Book, BookCopy]:
    """Helper fixture to create an approved customer and a catalogued book with one available copy."""
    customer = Customer(
        telegram_id=300000003,
        first_name="Alice",
        last_name="Reader",
        username="alicereader",
        status=CustomerStatus.APPROVED.value,
    )
    db_session.add(customer)

    book = Book(
        isbn="9780132350884",
        title="Clean Code",
        author="Robert C. Martin",
        rental_price=Decimal("12.50"),
    )
    db_session.add(book)
    db_session.flush()

    copy = BookCopy(
        book_id=book.id,
        copy_number=1,
        barcode="9780132350884-001",
        status=BookCopyStatus.ON_SHELF.value,
    )
    db_session.add(copy)
    db_session.commit()

    return customer, book, copy


# ==============================================================================
# 1. Rental Request Submission Tests
# ==============================================================================


def test_submit_rental_request_success(db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]) -> None:
    """Approved customer can submit a rental request when a copy is ON_SHELF."""
    customer, book, _ = setup_customer_and_book

    req = submit_rental_request(
        session=db_session,
        customer_id=customer.id,
        book_id=book.id,
        collateral_type=CollateralType.MONETARY,
    )
    db_session.commit()

    assert req.id is not None
    assert req.customer_id == customer.id
    assert req.book_id == book.id
    assert req.copy_id is None  # Copy is NOT allocated until approval!
    assert req.status == RentalRequestStatus.SUBMITTED.value
    assert req.rental_fee == Decimal("12.50")
    assert req.rental_fee_paid is False
    assert req.collateral_received is False
    assert req.collateral_type == CollateralType.MONETARY.value


def test_submit_rental_request_with_guarantee(db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]) -> None:
    """Approved customer can submit a rental request with a non-cash guarantee arrangement."""
    customer, book, _ = setup_customer_and_book

    req = submit_rental_request(
        session=db_session,
        customer_id=customer.id,
        book_id=book.id,
        collateral_type=CollateralType.GUARANTEE,
        guarantee_details="Held Passport #AB123456",
    )
    db_session.commit()

    assert req.collateral_type == CollateralType.GUARANTEE.value
    assert req.guarantee_details == "Held Passport #AB123456"
    assert req.status == RentalRequestStatus.SUBMITTED.value


def test_submit_rental_request_unapproved_customer_rejected(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Pending or unapproved customer cannot submit a rental request."""
    _, book, _ = setup_customer_and_book

    pending_cust = Customer(
        telegram_id=400000004,
        first_name="Bob",
        status=CustomerStatus.PENDING.value,
    )
    db_session.add(pending_cust)
    db_session.commit()

    with pytest.raises(CustomerNotApprovedError, match="must be APPROVED"):
        submit_rental_request(db_session, pending_cust.id, book.id)


def test_submit_rental_request_nonexistent_customer(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Non-existent customer raises CustomerNotFoundError."""
    _, book, _ = setup_customer_and_book
    with pytest.raises(CustomerNotFoundError):
        submit_rental_request(db_session, customer_id=999999, book_id=book.id)


def test_submit_rental_request_no_available_copies(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Submitting a request fails if no copies of the book are ON_SHELF."""
    customer, book, copy = setup_customer_and_book
    # Mark the only copy as RENTED
    copy.status = BookCopyStatus.RENTED.value
    db_session.commit()

    with pytest.raises(CopyNotAvailableError, match="available on shelf"):
        submit_rental_request(db_session, customer.id, book.id)


# ==============================================================================
# 2. Owner Approval & Copy Reservation Tests
# ==============================================================================


def test_approve_rental_request_success(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Owner approval atomically reserves one available physical copy."""
    customer, book, copy = setup_customer_and_book

    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    approved_req = approve_rental_request(
        session=db_session,
        request_id=req.id,
        actor_telegram_id=OWNER_ID,
    )
    db_session.commit()

    assert approved_req.status == RentalRequestStatus.APPROVED.value
    assert approved_req.copy_id == copy.id
    assert approved_req.reviewed_by == str(OWNER_ID)
    assert approved_req.reviewed_at is not None

    # Verify physical copy transitioned from ON_SHELF to RESERVED
    db_session.refresh(copy)
    assert copy.status == BookCopyStatus.RESERVED.value


def test_approve_rental_request_unauthorized(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Non-owner cannot approve a rental request."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    with pytest.raises(UnauthorizedError):
        approve_rental_request(db_session, req.id, actor_telegram_id=NON_OWNER_ID)


def test_approve_rental_request_already_approved(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Attempting to approve a request that is not SUBMITTED raises error."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    with pytest.raises(InvalidRentalRequestStatusError, match="only SUBMITTED"):
        approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)


def test_concurrent_approval_single_copy_reservation(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """When only 1 copy is available, approving two competing requests reserves it for the first, failing the second."""
    customer1, book, copy = setup_customer_and_book

    customer2 = Customer(
        telegram_id=500000005,
        first_name="Charlie",
        status=CustomerStatus.APPROVED.value,
    )
    db_session.add(customer2)
    db_session.flush()

    req1 = submit_rental_request(db_session, customer1.id, book.id)
    req2 = submit_rental_request(db_session, customer2.id, book.id)
    db_session.commit()

    # First approval succeeds and claims the only ON_SHELF copy
    approved1 = approve_rental_request(db_session, req1.id, actor_telegram_id=OWNER_ID)
    db_session.commit()
    assert approved1.copy_id == copy.id

    # Second approval fails because no ON_SHELF copies remain
    with pytest.raises(CopyNotAvailableError, match="available for allocation"):
        approve_rental_request(db_session, req2.id, actor_telegram_id=OWNER_ID)


# ==============================================================================
# 3. Owner Rejection & Copy Release Tests
# ==============================================================================


def test_reject_submitted_request(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Owner can reject a SUBMITTED request."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    rejected = reject_rental_request(
        session=db_session,
        request_id=req.id,
        actor_telegram_id=OWNER_ID,
        reason="Suspicious history",
    )
    db_session.commit()

    assert rejected.status == RentalRequestStatus.REJECTED.value
    assert rejected.rejection_reason == "Suspicious history"
    assert rejected.copy_id is None


def test_reject_approved_request_releases_reserved_copy(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Rejecting an already approved request releases the reserved copy back to ON_SHELF."""
    customer, book, copy = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    db_session.refresh(copy)
    assert copy.status == BookCopyStatus.RESERVED.value

    # Now reject the request
    reject_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID, reason="Customer cancelled pickup")
    db_session.commit()

    db_session.refresh(copy)
    assert copy.status == BookCopyStatus.ON_SHELF.value
    db_session.refresh(req)
    assert req.status == RentalRequestStatus.REJECTED.value
    assert req.copy_id is None


def test_reject_request_unauthorized(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Non-owner cannot reject a request."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    with pytest.raises(UnauthorizedError):
        reject_rental_request(db_session, req.id, actor_telegram_id=NON_OWNER_ID)


# ==============================================================================
# 4. Request Cancellation Tests
# ==============================================================================


def test_cancel_request_by_customer(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Customer can cancel their own request, releasing any reserved copy."""
    customer, book, copy = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()
    assert copy.status == BookCopyStatus.RESERVED.value

    # Customer cancels
    cancel_rental_request(db_session, req.id, actor_telegram_id=customer.telegram_id, reason="Changed mind")
    db_session.commit()

    db_session.refresh(copy)
    assert copy.status == BookCopyStatus.ON_SHELF.value
    db_session.refresh(req)
    assert req.status == RentalRequestStatus.CANCELLED.value


def test_cancel_request_by_third_party_denied(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Unrelated third party cannot cancel another customer's request."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    with pytest.raises(UnauthorizedError):
        cancel_rental_request(db_session, req.id, actor_telegram_id=NON_OWNER_ID)


# ==============================================================================
# 5. Payment & Collateral Verification Tests
# ==============================================================================


def test_record_payment_verification_rental_fee(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Owner records manually verified cash payment for rental fee."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    payment = record_payment_verification(
        session=db_session,
        request_id=req.id,
        payment_type=PaymentType.RENTAL_FEE,
        payment_method=PaymentMethod.CASH,
        amount=Decimal("12.50"),
        actor_telegram_id=OWNER_ID,
        reference="Front desk cash receipt #8812",
    )
    db_session.commit()

    assert payment.id is not None
    assert payment.payment_type == PaymentType.RENTAL_FEE.value
    assert payment.payment_method == PaymentMethod.CASH.value
    assert payment.amount == Decimal("12.50")
    assert payment.verified_by == str(OWNER_ID)

    db_session.refresh(req)
    assert req.rental_fee_paid is True

    # Verify discrete ledger entry was recorded
    ledger = db_session.query(CollateralLedger).filter_by(customer_id=customer.id).first()
    assert ledger is not None
    assert ledger.transaction_type == LedgerTransactionType.RENTAL_FEE.value
    assert ledger.amount == Decimal("12.50")


def test_record_payment_verification_duplicate_fee_prevented(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Recording payment twice for rental fee is blocked by idempotency guard."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    record_payment_verification(
        session=db_session,
        request_id=req.id,
        payment_type=PaymentType.RENTAL_FEE,
        payment_method=PaymentMethod.CASH,
        amount=Decimal("12.50"),
        actor_telegram_id=OWNER_ID,
    )
    db_session.commit()

    with pytest.raises(PaymentAlreadyVerifiedError, match="already been verified"):
        record_payment_verification(
            session=db_session,
            request_id=req.id,
            payment_type=PaymentType.RENTAL_FEE,
            payment_method=PaymentMethod.CASH,
            amount=Decimal("12.50"),
            actor_telegram_id=OWNER_ID,
        )


def test_record_payment_verification_collateral_deposit(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Owner records bank transfer for monetary collateral deposit, updating customer balance."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    payment = record_payment_verification(
        session=db_session,
        request_id=req.id,
        payment_type=PaymentType.COLLATERAL_DEPOSIT,
        payment_method=PaymentMethod.BANK_TRANSFER,
        amount=Decimal("50.00"),
        actor_telegram_id=OWNER_ID,
        reference="Bank TX #9918237",
    )
    db_session.commit()

    db_session.refresh(req)
    assert req.collateral_received is True
    assert req.collateral_amount == Decimal("50.00")

    # Customer collateral balance should now be 50.00
    balance = get_customer_collateral_balance(db_session, customer.id)
    assert balance == Decimal("50.00")


def test_record_payment_float_amount_rejected(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Passing float amounts to record_payment_verification is strictly rejected."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    with pytest.raises(TypeError, match="must be Decimal or integer string, never float"):
        record_payment_verification(
            session=db_session,
            request_id=req.id,
            payment_type=PaymentType.RENTAL_FEE,
            payment_method=PaymentMethod.CASH,
            amount=12.50,  # float!
            actor_telegram_id=OWNER_ID,
        )


def test_record_non_cash_guarantee_no_cash_ledger_impact(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Recording a non-cash guarantee satisfies collateral requirement without adding money to CollateralLedger."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(
        db_session,
        customer.id,
        book.id,
        collateral_type=CollateralType.GUARANTEE,
        guarantee_details="Held Passport #AB998877",
    )
    db_session.commit()

    # Initial collateral balance is 0.00
    assert get_customer_collateral_balance(db_session, customer.id) == Decimal("0.00")

    payment = record_non_cash_guarantee(
        session=db_session,
        request_id=req.id,
        actor_telegram_id=OWNER_ID,
        guarantee_details="Held Passport #AB998877 verified and placed in safe box",
    )
    db_session.commit()

    assert payment.payment_method == PaymentMethod.NON_CASH_GUARANTEE.value
    assert payment.amount == Decimal("0.00")

    db_session.refresh(req)
    assert req.collateral_received is True
    assert req.collateral_type == CollateralType.GUARANTEE.value

    # Cash ledger balance MUST REMAIN exactly 0.00!
    balance = get_customer_collateral_balance(db_session, customer.id)
    assert balance == Decimal("0.00")

    # There must be no COLLATERAL_DEPOSIT entry in collateral_ledger
    ledger_entries = (
        db_session.query(CollateralLedger)
        .filter_by(customer_id=customer.id, transaction_type=LedgerTransactionType.COLLATERAL_DEPOSIT.value)
        .all()
    )
    assert len(ledger_entries) == 0


# ==============================================================================
# 6. Physical Handover / Checkout Confirmation Tests
# ==============================================================================


def test_confirm_physical_handover_success(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Full lifecycle: Submit -> Approve -> Record Fee -> Record Guarantee -> Physical Checkout."""
    customer, book, copy = setup_customer_and_book

    # 1. Submit
    req = submit_rental_request(
        db_session,
        customer.id,
        book.id,
        collateral_type=CollateralType.GUARANTEE,
        guarantee_details="National ID #00129",
    )
    db_session.commit()

    # 2. Approve
    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    # 3. Pay fee
    record_payment_verification(
        session=db_session,
        request_id=req.id,
        payment_type=PaymentType.RENTAL_FEE,
        payment_method=PaymentMethod.CASH,
        amount=Decimal("12.50"),
        actor_telegram_id=OWNER_ID,
    )
    db_session.commit()

    # 4. Verify guarantee
    record_non_cash_guarantee(
        session=db_session,
        request_id=req.id,
        actor_telegram_id=OWNER_ID,
        guarantee_details="National ID #00129 verified",
    )
    db_session.commit()

    # 5. Physical Handover
    checkout_dt = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    rental = confirm_physical_handover(
        session=db_session,
        request_id=req.id,
        actor_telegram_id=OWNER_ID,
        checkout_time=checkout_dt,
        calendar_days=10,
    )
    db_session.commit()

    # Verify Rental record
    assert rental.id is not None
    assert rental.customer_id == customer.id
    assert rental.copy_id == copy.id
    assert rental.status == RentalStatus.ACTIVE.value
    assert rental.checkout_time == checkout_dt

    # Default 10 calendar days: Oct 16 + 10 = Oct 26 at 23:59:59 UTC
    expected_due = calculate_due_date(checkout_dt, calendar_days=10)
    assert rental.due_date == expected_due

    # Verify physical copy status changed to RENTED
    db_session.refresh(copy)
    assert copy.status == BookCopyStatus.RENTED.value

    # Verify request status changed to COMPLETED
    db_session.refresh(req)
    assert req.status == RentalRequestStatus.COMPLETED.value
    assert req.rental_id == rental.id


def test_handover_blocked_if_unapproved(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Cannot perform physical handover if request is only SUBMITTED."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    with pytest.raises(CheckoutConditionsNotMetError, match="must be APPROVED"):
        confirm_physical_handover(db_session, req.id, actor_telegram_id=OWNER_ID)


def test_handover_blocked_if_fee_unpaid(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Cannot perform physical handover if rental fee has not been verified."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    # Verify guarantee only, leave fee unpaid
    record_non_cash_guarantee(db_session, req.id, actor_telegram_id=OWNER_ID, guarantee_details="ID card")
    db_session.commit()

    with pytest.raises(CheckoutConditionsNotMetError, match="Rental fee has not been verified"):
        confirm_physical_handover(db_session, req.id, actor_telegram_id=OWNER_ID)


def test_handover_blocked_if_collateral_unverified(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Cannot perform physical handover if collateral/guarantee is unverified."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    # Verify fee only
    record_payment_verification(
        db_session, req.id, PaymentType.RENTAL_FEE, PaymentMethod.CASH, Decimal("12.50"), OWNER_ID
    )
    db_session.commit()

    with pytest.raises(CheckoutConditionsNotMetError, match="Collateral or guarantee requirement"):
        confirm_physical_handover(db_session, req.id, actor_telegram_id=OWNER_ID)


def test_duplicate_handover_prevented(
    db_session: Session, setup_customer_and_book: tuple[Customer, Book, BookCopy]
) -> None:
    """Calling confirm_physical_handover again raises RentalRequestAlreadyCompletedError."""
    customer, book, _ = setup_customer_and_book
    req = submit_rental_request(db_session, customer.id, book.id)
    db_session.commit()

    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    record_payment_verification(
        db_session, req.id, PaymentType.RENTAL_FEE, PaymentMethod.CASH, Decimal("12.50"), OWNER_ID
    )
    record_non_cash_guarantee(db_session, req.id, actor_telegram_id=OWNER_ID, guarantee_details="ID card")
    db_session.commit()

    confirm_physical_handover(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    with pytest.raises(RentalRequestAlreadyCompletedError, match="already been completed"):
        confirm_physical_handover(db_session, req.id, actor_telegram_id=OWNER_ID)
