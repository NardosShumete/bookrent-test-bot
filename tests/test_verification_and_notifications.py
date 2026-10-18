"""Automated tests for Phase 8: Customer Verification & Event Notifications.

Verifies:
1. Multi-step registration conversation flow (Consent -> Photo -> Phone -> Location -> Summary -> Submit).
2. Navigation controls: Back, Cancel, and Restart handling.
3. Phone normalization for Ethiopian (+251/09/07) and international numbers.
4. Contact sharing vs manual phone input with verified flag.
5. Location sharing (GPS) vs text residential address.
6. Duplicate prevention on repeated registration attempts.
7. Preserving existing approved customers without forcing re-registration.
8. Owner-only National ID photo viewing security (view_id_photo callback).
9. Centralized localized notification dispatch and failure resilience.
10. Sensitive data masking in audit logs and logging filters.
"""

from datetime import datetime, timezone
from decimal import Decimal
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.orm import Session
from telegram import (
    CallbackQuery,
    Chat,
    Contact,
    InlineKeyboardMarkup,
    Location,
    Message,
    PhotoSize,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    User,
)
from telegram.ext import ConversationHandler

from app.bot.handlers import (
    REG_CONFIRM,
    REG_CONSENT,
    REG_LOCATION,
    REG_PHONE,
    REG_PHOTO,
    pending_command,
    prompt_registration_consent,
    reg_cancel_command,
    reg_cancel_handler,
    reg_confirm_handler,
    reg_consent_handler,
    reg_location_handler,
    reg_location_text_handler,
    reg_phone_contact_handler,
    reg_phone_text_handler,
    reg_photo_handler,
    reg_photo_text_handler,
    register_command,
    start_command,
    view_id_photo_callback,
)
from app.config import get_settings
from app.localization import t
from app.logging_config import SensitiveDataFilter, mask_phone
from app.models.audit import AuditLog
from app.models.customer import Customer
from app.models.enums import CustomerStatus
from app.services.customer import (
    get_customer_by_telegram_id,
    normalize_phone_number,
    register_customer,
    submit_customer_registration,
)
from app.services.notification import (
    announce_new_stock,
    notify_admins,
    notify_admins_sync,
    notify_customer,
    notify_customer_sync,
)


OWNER_ID = 12345
NON_OWNER_ID = 99999


def make_mock_update(
    user_id: int = 5001,
    first_name: str = "Abebe",
    username: str = "abebe",
    text: str = None,
    photo: list = None,
    contact: Contact = None,
    location: Location = None,
) -> tuple[Update, MagicMock]:
    """Create mock Update and Context objects for conversation steps."""
    user = User(id=user_id, first_name=first_name, is_bot=False, username=username)
    chat = Chat(id=user_id, type="private")

    message = AsyncMock(spec=Message)
    message.reply_text = AsyncMock()
    message.text = text
    message.photo = photo or []
    message.contact = contact
    message.location = location

    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message
    update.callback_query = None

    context = MagicMock()
    context.user_data = {}
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock(return_value=True)
    context.bot.send_photo = AsyncMock(return_value=True)

    return update, context


def make_mock_callback_update(
    user_id: int = 12345,
    data: str = "view_id_photo:1",
    first_name: str = "Admin",
) -> tuple[Update, MagicMock]:
    """Create mock Update and Context objects for callback query handlers."""
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
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock(return_value=True)
    context.bot.send_photo = AsyncMock(return_value=True)
    return update, context


# ==============================================================================
# 1. Phone Normalization Tests
# ==============================================================================


def test_normalize_ethiopian_local_format_09() -> None:
    """Ethiopian 09 local number normalizes to E.164 +2519..."""
    assert normalize_phone_number("0911234567") == "+251911234567"
    assert normalize_phone_number("09 11-23 45 67") == "+251911234567"
    assert normalize_phone_number("(0911) 234567") == "+251911234567"


def test_normalize_ethiopian_local_format_07() -> None:
    """Ethiopian 07 local number (Safaricom) normalizes to E.164 +2517..."""
    assert normalize_phone_number("0711234567") == "+251711234567"
    assert normalize_phone_number("07-12-34-56-78") == "+251712345678"


def test_normalize_ethiopian_international_prefix() -> None:
    """Ethiopian +251 / 251 / 00251 formats normalize properly."""
    assert normalize_phone_number("+251911234567") == "+251911234567"
    assert normalize_phone_number("251911234567") == "+251911234567"
    assert normalize_phone_number("00251911234567") == "+251911234567"


def test_normalize_international_e164() -> None:
    """Valid foreign international E.164 numbers normalize properly."""
    assert normalize_phone_number("+14155552671") == "+14155552671"
    assert normalize_phone_number("+44 20 7946 0958") == "+442079460958"


def test_normalize_invalid_phone_numbers() -> None:
    """Invalid phone numbers return None."""
    assert normalize_phone_number("1234") is None
    assert normalize_phone_number("abcdef") is None
    assert normalize_phone_number("+") is None
    assert normalize_phone_number("") is None
    assert normalize_phone_number("09112345") is None  # Too short for 09
    assert normalize_phone_number("091123456789") is None  # Too long for 09


# ==============================================================================
# 2. Customer Model & Verification Submission Tests
# ==============================================================================


def test_customer_model_verification_properties(db_session: Session) -> None:
    """Verify is_verification_complete property logic on Customer model."""
    customer, _ = register_customer(db_session, telegram_id=7010, first_name="Tadesse")
    db_session.flush()

    # Initial state: unverified
    assert not customer.is_verification_complete

    # Incomplete: consent only
    customer.consent_given = True
    assert not customer.is_verification_complete

    # Incomplete: photo added
    customer.national_id_file_id = "file_id_xyz_123"
    assert not customer.is_verification_complete

    # Incomplete: phone added
    customer.phone_number = "+251911223344"
    assert not customer.is_verification_complete

    # Complete with address
    customer.address = "Bole Subcity, Woreda 03, Addis Ababa"
    assert customer.is_verification_complete

    # Complete with GPS coordinates instead of address
    customer.address = None
    customer.latitude = 9.0105
    customer.longitude = 38.7612
    assert customer.is_verification_complete


def test_submit_customer_registration_updates_existing_without_duplicate(db_session: Session, valid_env_vars: dict) -> None:
    """Submitting verification updates existing customer record without creating duplicates."""
    # Existing record
    cust1, created = register_customer(db_session, telegram_id=7020, first_name="Almaz")
    db_session.commit()
    assert created

    # Submit registration
    updated_cust = submit_customer_registration(
        session=db_session,
        telegram_id=7020,
        first_name="Almaz",
        national_id_file_id="id_photo_almaz_001",
        phone_number="+251912345678",
        phone_source="TELEGRAM_CONTACT",
        address=None,
        latitude=9.02,
        longitude=38.75,
        language="en",
    )
    db_session.commit()

    assert updated_cust.id == cust1.id
    assert updated_cust.status == CustomerStatus.PENDING.value
    assert updated_cust.phone_verified is True
    assert updated_cust.phone_source == "TELEGRAM_CONTACT"
    assert updated_cust.national_id_file_id == "id_photo_almaz_001"
    assert updated_cust.latitude == 9.02
    assert updated_cust.longitude == 38.75
    assert updated_cust.consent_given is True
    assert updated_cust.registration_completed_at is not None

    # Verify no duplicate records exist in the database
    all_custs = db_session.query(Customer).filter_by(telegram_id=7020).all()
    assert len(all_custs) == 1

    # Verify audit log recorded
    reg_logs = (
        db_session.query(AuditLog)
        .filter_by(entity_type="CUSTOMER", entity_id=str(updated_cust.id), action="SUBMIT_VERIFICATION")
        .all()
    )
    assert len(reg_logs) == 1
    # Check phone number is masked in audit log
    assert "+251912345678" not in reg_logs[0].new_values.get("phone_masked", "")
    assert "****" in reg_logs[0].new_values.get("phone_masked", "")


# ==============================================================================
# 3. Preserving Approved Customers
# ==============================================================================


@pytest.mark.asyncio
async def test_approved_customer_not_forced_to_register(db_session: Session, valid_env_vars: dict) -> None:
    """Approved customer running /start or /register receives approval menu/notice, not registration."""
    cust, _ = register_customer(db_session, telegram_id=7030, first_name="ApprovedUser")
    cust.status = CustomerStatus.APPROVED.value
    cust.language = "en"
    db_session.commit()

    # Test /start
    update, context = make_mock_update(user_id=7030, first_name="ApprovedUser")
    result = await start_command(update, context)
    assert result == ConversationHandler.END
    reply_text = update.effective_message.reply_text.call_args[0][0]
    assert "Welcome back" in reply_text

    # Test /register
    update2, context2 = make_mock_update(user_id=7030, first_name="ApprovedUser")
    result2 = await register_command(update2, context2)
    assert result2 == ConversationHandler.END
    reply_text2 = update2.effective_message.reply_text.call_args[0][0]
    assert "already an approved customer" in reply_text2


# ==============================================================================
# 4. Multi-Step Conversation Flow Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_full_registration_conversation_flow(db_session: Session, valid_env_vars: dict) -> None:
    """Walk through complete registration flow: Consent -> Photo -> Phone -> Location -> Summary -> Confirm."""
    user_id = 8100

    # 1. Start consent step
    update, context = make_mock_update(user_id=user_id, first_name="Kidus")
    context.user_data["lang"] = "en"

    # Send "I Agree"
    update.effective_message.text = "✅ I Agree"
    next_state = await reg_consent_handler(update, context)
    assert next_state == REG_PHOTO
    assert context.user_data["consent_given"] is True
    assert "National ID" in update.effective_message.reply_text.call_args[0][0]

    # 2. Upload photo step
    photo_obj = PhotoSize(file_id="mock_file_id_nat_id", file_unique_id="u_01", width=800, height=600)
    update_photo, _ = make_mock_update(user_id=user_id, photo=[photo_obj])
    next_state = await reg_photo_handler(update_photo, context)
    assert next_state == REG_PHONE
    assert context.user_data["photo_file_id"] == "mock_file_id_nat_id"
    assert "Phone Number" in update_photo.effective_message.reply_text.call_args[0][0]

    # 3. Share phone via contact
    contact_obj = Contact(phone_number="0911556677", first_name="Kidus")
    update_contact, _ = make_mock_update(user_id=user_id, contact=contact_obj)
    next_state = await reg_phone_contact_handler(update_contact, context)
    assert next_state == REG_LOCATION
    assert context.user_data["phone"] == "+251911556677"
    assert context.user_data["phone_source"] == "TELEGRAM_CONTACT"
    assert "Residential Location" in update_contact.effective_message.reply_text.call_args[0][0]

    # 4. Share location via text address
    update_loc, _ = make_mock_update(user_id=user_id, text="Kazanchis, behind UNECA, Addis Ababa")
    next_state = await reg_location_text_handler(update_loc, context)
    assert next_state == REG_CONFIRM
    assert context.user_data["address"] == "Kazanchis, behind UNECA, Addis Ababa"

    # Verify summary message contains masked phone, address, and confirmation prompt
    summary_text = update_loc.effective_message.reply_text.call_args[0][0]
    assert "Registration Summary" in summary_text
    assert "Kazanchis, behind UNECA" in summary_text

    # 5. Confirm and submit
    update_confirm, _ = make_mock_update(user_id=user_id, text="✅ Confirm & Submit")
    end_state = await reg_confirm_handler(update_confirm, context)
    assert end_state == ConversationHandler.END

    # Verify customer in database is now PENDING and has verification details
    with db_session.no_autoflush:
        cust = db_session.query(Customer).filter_by(telegram_id=user_id).first()
        assert cust is not None
        assert cust.status == CustomerStatus.PENDING.value
        assert cust.national_id_file_id == "mock_file_id_nat_id"
        assert cust.phone_number == "+251911556677"
        assert cust.phone_verified is True
        assert cust.address == "Kazanchis, behind UNECA, Addis Ababa"
        assert cust.is_verification_complete is True


@pytest.mark.asyncio
async def test_registration_with_manual_phone_and_gps_location(db_session: Session, valid_env_vars: dict) -> None:
    """Registration using manual typed phone number and Telegram GPS location coordinates."""
    user_id = 8101
    update, context = make_mock_update(user_id=user_id, first_name="Selam")
    context.user_data["lang"] = "am"
    context.user_data["consent_given"] = True
    context.user_data["photo_file_id"] = "photo_selam_id_123"

    # 1. Manual phone text input
    update_phone, _ = make_mock_update(user_id=user_id, text="0712345678")
    next_state = await reg_phone_text_handler(update_phone, context)
    assert next_state == REG_LOCATION
    assert context.user_data["phone"] == "+251712345678"
    assert context.user_data["phone_source"] == "MANUAL_INPUT"

    # 2. GPS Location
    loc_obj = Location(latitude=9.0300, longitude=38.7400)
    update_loc, _ = make_mock_update(user_id=user_id, location=loc_obj)
    next_state = await reg_location_handler(update_loc, context)
    assert next_state == REG_CONFIRM
    assert context.user_data["latitude"] == 9.0300
    assert context.user_data["longitude"] == 38.7400

    # 3. Confirm
    update_confirm, _ = make_mock_update(user_id=user_id, text="✅ Confirm & Submit")
    end_state = await reg_confirm_handler(update_confirm, context)
    assert end_state == ConversationHandler.END

    cust = db_session.query(Customer).filter_by(telegram_id=user_id).first()
    assert cust is not None
    assert cust.phone_number == "+251712345678"
    assert cust.phone_verified is False  # Manual text is unverified
    assert float(cust.latitude) == pytest.approx(9.0300)
    assert float(cust.longitude) == pytest.approx(38.7400)


# ==============================================================================
# 5. Invalid Inputs, Navigation (Back, Cancel, Restart)
# ==============================================================================


@pytest.mark.asyncio
async def test_invalid_phone_number_keeps_in_phone_state(db_session: Session, valid_env_vars: dict) -> None:
    """Invalid manual phone format prompts error message and retains REG_PHONE state."""
    update, context = make_mock_update(user_id=8200, text="not-a-number")
    context.user_data["lang"] = "en"

    next_state = await reg_phone_text_handler(update, context)
    assert next_state == REG_PHONE
    error_msg = update.effective_message.reply_text.call_args[0][0]
    assert "Invalid phone number" in error_msg


@pytest.mark.asyncio
async def test_non_photo_text_in_photo_step(db_session: Session, valid_env_vars: dict) -> None:
    """Sending text instead of photo in REG_PHOTO reminds user to upload an image."""
    update, context = make_mock_update(user_id=8201, text="Here is my ID")
    context.user_data["lang"] = "en"

    next_state = await reg_photo_text_handler(update, context)
    assert next_state == REG_PHOTO
    reply_msg = update.effective_message.reply_text.call_args[0][0]
    assert "photo" in reply_msg.lower()


@pytest.mark.asyncio
async def test_navigation_back_buttons(db_session: Session, valid_env_vars: dict) -> None:
    """Back button moves user back one step in the conversation."""
    # From photo step -> back to consent
    update, context = make_mock_update(user_id=8202, text="⬅️ Back")
    context.user_data["lang"] = "en"
    state = await reg_photo_text_handler(update, context)
    assert state == REG_CONSENT

    # From phone step -> back to photo
    update2, context2 = make_mock_update(user_id=8202, text="⬅️ Back")
    context2.user_data["lang"] = "en"
    state2 = await reg_phone_text_handler(update2, context2)
    assert state2 == REG_PHOTO

    # From location step -> back to phone
    update3, context3 = make_mock_update(user_id=8202, text="⬅️ Back")
    context3.user_data["lang"] = "en"
    state3 = await reg_location_text_handler(update3, context3)
    assert state3 == REG_PHONE


@pytest.mark.asyncio
async def test_cancellation_and_restart(db_session: Session, valid_env_vars: dict) -> None:
    """Canceling cleans state and ends conversation; Restart starts over from consent."""
    # Cancel via button text
    update, context = make_mock_update(user_id=8203, text="❌ Cancel")
    context.user_data["lang"] = "en"
    state = await reg_cancel_handler(update, context, "en")
    assert state == ConversationHandler.END
    assert len(context.user_data) == 0

    # Cancel via command
    update2, context2 = make_mock_update(user_id=8203)
    state2 = await reg_cancel_command(update2, context2)
    assert state2 == ConversationHandler.END

    # Restart from confirm step
    update3, context3 = make_mock_update(user_id=8203, text="🔄 Restart")
    context3.user_data["lang"] = "en"
    state3 = await reg_confirm_handler(update3, context3)
    assert state3 == REG_CONSENT


# ==============================================================================
# 6. Admin Verification & ID Photo View Security
# ==============================================================================


@pytest.mark.asyncio
async def test_pending_command_includes_verification_details(db_session: Session, valid_env_vars: dict) -> None:
    """Owner running /pending sees verification status and ID photo action button."""
    cust = submit_customer_registration(
        session=db_session,
        telegram_id=8300,
        first_name="Belete",
        national_id_file_id="nat_id_belete_photo",
        phone_number="+251911445566",
        phone_source="TELEGRAM_CONTACT",
        address="Bole, Addis Ababa",
        latitude=None,
        longitude=None,
        language="en",
    )
    db_session.commit()

    update, context = make_mock_update(user_id=OWNER_ID)
    await pending_command(update, context)

    update.effective_message.reply_text.assert_called()
    msg_args, msg_kwargs = update.effective_message.reply_text.call_args
    card_text = msg_args[0]
    reply_markup: InlineKeyboardMarkup = msg_kwargs.get("reply_markup")

    # Verification markers present in card
    assert "Belete" in card_text
    assert "TELEGRAM_CONTACT" in card_text
    assert "Uploaded" in card_text
    assert "Bole, Addis Ababa" in card_text

    # Inline button to view ID photo is present
    buttons = [btn for row in reply_markup.inline_keyboard for btn in row]
    id_buttons = [btn for btn in buttons if btn.callback_data == f"view_id_photo:{cust.id}"]
    assert len(id_buttons) == 1


@pytest.mark.asyncio
async def test_view_id_photo_owner_access_granted(db_session: Session, valid_env_vars: dict) -> None:
    """Owner clicking view_id_photo receives photo delivered to chat."""
    cust = submit_customer_registration(
        session=db_session,
        telegram_id=8301,
        first_name="Hiwot",
        national_id_file_id="nat_id_hiwot_photo_file_id",
        phone_number="+251922334455",
        phone_source="MANUAL_TEXT",
        address="Arada Subcity",
        latitude=None,
        longitude=None,
        language="en",
    )
    db_session.commit()

    update, context = make_mock_callback_update(
        user_id=OWNER_ID,
        data=f"view_id_photo:{cust.id}",
    )
    await view_id_photo_callback(update, context)

    # Photo delivered via context.bot.send_photo
    context.bot.send_photo.assert_called_once()
    call_kwargs = context.bot.send_photo.call_args[1]
    assert call_kwargs["photo"] == "nat_id_hiwot_photo_file_id"
    assert "Hiwot" in call_kwargs["caption"]
    update.callback_query.answer.assert_called_with("Displaying ID photo...")


@pytest.mark.asyncio
async def test_view_id_photo_non_owner_access_denied(db_session: Session, valid_env_vars: dict) -> None:
    """Non-owner clicking view_id_photo callback is denied access."""
    cust = submit_customer_registration(
        session=db_session,
        telegram_id=8302,
        first_name="NonOwnerTest",
        national_id_file_id="secret_id_file",
        phone_number="+251933445566",
        phone_source="TELEGRAM_CONTACT",
        address="Addis Ababa",
        latitude=None,
        longitude=None,
        language="en",
    )
    db_session.commit()

    update, context = make_mock_callback_update(
        user_id=NON_OWNER_ID,
        data=f"view_id_photo:{cust.id}",
    )
    await view_id_photo_callback(update, context)

    # Not allowed to see photo
    context.bot.send_photo.assert_not_called()
    update.callback_query.answer.assert_called_with(
        "⛔ Unauthorized: Owner access required.", show_alert=True
    )


# ==============================================================================
# 7. Localized Event Notifications & Failure Resilience
# ==============================================================================


@pytest.mark.asyncio
async def test_notify_customer_localized(db_session: Session, valid_env_vars: dict) -> None:
    """notify_customer picks user's preferred language from database and sends translated text."""
    cust, _ = register_customer(db_session, telegram_id=8400, first_name="Tigist")
    cust.language = "am"
    db_session.commit()

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    success = await notify_customer(
        bot=mock_bot,
        customer_telegram_id=8400,
        event_key="notify_customer_approved",
        name="Tigist",
    )
    assert success is True
    mock_bot.send_message.assert_called_once()
    msg_text = mock_bot.send_message.call_args[1]["text"]
    assert "መለያዎ ጸድቋል" in msg_text  # Amharic approval text


@pytest.mark.asyncio
async def test_notify_customer_english_fallback(db_session: Session, valid_env_vars: dict) -> None:
    """notify_customer falls back to English when customer has no preferred language set."""
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    # Use a telegram ID that doesn't exist in DB to test DEFAULT_LANGUAGE fallback
    success = await notify_customer(
        bot=mock_bot,
        customer_telegram_id=999888777,
        event_key="notify_customer_rejected",
        name="John",
        reason_line="• Reason: Incomplete national ID image\n",
    )
    assert success is True
    msg_text = mock_bot.send_message.call_args[1]["text"]
    assert "Account Update" in msg_text
    assert "Incomplete national ID image" in msg_text


@pytest.mark.asyncio
async def test_notify_admins_dispatches_to_all_configured_owners(valid_env_vars: dict) -> None:
    """notify_admins delivers alert to all configured ADMIN_USER_IDS (12345, 67890)."""
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    count = await notify_admins(
        bot=mock_bot,
        event_key="notify_owner_new_registration",
        name="NewUser",
        telegram_id=9876,
    )
    # valid_env_vars has ADMIN_USER_IDS="12345,67890" -> 2 admins
    assert count == 2
    assert mock_bot.send_message.call_count == 2
    recipients = [call[1]["chat_id"] for call in mock_bot.send_message.call_args_list]
    assert 12345 in recipients
    assert 67890 in recipients


@pytest.mark.asyncio
async def test_notification_failure_does_not_raise(valid_env_vars: dict) -> None:
    """Telegram errors during notification delivery are caught, logged, and return False."""
    from telegram.error import NetworkError

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(side_effect=NetworkError("Telegram server unreachable"))

    # Must return False and NOT raise an unhandled exception
    success = await notify_customer(
        bot=mock_bot,
        customer_telegram_id=8402,
        event_key="notify_rental_due_today",
        title="Python Guide",
        date="2026-10-25",
    )
    assert success is False


@pytest.mark.asyncio
async def test_announce_new_stock_setting(db_session: Session, valid_env_vars: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """announce_new_stock broadcasts to approved customers only if ANNOUNCE_NEW_BOOKS is True."""
    cust1, _ = register_customer(db_session, telegram_id=8501, first_name="Appr1")
    cust1.status = CustomerStatus.APPROVED.value
    cust2, _ = register_customer(db_session, telegram_id=8502, first_name="Appr2")
    cust2.status = CustomerStatus.APPROVED.value
    cust3, _ = register_customer(db_session, telegram_id=8503, first_name="Pending3")
    cust3.status = CustomerStatus.PENDING.value
    db_session.commit()

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    # 1. Disabled (default is False)
    monkeypatch.setenv("ANNOUNCE_NEW_BOOKS", "false")
    get_settings.cache_clear()
    count_disabled = await announce_new_stock(mock_bot, "Clean Code", "Robert Martin")
    assert count_disabled == 0

    # 2. Enabled
    monkeypatch.setenv("ANNOUNCE_NEW_BOOKS", "true")
    get_settings.cache_clear()
    count_enabled = await announce_new_stock(mock_bot, "Clean Code", "Robert Martin")
    assert count_enabled == 2  # Only the 2 approved customers


# ==============================================================================
# 8. Sensitive Data Masking Tests
# ==============================================================================


def test_sensitive_data_masking() -> None:
    """Verify phone masking and log filter redaction."""
    # Direct mask_phone
    assert "****" in mask_phone("+251911234567")
    assert "****" in mask_phone("0911234567")
    assert mask_phone("123") == "****"

    # Filter redaction in logging
    log_filter = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Customer registered with token 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ and file_id='AgACAgIAAxkBAAI_xyz123'",
        args=(),
        exc_info=None,
    )
    log_filter.filter(record)
    assert "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ" not in record.msg
    assert "***REDACTED***" in record.msg
    assert "AgACAgIAAxkBAAI_xyz123" not in record.msg
