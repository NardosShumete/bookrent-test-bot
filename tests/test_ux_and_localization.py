"""Automated tests for Phase 7 UX improvements: Amharic/English localization,
navigation buttons, rejected customer tracking, and admin clarity."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.orm import Session
from telegram import CallbackQuery, Chat, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, Update, User

from app.bot.handlers import (
    handle_menu_button,
    help_command,
    language_command,
    language_selection_callback,
    pending_command,
    reapprove_customer_callback,
    rejected_customers_command,
    rejected_page_callback,
    start_command,
)
from app.localization import get_admin_reply_keyboard, get_customer_reply_keyboard, t
from app.models.customer import Customer
from app.models.enums import CustomerStatus
from app.services.customer import (
    get_customer_language,
    get_rejected_customers,
    reapprove_customer,
    register_customer,
    reject_customer,
    set_customer_language,
)


OWNER_ID = 12345
NON_OWNER_ID = 88888


def make_mock_update(user_id: int = 5001, first_name: str = "Alice", username: str = "alice", args: list = None, text: str = None):
    """Helper creating mock Update and Context objects for command and message handlers."""
    user = User(id=user_id, first_name=first_name, is_bot=False, username=username)
    chat = Chat(id=user_id, type="private")

    message = AsyncMock(spec=Message)
    message.reply_text = AsyncMock()
    message.text = text

    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message
    update.callback_query = None

    context = MagicMock()
    context.args = args or []
    return update, context


def make_mock_callback_update(user_id: int = 12345, data: str = "lang:en", first_name: str = "Admin"):
    """Helper creating mock Update and Context objects for callback query handlers."""
    user = User(id=user_id, first_name=first_name, is_bot=False)
    query = AsyncMock(spec=CallbackQuery)
    query.from_user = user
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    message = AsyncMock(spec=Message)
    message.reply_text = AsyncMock()
    query.message = message

    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_user = user
    update.effective_message = message

    context = MagicMock()
    return update, context


# ==============================================================================
# 1-3: Language Selection After /start & Callbacks
# ==============================================================================


@pytest.mark.asyncio
async def test_first_time_user_sees_language_selection_before_services(db_session: Session, valid_env_vars: dict) -> None:
    """A new user sending /start must see language selection screen with English and Amharic."""
    update, context = make_mock_update(user_id=9001, first_name="Blen")
    await start_command(update, context)

    reply_args, reply_kwargs = update.effective_message.reply_text.call_args
    text = reply_args[0]
    keyboard: InlineKeyboardMarkup = reply_kwargs["reply_markup"]

    # Verify message has English & Amharic instructions
    assert "Welcome to BookRent! Please choose your language to continue" in text
    assert "ወደ BookRent እንኳን በደህና መጡ! ለመቀጠል ቋንቋዎን ይምረጡ" in text

    # Verify buttons are present
    button_callbacks = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert "lang:en" in button_callbacks
    assert "lang:am" in button_callbacks


@pytest.mark.asyncio
async def test_english_selection_saves_preference_and_displays_english(db_session: Session, valid_env_vars: dict) -> None:
    """Selecting English saves language as 'en' and presents English welcome."""
    update, context = make_mock_callback_update(user_id=9002, data="lang:en", first_name="Dawit")
    await language_selection_callback(update, context)

    # Database verification
    cust = db_session.query(Customer).filter_by(telegram_id=9002).first()
    assert cust is not None
    assert cust.language == "en"

    # Message verification
    update.callback_query.edit_message_text.assert_awaited()
    edit_text = update.callback_query.edit_message_text.call_args[0][0]
    assert "Language set to <b>English</b>" in edit_text


@pytest.mark.asyncio
async def test_amharic_selection_saves_preference_and_displays_amharic(db_session: Session, valid_env_vars: dict) -> None:
    """Selecting Amharic saves language as 'am' and presents Amharic welcome."""
    update, context = make_mock_callback_update(user_id=9003, data="lang:am", first_name="Abebe")
    await language_selection_callback(update, context)

    # Database verification
    cust = db_session.query(Customer).filter_by(telegram_id=9003).first()
    assert cust is not None
    assert cust.language == "am"

    # Message verification
    update.callback_query.edit_message_text.assert_awaited()
    edit_text = update.callback_query.edit_message_text.call_args[0][0]
    assert "ቋንቋዎ ወደ <b>አማርኛ</b> ተቀናብሯል" in edit_text


# ==============================================================================
# 4-5: Returning Users & Changing Language
# ==============================================================================


@pytest.mark.asyncio
async def test_returning_user_retains_saved_language(db_session: Session, valid_env_vars: dict) -> None:
    """Returning users retain their saved language without repeating language selection."""
    cust, _ = register_customer(db_session, telegram_id=9004, first_name="Chala")
    cust.language = "am"
    cust.status = CustomerStatus.APPROVED.value
    db_session.flush()

    update, context = make_mock_update(user_id=9004, first_name="Chala")
    await start_command(update, context)

    reply_args, reply_kwargs = update.effective_message.reply_text.call_args
    text = reply_args[0]
    assert "እንኳን ደህና መጡ <b>Chala</b>" in text
    assert "መለያዎ <b>የጸደቀ</b>" in text
    assert "Choose your language" not in text


@pytest.mark.asyncio
async def test_language_command_lets_user_switch_language(db_session: Session, valid_env_vars: dict) -> None:
    """Sending /language displays the language selection keyboard to change preference."""
    set_customer_language(db_session, telegram_id=9005, language="en", first_name="Eden")
    db_session.flush()

    update, context = make_mock_update(user_id=9005, first_name="Eden")
    await language_command(update, context)

    reply_args, reply_kwargs = update.effective_message.reply_text.call_args
    assert "Please choose your preferred language" in reply_args[0]
    keyboard: InlineKeyboardMarkup = reply_kwargs["reply_markup"]
    assert any(btn.callback_data == "lang:am" for row in keyboard.inline_keyboard for btn in row)


# ==============================================================================
# 6-7: Account Status Guidance (Pending vs Rejected)
# ==============================================================================


@pytest.mark.asyncio
async def test_pending_customer_receives_clear_explanation(db_session: Session, valid_env_vars: dict) -> None:
    """Pending customer sees clear pending explanation instead of unavailable rental services."""
    cust, _ = register_customer(db_session, telegram_id=9006, first_name="Fikru")
    cust.language = "en"
    cust.status = CustomerStatus.PENDING.value
    db_session.flush()

    update, context = make_mock_update(user_id=9006, first_name="Fikru")
    await start_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    text = reply_args[0]
    assert "PENDING" in text
    assert "You will receive access to borrow books once an administrator approves" in text


@pytest.mark.asyncio
async def test_rejected_customer_receives_status_and_stored_reason(db_session: Session, valid_env_vars: dict) -> None:
    """Rejected customer sees rejection status and stored reason clearly."""
    cust, _ = register_customer(db_session, telegram_id=9007, first_name="Genet")
    cust.language = "en"
    reject_customer(db_session, cust.id, actor_telegram_id=OWNER_ID, reason="Invalid phone number provided")
    db_session.flush()

    update, context = make_mock_update(user_id=9007, first_name="Genet")
    await start_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    text = reply_args[0]
    assert "REJECTED" in text
    assert "Invalid phone number provided" in text
    assert "please contact the library owner for assistance" in text


@pytest.mark.asyncio
async def test_rejected_customer_without_reason_does_not_invent_one(db_session: Session, valid_env_vars: dict) -> None:
    """Rejected customer without a reason sees rejection status without fabricated reasons."""
    cust, _ = register_customer(db_session, telegram_id=9008, first_name="Habtamu")
    cust.language = "am"
    reject_customer(db_session, cust.id, actor_telegram_id=OWNER_ID, reason=None)
    db_session.flush()

    update, context = make_mock_update(user_id=9008, first_name="Habtamu")
    await start_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    text = reply_args[0]
    assert "ተቀባይነት አላገኘም" in text
    assert "ምክንያት፦" not in text


# ==============================================================================
# 8-11: Admin Menus, Pending, Rejected List & Reapproval
# ==============================================================================


@pytest.mark.asyncio
async def test_admin_opens_pending_customers_list(db_session: Session, valid_env_vars: dict) -> None:
    """Administrator can open pending customer list with Approve and Reject buttons."""
    set_customer_language(db_session, OWNER_ID, "en", first_name="Admin")
    cust, _ = register_customer(db_session, telegram_id=9009, first_name="PendingPerson")
    db_session.flush()

    update, context = make_mock_update(user_id=OWNER_ID, first_name="Admin")
    await pending_command(update, context)

    # Should send pending header + card with buttons
    assert update.effective_message.reply_text.call_count >= 2


@pytest.mark.asyncio
async def test_admin_opens_rejected_customers_list(db_session: Session, valid_env_vars: dict) -> None:
    """Administrator can view rejected customers with stored reason and reapprove buttons."""
    set_customer_language(db_session, OWNER_ID, "en", first_name="Admin")
    cust, _ = register_customer(db_session, telegram_id=9010, first_name="RejectedPerson", username="rej_user")
    reject_customer(db_session, cust.id, actor_telegram_id=OWNER_ID, reason="Suspicious profile")
    db_session.flush()

    update, context = make_mock_update(user_id=OWNER_ID, first_name="Admin")
    await rejected_customers_command(update, context)

    reply_args, reply_kwargs = update.effective_message.reply_text.call_args
    text = reply_args[0]
    assert "Rejected Customers" in text
    assert "RejectedPerson" in text
    assert "@rej_user" in text
    assert "Suspicious profile" in text

    keyboard: InlineKeyboardMarkup = reply_kwargs["reply_markup"]
    callbacks = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert f"reapprove_cust:{cust.id}" in callbacks


@pytest.mark.asyncio
async def test_rejected_customers_empty_state(db_session: Session, valid_env_vars: dict) -> None:
    """Empty rejected customers list displays helpful empty state message."""
    set_customer_language(db_session, OWNER_ID, "en", first_name="Admin")
    update, context = make_mock_update(user_id=OWNER_ID, first_name="Admin")
    await rejected_customers_command(update, context)

    reply_args, _ = update.effective_message.reply_text.call_args
    assert "no rejected customer accounts" in reply_args[0]


@pytest.mark.asyncio
async def test_rejected_customers_pagination(db_session: Session, valid_env_vars: dict) -> None:
    """Lists with more than PAGE_SIZE items paginate correctly with Previous/Next buttons."""
    set_customer_language(db_session, OWNER_ID, "en", first_name="Admin")
    # Create 7 rejected customers (PAGE_SIZE = 5)
    for i in range(1, 8):
        c, _ = register_customer(db_session, telegram_id=9100 + i, first_name=f"Rej{i}")
        reject_customer(db_session, c.id, actor_telegram_id=OWNER_ID, reason=f"Reason {i}")
    db_session.flush()

    update, context = make_mock_update(user_id=OWNER_ID, first_name="Admin")
    await rejected_customers_command(update, context)

    # Page 1
    reply_args, reply_kwargs = update.effective_message.reply_text.call_args
    text = reply_args[0]
    assert "Page 1/2" in text
    assert "Rej7" in text

    keyboard: InlineKeyboardMarkup = reply_kwargs["reply_markup"]
    callbacks = [btn.callback_data for row in keyboard.inline_keyboard for btn in row]
    assert "admin_rejected_page:2" in callbacks


@pytest.mark.asyncio
async def test_admin_reapprove_customer_callback(db_session: Session, valid_env_vars: dict) -> None:
    """Administrator can reapprove a previously rejected customer."""
    cust, _ = register_customer(db_session, telegram_id=9020, first_name="ToReapprove")
    reject_customer(db_session, cust.id, actor_telegram_id=OWNER_ID, reason="Mistake")
    db_session.flush()

    update, context = make_mock_callback_update(
        user_id=OWNER_ID, data=f"reapprove_cust:{cust.id}", first_name="Admin"
    )
    await reapprove_customer_callback(update, context)

    # Verify customer is now APPROVED
    db_session.expire_all()
    updated_cust = db_session.query(Customer).filter_by(id=cust.id).first()
    assert updated_cust.status == CustomerStatus.APPROVED.value
    assert updated_cust.rejection_reason is None
    assert updated_cust.rejected_at is None


# ==============================================================================
# 12: Security: Non-Admin Access Control
# ==============================================================================


@pytest.mark.asyncio
async def test_non_admin_cannot_execute_admin_callbacks(db_session: Session, valid_env_vars: dict) -> None:
    """Non-administrators cannot trigger admin approval or rejection callbacks."""
    cust, _ = register_customer(db_session, telegram_id=9030, first_name="Victim")
    db_session.flush()

    # Non-admin tries to reapprove
    update, context = make_mock_callback_update(
        user_id=NON_OWNER_ID, data=f"reapprove_cust:{cust.id}", first_name="Attacker"
    )
    await reapprove_customer_callback(update, context)
    update.callback_query.answer.assert_awaited_with("⛔ Unauthorized: Owner access required.", show_alert=True)

    # Non-admin tries rejected pagination
    update2, context2 = make_mock_callback_update(
        user_id=NON_OWNER_ID, data="admin_rejected_page:2", first_name="Attacker"
    )
    await rejected_page_callback(update2, context2)
    update2.callback_query.answer.assert_awaited_with("⛔ Unauthorized: Owner access required.", show_alert=True)


# ==============================================================================
# 13: Customer & Admin Button Navigation & Descriptions
# ==============================================================================


@pytest.mark.asyncio
async def test_customer_navigation_buttons_give_clear_descriptions(db_session: Session, valid_env_vars: dict) -> None:
    """Pressing customer navigation buttons displays rich purpose explanations."""
    cust, _ = register_customer(db_session, telegram_id=9040, first_name="ReaderA")
    cust.status = CustomerStatus.APPROVED.value
    cust.language = "en"
    db_session.flush()

    # Search button
    update, context = make_mock_update(user_id=9040, text="🔎 Search Books")
    await handle_menu_button(update, context)
    text = update.effective_message.reply_text.call_args[0][0]
    assert "Search by book title, author, ISBN, or category" in text

    # Request rental button
    update, context = make_mock_update(user_id=9040, text="📖 Request a Rental")
    await handle_menu_button(update, context)
    text = update.effective_message.reply_text.call_args[0][0]
    assert "Select an available book to submit a rental request" in text

    # Extensions button
    update, context = make_mock_update(user_id=9040, text="⏳ My Extensions")
    await handle_menu_button(update, context)
    all_replies = [c[0][0] for c in update.effective_message.reply_text.call_args_list]
    assert any("5 calendar days" in r for r in all_replies)
    assert any("10 ETB" in r for r in all_replies)


@pytest.mark.asyncio
async def test_customer_amharic_navigation_buttons(db_session: Session, valid_env_vars: dict) -> None:
    """Pressing Amharic customer buttons displays Amharic explanations."""
    cust, _ = register_customer(db_session, telegram_id=9041, first_name="ReaderB")
    cust.status = CustomerStatus.APPROVED.value
    cust.language = "am"
    db_session.flush()

    # Amharic Search button
    update, context = make_mock_update(user_id=9041, text="🔎 መጻሕፍት ፈልግ")
    await handle_menu_button(update, context)
    text = update.effective_message.reply_text.call_args[0][0]
    assert "በመጽሐፍ ርዕስ፣ በደራሲ፣ በISBN ወይም በምድብ መፈለግ ይችላሉ" in text


@pytest.mark.asyncio
async def test_unapproved_customer_button_access_explanation(db_session: Session, valid_env_vars: dict) -> None:
    """An unapproved customer pressing restricted buttons is explained why."""
    cust, _ = register_customer(db_session, telegram_id=9042, first_name="PendingReader")
    cust.status = CustomerStatus.PENDING.value
    cust.language = "en"
    db_session.flush()

    update, context = make_mock_update(user_id=9042, text="📖 Request a Rental")
    await handle_menu_button(update, context)
    text = update.effective_message.reply_text.call_args[0][0]
    assert "Your account is currently <b>PENDING</b>" in text


@pytest.mark.asyncio
async def test_admin_navigation_buttons_open_sections(db_session: Session, valid_env_vars: dict) -> None:
    """Owner pressing admin buttons opens appropriate sections without remembering commands."""
    set_customer_language(db_session, OWNER_ID, "en", first_name="Admin")
    db_session.flush()

    # Rejected Customers button
    update, context = make_mock_update(user_id=OWNER_ID, text="🚫 Rejected Customers")
    await handle_menu_button(update, context)
    assert update.effective_message.reply_text.called

    # Manage Books & Stock button
    update, context = make_mock_update(user_id=OWNER_ID, text="📚 Manage Books & Stock")
    await handle_menu_button(update, context)
    text = update.effective_message.reply_text.call_args[0][0]
    assert "/addbook" in text
    assert "/receive" in text


@pytest.mark.asyncio
async def test_unexpected_text_provides_guidance(db_session: Session, valid_env_vars: dict) -> None:
    """Unexpected text input receives helpful navigation guidance."""
    set_customer_language(db_session, telegram_id=9050, language="en", first_name="LostUser")
    db_session.flush()

    update, context = make_mock_update(user_id=9050, text="random jibberish 12345")
    await handle_menu_button(update, context)
    text = update.effective_message.reply_text.call_args[0][0]
    assert "I didn't recognize that message" in text
    assert "/help" in text
