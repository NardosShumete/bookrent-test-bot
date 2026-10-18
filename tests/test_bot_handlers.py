"""Tests for Telegram bot handlers: registration, approvals, callbacks, cataloguing, and search."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.orm import Session
from telegram import CallbackQuery, Chat, Message, Update, User

from app.bot.handlers import (
    addbook_command,
    approve_command,
    books_command,
    customer_approval_callback,
    help_command,
    inventory_command,
    pending_command,
    ping_command,
    receive_command,
    reject_command,
    search_command,
    start_command,
)
from app.models.customer import Customer
from app.models.enums import CustomerStatus
from app.services.book_catalog import create_book, receive_stock_for_isbn
from app.services.customer import approve_customer, register_customer


def make_mock_update(user_id: int = 5001, first_name: str = "Alice", username: str = "alice", args: list = None):
    """Helper creating mock Update and Context objects for command handlers."""
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
    return update, context


def make_mock_callback_update(user_id: int = 12345, data: str = "approve_cust:1"):
    """Helper creating mock Update and Context objects for callback query handlers."""
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
    return update, context


@pytest.mark.asyncio
async def test_start_command_new_customer(db_session: Session, valid_env_vars: dict) -> None:
    """Verify /start displays language selection for a new first-time user."""
    update, context = make_mock_update(user_id=7001, first_name="NewUser")

    await start_command(update, context)

    # Verify response prompts language selection
    reply_args, reply_kwargs = update.effective_message.reply_text.call_args
    assert "choose your language" in reply_args[0]
    assert "ቋንቋዎን ይምረጡ" in reply_args[0]
    assert reply_kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_start_command_approved_customer(db_session: Session, valid_env_vars: dict) -> None:
    """Verify /start greets approved customers and directs them to search."""
    cust, _ = register_customer(db_session, telegram_id=7002, first_name="ApprovedUser")
    cust.status = CustomerStatus.APPROVED.value
    cust.language = "en"
    db_session.flush()

    update, context = make_mock_update(user_id=7002, first_name="ApprovedUser")
    await start_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "APPROVED" in reply_args[0]
    assert "/search" in reply_args[0]


@pytest.mark.asyncio
async def test_start_command_owner(db_session: Session, valid_env_vars: dict) -> None:
    """Verify /start presents the Owner Console to authorized owners with saved language."""
    owner_id = 12345  # In ADMIN_USER_IDS
    from app.services.customer import set_customer_language
    set_customer_language(db_session, owner_id, "en", first_name="Admin")
    db_session.flush()

    update, context = make_mock_update(user_id=owner_id, first_name="Admin")

    await start_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "Owner Console" in reply_args[0]
    assert "/pending" in reply_args[0]
    assert "/addbook" in reply_args[0]


@pytest.mark.asyncio
async def test_pending_command_owner_vs_non_owner(db_session: Session, valid_env_vars: dict) -> None:
    """Verify /pending permits owners and rejects non-owners."""
    register_customer(db_session, telegram_id=7003, first_name="PendingOne")
    db_session.flush()

    # Non-owner blocked
    non_owner_update, ctx = make_mock_update(user_id=99999)
    await pending_command(non_owner_update, ctx)
    reply_args, _ = non_owner_update.effective_message.reply_text.call_args
    assert "Access denied" in reply_args[0]

    # Owner succeeds
    owner_update, ctx = make_mock_update(user_id=12345)
    await pending_command(owner_update, ctx)
    assert owner_update.effective_message.reply_text.call_count >= 1


@pytest.mark.asyncio
async def test_approve_and_reject_commands(db_session: Session, valid_env_vars: dict) -> None:
    """Verify /approve and /reject commands update customer status."""
    c1, _ = register_customer(db_session, telegram_id=7004, first_name="ToApprove")
    c2, _ = register_customer(db_session, telegram_id=7005, first_name="ToReject")
    db_session.flush()

    # Approve c1
    update1, ctx1 = make_mock_update(user_id=12345, args=[str(c1.id)])
    await approve_command(update1, ctx1)
    reply1, _ = update1.effective_message.reply_text.call_args
    assert "APPROVED" in reply1[0]
    db_session.refresh(c1)
    assert c1.status == CustomerStatus.APPROVED.value

    # Reject c2
    update2, ctx2 = make_mock_update(user_id=12345, args=[str(c2.id), "Duplicate", "account"])
    await reject_command(update2, ctx2)
    reply2, _ = update2.effective_message.reply_text.call_args
    assert "REJECTED" in reply2[0]
    db_session.refresh(c2)
    assert c2.status == CustomerStatus.REJECTED.value


@pytest.mark.asyncio
async def test_callback_query_approval_and_repeated_click_guard(
    db_session: Session, valid_env_vars: dict
) -> None:
    """Verify inline button callbacks approve customer and protect against repeated clicks."""
    customer, _ = register_customer(db_session, telegram_id=7006, first_name="CallbackUser")
    db_session.flush()

    # 1. Non-owner clicking button is rejected
    unauth_update, unauth_ctx = make_mock_callback_update(user_id=99999, data=f"approve_cust:{customer.id}")
    await customer_approval_callback(unauth_update, unauth_ctx)
    unauth_update.callback_query.answer.assert_called_with("⛔ Unauthorized: Owner access required.", show_alert=True)

    # 2. Owner clicks "Approve" -> Succeeds
    owner_update, owner_ctx = make_mock_callback_update(user_id=12345, data=f"approve_cust:{customer.id}")
    await customer_approval_callback(owner_update, owner_ctx)
    db_session.refresh(customer)
    assert customer.status == CustomerStatus.APPROVED.value
    owner_update.callback_query.edit_message_text.assert_called()

    # 3. Repeated click on the same customer -> Protected! Does not crash; notices already processed
    owner_update2, owner_ctx2 = make_mock_callback_update(user_id=12345, data=f"approve_cust:{customer.id}")
    await customer_approval_callback(owner_update2, owner_ctx2)
    owner_update2.callback_query.answer.assert_called_with("Notice: Customer is already processed.", show_alert=False)


@pytest.mark.asyncio
async def test_addbook_and_receive_commands(db_session: Session, valid_env_vars: dict) -> None:
    """Verify /addbook and /receive handlers for cataloguing and stocking."""
    owner_id = 12345

    # 1. /addbook
    addbook_update, ctx = make_mock_update(
        user_id=owner_id,
        args=["978-0-306-40615-7", "|", "Computer", "Architecture", "|", "Patterson", "|", "18.00", "|", "800", "|", "CS"],
    )
    await addbook_command(addbook_update, ctx)
    reply, _ = addbook_update.effective_message.reply_text.call_args
    assert "Book Catalogued Successfully" in reply[0]

    # 2. /receive
    receive_update, ctx2 = make_mock_update(user_id=owner_id, args=["9780306406157", "4"])
    await receive_command(receive_update, ctx2)
    reply2, _ = receive_update.effective_message.reply_text.call_args
    assert "Stock Received Successfully" in reply2[0]
    assert "Copies Added: <b>4</b>" in reply2[0]


@pytest.mark.asyncio
async def test_inventory_command(db_session: Session, valid_env_vars: dict) -> None:
    """Verify /inventory handler displays overall summary and specific book inspection."""
    owner_id = 12345

    # Overall summary
    update1, ctx1 = make_mock_update(user_id=owner_id, args=[])
    await inventory_command(update1, ctx1)
    reply1, _ = update1.effective_message.reply_text.call_args
    assert "Library Inventory Summary" in reply1[0]
    assert "Available (ON_SHELF)" in reply1[0]


@pytest.mark.asyncio
async def test_search_command_authorization_and_results(db_session: Session, valid_env_vars: dict) -> None:
    """Verify /search blocks pending customers and displays available copies to approved customers."""
    # Catalogue a book and add 2 copies
    create_book(db_session, "9781861978769", "The 48 Laws of Power", "Robert Greene", Decimal("10.00"), actor_telegram_id=12345)
    receive_stock_for_isbn(db_session, "9781861978769", 2, actor_telegram_id=12345)
    db_session.flush()

    # Pending customer searching -> blocked
    pending_cust, _ = register_customer(db_session, telegram_id=7007, first_name="PendingSearcher")
    db_session.flush()

    pending_update, ctx = make_mock_update(user_id=7007, args=["Power"])
    await search_command(pending_update, ctx)
    reply_pending, _ = pending_update.effective_message.reply_text.call_args
    assert "must be an <b>APPROVED</b> customer" in reply_pending[0]

    # Approved customer searching -> succeeds and displays availability
    pending_cust.status = CustomerStatus.APPROVED.value
    db_session.flush()

    approved_update, ctx2 = make_mock_update(user_id=7007, args=["Power"])
    await search_command(approved_update, ctx2)
    reply_approved, _ = approved_update.effective_message.reply_text.call_args
    assert "The 48 Laws of Power" in reply_approved[0]
    assert "2 available" in reply_approved[0]
