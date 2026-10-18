"""Tests for Telegram bot Phase 4 handlers: rental requests, approvals, payments, checkout, and callbacks."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.orm import Session
from telegram import CallbackQuery, Chat, Message, Update, User

from app.bot.handlers import (
    approvereq_command,
    checkout_command,
    recordguarantee_command,
    recordpayment_command,
    rejectreq_command,
    rent_command,
    rental_request_callback,
    requests_command,
)
from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import BookCopyStatus, CustomerStatus, RentalRequestStatus
from app.models.rental_request import RentalRequest
from app.services.book_catalog import create_book, receive_stock_for_isbn
from app.services.customer import approve_customer, register_customer
from app.services.rental_request import approve_rental_request, record_payment_verification, submit_rental_request

OWNER_ID = 12345
CUSTOMER_ID = 7701
OTHER_USER_ID = 9999


def make_mock_update(user_id: int = CUSTOMER_ID, first_name: str = "Alice", username: str = "alice", args: list = None):
    """Create mock Update and Context for Telegram command tests."""
    user = User(id=user_id, first_name=first_name, is_bot=False, username=username)
    chat = Chat(id=user_id, type="private")

    message = AsyncMock(spec=Message)
    message.reply_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message
    update.callback_query = None

    context = MagicMock()
    context.args = args or []
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    return update, context


def make_mock_callback_update(user_id: int = OWNER_ID, data: str = "approve_req:1"):
    """Create mock Update and Context for Telegram callback query tests."""
    user = User(id=user_id, first_name="Admin", is_bot=False)
    query = AsyncMock(spec=CallbackQuery)
    query.from_user = user
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = user
    update.effective_message = None

    context = MagicMock()
    context.bot = AsyncMock()
    return update, context


@pytest.fixture
def catalog_with_book(db_session: Session, valid_env_vars: dict) -> tuple[Customer, Book, BookCopy]:
    """Helper fixture providing an approved customer and a book with 1 copy."""
    cust, _ = register_customer(db_session, telegram_id=CUSTOMER_ID, first_name="Alice")
    approve_customer(db_session, cust.id, actor_telegram_id=OWNER_ID)

    book = create_book(
        session=db_session,
        isbn="9780132350884",
        title="Clean Code",
        author="Robert C. Martin",
        rental_price=Decimal("12.50"),
        actor_telegram_id=OWNER_ID,
    )
    book, copies = receive_stock_for_isbn(db_session, isbn=book.isbn, quantity=1, actor_telegram_id=OWNER_ID)
    db_session.commit()

    return cust, book, copies[0]


# ==============================================================================
# /rent command tests
# ==============================================================================


@pytest.mark.asyncio
async def test_rent_command_no_args(db_session: Session, valid_env_vars: dict) -> None:
    """Invoking /rent with no arguments displays usage guidance."""
    update, context = make_mock_update(args=[])
    await rent_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "How to Request a Book Rental" in reply_args[0]
    assert "/rent" in reply_args[0]
    assert "book_id" in reply_args[0]



@pytest.mark.asyncio
async def test_rent_command_unregistered_customer(db_session: Session, valid_env_vars: dict) -> None:
    """Unregistered user is instructed to run /start before requesting rentals."""
    update, context = make_mock_update(user_id=8888, args=["1"])
    await rent_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "register first" in reply_args[0]


@pytest.mark.asyncio
async def test_rent_command_pending_customer(db_session: Session, valid_env_vars: dict, catalog_with_book) -> None:
    """Pending (unapproved) customer is blocked from requesting rentals."""
    _, book, _ = catalog_with_book
    register_customer(db_session, telegram_id=8889, first_name="PendingUser")
    db_session.commit()

    update, context = make_mock_update(user_id=8889, args=[str(book.id)])
    await rent_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "PENDING" in reply_args[0]
    assert "APPROVED" in reply_args[0]


@pytest.mark.asyncio
async def test_rent_command_success_monetary(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Approved customer requests available book with standard monetary collateral."""
    _, book, _ = catalog_with_book
    update, context = make_mock_update(user_id=CUSTOMER_ID, args=[str(book.id)])

    await rent_command(update, context)

    # Verify customer received confirmation
    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Rental Request Submitted!" in reply_args[0]
    assert "Clean Code" in reply_args[0]
    assert "SUBMITTED" in reply_args[0]

    # Verify owner notification was attempted
    assert context.bot.send_message.called


@pytest.mark.asyncio
async def test_rent_command_success_with_guarantee(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Approved customer requests available book with a guarantee note."""
    _, book, _ = catalog_with_book
    update, context = make_mock_update(user_id=CUSTOMER_ID, args=[str(book.id), "Passport", "#998811"])

    await rent_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Rental Request Submitted!" in reply_args[0]
    assert "Passport #998811" in reply_args[0]


# ==============================================================================
# Owner commands: /requests, /approvereq, /rejectreq
# ==============================================================================


@pytest.mark.asyncio
async def test_requests_command_owner_access(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Owner can list rental requests."""
    cust, book, _ = catalog_with_book
    submit_rental_request(db_session, cust.id, book.id)
    db_session.commit()

    update, context = make_mock_update(user_id=OWNER_ID, args=[])
    await requests_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Rental Requests" in reply_args[0]
    assert "Clean Code" in reply_args[0]


@pytest.mark.asyncio
async def test_requests_command_unauthorized(
    db_session: Session, valid_env_vars: dict
) -> None:
    """Non-owner is denied access to /requests."""
    update, context = make_mock_update(user_id=OTHER_USER_ID, args=[])
    await requests_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Unauthorized" in reply_args[0]


@pytest.mark.asyncio
async def test_approvereq_command_owner_success(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Owner can approve request and allocate physical copy via /approvereq."""
    cust, book, copy = catalog_with_book
    req = submit_rental_request(db_session, cust.id, book.id)
    db_session.commit()

    update, context = make_mock_update(user_id=OWNER_ID, args=[str(req.id)])
    await approvereq_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "APPROVED" in reply_args[0]
    assert copy.barcode in reply_args[0]


@pytest.mark.asyncio
async def test_rejectreq_command_owner_success(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Owner can reject request and release copy via /rejectreq."""
    cust, book, _ = catalog_with_book
    req = submit_rental_request(db_session, cust.id, book.id)
    db_session.commit()

    update, context = make_mock_update(user_id=OWNER_ID, args=[str(req.id), "Customer cancelled"])
    await rejectreq_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "REJECTED" in reply_args[0]
    assert "Customer cancelled" in reply_args[0]


# ==============================================================================
# /recordpayment & /recordguarantee commands
# ==============================================================================


@pytest.mark.asyncio
async def test_recordpayment_command_fee_and_collateral(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Owner records verified cash fee and bank collateral."""
    cust, book, _ = catalog_with_book
    req = submit_rental_request(db_session, cust.id, book.id)
    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    # 1. Record fee
    update, context = make_mock_update(user_id=OWNER_ID, args=[str(req.id), "fee", "cash", "12.50", "Desk cash"])
    await recordpayment_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Payment Verified & Recorded!" in reply_args[0]
    assert "$12.50" in reply_args[0]

    # 2. Record collateral deposit
    update, context = make_mock_update(user_id=OWNER_ID, args=[str(req.id), "collateral", "bank", "50.00", "Ref991"])
    await recordpayment_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Payment Verified & Recorded!" in reply_args[0]
    assert "Ready for physical checkout" in reply_args[0]


@pytest.mark.asyncio
async def test_recordguarantee_command_success(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Owner records non-cash guarantee verification."""
    cust, book, _ = catalog_with_book
    req = submit_rental_request(db_session, cust.id, book.id)
    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    update, context = make_mock_update(user_id=OWNER_ID, args=[str(req.id), "National ID #88129 stored in vault"])
    await recordguarantee_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Non-Cash Guarantee Recorded!" in reply_args[0]
    assert "No monetary collateral ledger entry created" in reply_args[0]


# ==============================================================================
# /checkout command tests
# ==============================================================================


@pytest.mark.asyncio
async def test_checkout_command_blocked_when_conditions_unmet(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Checkout is blocked if payments/collateral are missing."""
    cust, book, _ = catalog_with_book
    req = submit_rental_request(db_session, cust.id, book.id)
    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    update, context = make_mock_update(user_id=OWNER_ID, args=[str(req.id)])
    await checkout_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Cannot Handover Yet" in reply_args[0]


@pytest.mark.asyncio
async def test_checkout_command_success(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Checkout succeeds when approved and fee + collateral are verified."""
    cust, book, copy = catalog_with_book
    req = submit_rental_request(db_session, cust.id, book.id)
    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    record_payment_verification(db_session, req.id, "RENTAL_FEE", "CASH", Decimal("12.50"), OWNER_ID)
    from app.services.rental_request import record_non_cash_guarantee
    record_non_cash_guarantee(db_session, req.id, actor_telegram_id=OWNER_ID, guarantee_details="Passport")
    db_session.commit()

    update, context = make_mock_update(user_id=OWNER_ID, args=[str(req.id)])
    await checkout_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Physical Handover Confirmed! Rental Activated!" in reply_args[0]
    assert copy.barcode in reply_args[0]
    assert "Return Deadline:" in reply_args[0]


# ==============================================================================
# Inline callback query handler tests
# ==============================================================================


@pytest.mark.asyncio
async def test_rental_request_callback_unauthorized(
    db_session: Session, valid_env_vars: dict
) -> None:
    """Non-owner clicking inline button is denied."""
    update, context = make_mock_callback_update(user_id=OTHER_USER_ID, data="approve_req:1")
    await rental_request_callback(update, context)

    assert update.callback_query.answer.called
    answer_args, _ = update.callback_query.answer.call_args
    assert "Unauthorized" in answer_args[0]


@pytest.mark.asyncio
async def test_rental_request_callback_approve_success_and_idempotency(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Owner clicks Approve button; repeated click is handled gracefully."""
    cust, book, _ = catalog_with_book
    req = submit_rental_request(db_session, cust.id, book.id)
    db_session.commit()

    # 1. First click: succeeds
    update, context = make_mock_callback_update(user_id=OWNER_ID, data=f"approve_req:{req.id}")
    await rental_request_callback(update, context)

    assert update.callback_query.edit_message_text.called
    edit_args, _ = update.callback_query.edit_message_text.call_args
    assert "Approved" in edit_args[0]

    # 2. Duplicate click: handled without crashing
    update2, context2 = make_mock_callback_update(user_id=OWNER_ID, data=f"approve_req:{req.id}")
    await rental_request_callback(update2, context2)

    assert update2.callback_query.answer.called
    answer_args, _ = update2.callback_query.answer.call_args
    assert "already processed" in answer_args[0]


@pytest.mark.asyncio
async def test_rental_request_callback_reject_success(
    db_session: Session, valid_env_vars: dict, catalog_with_book
) -> None:
    """Owner clicks Reject button; releases copy and updates message."""
    cust, book, _ = catalog_with_book
    req = submit_rental_request(db_session, cust.id, book.id)
    db_session.commit()

    update, context = make_mock_callback_update(user_id=OWNER_ID, data=f"reject_req:{req.id}")
    await rental_request_callback(update, context)

    assert update.callback_query.edit_message_text.called
    edit_args, _ = update.callback_query.edit_message_text.call_args
    assert "Rejected" in edit_args[0]
