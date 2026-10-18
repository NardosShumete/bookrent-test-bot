"""Telegram bot handlers for Phase 3 and Phase 4 customer workflows, owner approvals, catalogue, inventory, rental requests, payment verification, and physical checkout."""

from decimal import Decimal, InvalidOperation
import html
import logging
from typing import List, Optional
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from app.config import get_settings
from app.database.session import get_db_session
from app.localization import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    get_add_book_confirm_keyboard,
    get_admin_reply_keyboard,
    get_book_search_menu_keyboard,
    get_cancel_keyboard,
    get_confirm_registration_keyboard,
    get_consent_keyboard,
    get_customer_reply_keyboard,
    get_existing_book_action_keyboard,
    get_isbn_step_keyboard,
    get_language_inline_keyboard,
    get_location_step_keyboard,
    get_owner_request_action_keyboard,
    get_owner_return_action_keyboard,
    get_phone_step_keyboard,
    get_photo_step_keyboard,
    get_rental_collateral_keyboard,
    get_rental_confirm_keyboard,
    get_step_nav_keyboard,
    t,
)
from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import (
    BookCopyStatus,
    CollateralType,
    CustomerStatus,
    ExtensionStatus,
    PaymentMethod,
    PaymentType,
    PaymentVerificationStatus,
    RentalRequestStatus,
    RentalStatus,
)
from app.models.exceptions import (
    ActiveExtensionRequestExistsError,
    CheckoutConditionsNotMetError,
    CopyNotAvailableError,
    CustomerNotApprovedError,
    CustomerNotFoundError,
    ExtensionAlreadyAppliedError,
    ExtensionNotFoundError,
    ExtensionPaymentNotVerifiedError,
    InsufficientCollateralError,
    InvalidCustomerStatusError,
    InvalidISBNError,
    InvalidRentalRequestStatusError,
    InvalidReturnConditionError,
    MissingBookDetailsError,
    PaymentAlreadyVerifiedError,
    RentalAlreadyReturnedError,
    RentalNotActiveError,
    RentalNotFoundError,
    RentalRequestAlreadyCompletedError,
    RentalRequestNotFoundError,
    UnauthorizedError,
)
from app.models.rental import Rental, RentalExtension
from app.models.rental_request import RentalRequest
from app.services.book_catalog import (
    create_book,
    get_book_inventory_details,
    get_overall_inventory_summary,
    receive_stock_for_isbn,
    search_books,
)
from app.services.inventory import record_received_copies
from app.services.isbn import normalize_isbn
from app.services.customer import (
    approve_customer,
    get_customer_by_telegram_id,
    get_customer_language,
    get_pending_customers,
    get_rejected_customers,
    is_owner,
    normalize_phone_number,
    reapprove_customer,
    register_customer,
    reject_customer,
    set_customer_language,
    submit_customer_registration,
)
from app.services.notification import (
    announce_new_stock,
    notify_admins,
    notify_customer,
)
from app.services.due_date import get_rental_timezone
from app.services.overdue import (
    get_all_overdue_rentals,
    get_rental_overdue_summary,
    process_overdue_rentals,
    send_overdue_notifications,
)
from app.services.rental import (
    approve_rental_extension,
    confirm_rental_return,
    get_customer_active_rentals,
    get_pending_extension_requests,
    get_rental_financial_reconciliation,
    reject_rental_extension,
    submit_extension_request,
    verify_and_approve_extension,
    verify_extension_payment,
)
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


logger = logging.getLogger(__name__)


# ==============================================================================
# Phase 8: Registration Conversation States
# ==============================================================================
REG_CONSENT = 1
REG_PHOTO = 2
REG_PHONE = 3
REG_LOCATION = 4
REG_CONFIRM = 5

# Guided Add Book Conversation States
ADD_BOOK_ISBN = 10
ADD_BOOK_TITLE = 11
ADD_BOOK_AUTHOR = 12
ADD_BOOK_PRICE = 13
ADD_BOOK_METADATA = 14
ADD_BOOK_COPIES = 15
ADD_BOOK_CONFIRM = 16


async def prompt_registration_consent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> int:
    """Send privacy explanation and prompt user consent to begin registration."""
    if context.user_data is not None:
        context.user_data.clear()
        context.user_data["lang"] = lang

    settings = get_settings()
    consent_text = t("reg_consent_prompt", lang, version=settings.consent_policy_version)
    keyboard = get_consent_keyboard(lang)
    if update.effective_message:
        await update.effective_message.reply_text(
            consent_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
        )
    return REG_CONSENT


async def show_user_menu_or_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    lang: str,
    from_callback: bool = False,
) -> None:
    """Render the appropriate menu and status for an authorized owner or customer."""
    first_name = (update.effective_user.first_name if update.effective_user else "") or "Reader"
    escaped_name = html.escape(first_name)

    if is_owner(user_id):
        owner_text = t("welcome_admin", lang, name=escaped_name)
        reply_markup = get_admin_reply_keyboard(lang)
        if update.effective_message:
            await update.effective_message.reply_text(
                owner_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
            )
        return

    # Standard customer workflow
    with get_db_session() as session:
        customer = get_customer_by_telegram_id(session, user_id)
        if customer and customer.is_approved:
            status_text = t("welcome_approved", lang, name=escaped_name)
            markup = get_customer_reply_keyboard(lang)
        elif customer and customer.status == CustomerStatus.PENDING.value:
            status_text = t("welcome_pending", lang, name=escaped_name)
            markup = ReplyKeyboardMarkup(
                [
                    [
                        KeyboardButton(t("btn_change_language", lang)),
                        KeyboardButton(t("btn_cust_help", lang)),
                    ]
                ],
                resize_keyboard=True,
            )
        elif customer and customer.status == CustomerStatus.REJECTED.value:
            reason_info = ""
            if customer.rejection_reason:
                reason_info = t(
                    "rejection_reason_label", lang, reason=html.escape(customer.rejection_reason)
                )
            status_text = t(
                "welcome_rejected", lang, name=escaped_name, reason_info=reason_info
            )
            markup = ReplyKeyboardMarkup(
                [
                    [
                        KeyboardButton(t("btn_change_language", lang)),
                        KeyboardButton(t("btn_cust_help", lang)),
                    ]
                ],
                resize_keyboard=True,
            )
        else:
            await prompt_registration_consent(update, context, lang)
            return

        if update.effective_message:
            await update.effective_message.reply_text(
                status_text, reply_markup=markup, parse_mode=ParseMode.HTML
            )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command.

    First-time users choose their language (English or Amharic) before accessing any services.
    Approved customers receive their customer menu.
    New or unverified customers are guided through the verification registration conversation.
    """
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    user = update.effective_user
    user_id = user.id

    if is_owner(user_id):
        with get_db_session() as session:
            saved_lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        owner_text = t("welcome_admin", saved_lang, name=html.escape(user.first_name or "Admin"))
        reply_markup = get_admin_reply_keyboard(saved_lang)
        await update.effective_message.reply_text(
            owner_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    with get_db_session() as session:
        saved_lang = get_customer_language(session, user_id)
        customer = get_customer_by_telegram_id(session, user_id)

    if not saved_lang:
        prompt = t("lang_prompt", "en")
        keyboard = get_language_inline_keyboard()
        await update.effective_message.reply_text(prompt, reply_markup=keyboard)
        return ConversationHandler.END

    if customer and customer.is_approved:
        escaped_name = html.escape(customer.first_name or user.first_name or "Reader")
        status_text = t("welcome_approved", saved_lang, name=escaped_name)
        markup = get_customer_reply_keyboard(saved_lang)
        await update.effective_message.reply_text(
            status_text, reply_markup=markup, parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    if customer and customer.status == CustomerStatus.PENDING.value:
        escaped_name = html.escape(customer.first_name or user.first_name or "Reader")
        status_text = t("welcome_pending", saved_lang, name=escaped_name)
        markup = ReplyKeyboardMarkup(
            [
                [
                    KeyboardButton(t("btn_change_language", saved_lang)),
                    KeyboardButton(t("btn_cust_help", saved_lang)),
                ]
            ],
            resize_keyboard=True,
        )
        await update.effective_message.reply_text(
            status_text, reply_markup=markup, parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    if customer and customer.status == CustomerStatus.REJECTED.value:
        escaped_name = html.escape(customer.first_name or user.first_name or "Reader")
        reason_info = ""
        if customer.rejection_reason:
            reason_info = t(
                "rejection_reason_label", saved_lang, reason=html.escape(customer.rejection_reason)
            )
        status_text = t(
            "welcome_rejected", saved_lang, name=escaped_name, reason_info=reason_info
        )
        markup = ReplyKeyboardMarkup(
            [
                [
                    KeyboardButton(t("btn_change_language", saved_lang)),
                    KeyboardButton(t("btn_cust_help", saved_lang)),
                ]
            ],
            resize_keyboard=True,
        )
        await update.effective_message.reply_text(
            status_text, reply_markup=markup, parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    return await prompt_registration_consent(update, context, saved_lang)


async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Customer command /register to submit or update identity verification details."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    user = update.effective_user
    user_id = user.id

    if is_owner(user_id):
        await update.effective_message.reply_text("ℹ️ Administrators do not require customer registration.")
        return ConversationHandler.END

    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        customer = get_customer_by_telegram_id(session, user_id)

    if customer and customer.is_approved:
        await update.effective_message.reply_text(
            "✅ You are already an approved customer! Send /books or /search to browse catalogue."
        )
        return ConversationHandler.END

    return await prompt_registration_consent(update, context, lang)


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /language command allowing users to change their preferred language."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    with get_db_session() as session:
        current_lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    prompt = t("choose_language", current_lang)
    keyboard = get_language_inline_keyboard()
    await update.effective_message.reply_text(prompt, reply_markup=keyboard)


async def language_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle inline button callback for language selection (lang:en, lang:am)."""
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    data = query.data
    _, _, chosen_lang = data.partition(":")
    if chosen_lang not in SUPPORTED_LANGUAGES:
        await query.answer("Invalid language selection.")
        return ConversationHandler.END

    user = query.from_user
    with get_db_session() as session:
        set_customer_language(
            session=session,
            telegram_id=user.id,
            language=chosen_lang,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )
        customer = get_customer_by_telegram_id(session, user.id)

    await query.answer()
    confirm_text = t(f"lang_selected_{chosen_lang}", chosen_lang)
    await query.edit_message_text(confirm_text, parse_mode=ParseMode.HTML)

    if is_owner(user.id):
        await show_user_menu_or_status(
            update, context, user_id=user.id, lang=chosen_lang, from_callback=True
        )
        return ConversationHandler.END

    if customer and customer.is_approved:
        await show_user_menu_or_status(
            update, context, user_id=user.id, lang=chosen_lang, from_callback=True
        )
        return ConversationHandler.END

    if customer and customer.status == CustomerStatus.PENDING.value and customer.is_verification_complete:
        await show_user_menu_or_status(
            update, context, user_id=user.id, lang=chosen_lang, from_callback=True
        )
        return ConversationHandler.END

    if customer and customer.status == CustomerStatus.REJECTED.value:
        await show_user_menu_or_status(
            update, context, user_id=user.id, lang=chosen_lang, from_callback=True
        )
        return ConversationHandler.END

    return await prompt_registration_consent(update, context, chosen_lang)


# ==============================================================================
# Registration Conversation Step Handlers
# ==============================================================================


async def reg_consent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user consent response for privacy policy."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    text = (update.effective_message.text or "").strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    agree_label = t("btn_consent_agree", lang)
    cancel_label = t("btn_cancel", lang)

    if text in (cancel_label, "❌ Cancel", "❌ ሰርዝ", "Cancel", "ሰርዝ", "/cancel"):
        return await reg_cancel_handler(update, context, lang)

    if text in (agree_label, "✅ I Agree", "✅ እስማማለሁ", "I Agree", "እስማማለሁ", "agree", "yes"):
        if context.user_data is not None:
            context.user_data["consent_given"] = True
            context.user_data["lang"] = lang
        prompt = t("reg_step_photo", lang)
        keyboard = get_photo_step_keyboard(lang)
        await update.effective_message.reply_text(
            prompt, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )
        return REG_PHOTO

    retry_msg = t("reg_consent_prompt", lang, version=get_settings().consent_policy_version)
    keyboard = get_consent_keyboard(lang)
    await update.effective_message.reply_text(
        retry_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML
    )
    return REG_CONSENT


async def reg_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle National ID photo upload."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    photo_objs = update.effective_message.photo
    if not photo_objs:
        err_msg = t("reg_err_photo_required", lang)
        keyboard = get_photo_step_keyboard(lang)
        await update.effective_message.reply_text(err_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return REG_PHOTO

    best_photo = photo_objs[-1]
    if context.user_data is not None:
        context.user_data["photo_file_id"] = best_photo.file_id

    prompt = t("reg_step_phone", lang)
    keyboard = get_phone_step_keyboard(lang)
    await update.effective_message.reply_text(prompt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    return REG_PHONE


async def reg_photo_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text input during photo step (e.g. Back, Cancel, or invalid text)."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    text = (update.effective_message.text or "").strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_back", lang), "⬅️ Back", "⬅️ ወደኋላ", "Back", "ወደኋላ"):
        return await prompt_registration_consent(update, context, lang)

    if text in (t("btn_cancel", lang), "❌ Cancel", "❌ ሰርዝ", "Cancel", "ሰርዝ", "/cancel"):
        return await reg_cancel_handler(update, context, lang)

    err_msg = t("reg_err_photo_required", lang)
    keyboard = get_photo_step_keyboard(lang)
    await update.effective_message.reply_text(err_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    return REG_PHOTO


async def reg_phone_contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle phone number shared via Telegram Contact button."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    contact = update.effective_message.contact
    if not contact or not contact.phone_number:
        err_msg = t("reg_err_phone_invalid", lang)
        keyboard = get_phone_step_keyboard(lang)
        await update.effective_message.reply_text(err_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return REG_PHONE

    raw_phone = contact.phone_number
    normalized = normalize_phone_number(raw_phone) or raw_phone
    if context.user_data is not None:
        context.user_data["phone"] = normalized
        context.user_data["phone_source"] = "TELEGRAM_CONTACT"
        context.user_data["phone_verified"] = True

    prompt = t("reg_step_location", lang)
    keyboard = get_location_step_keyboard(lang)
    await update.effective_message.reply_text(prompt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    return REG_LOCATION


async def reg_phone_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle manual phone number text input or navigation buttons."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    text = (update.effective_message.text or "").strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_back", lang), "⬅️ Back", "⬅️ ወደኋላ", "Back", "ወደኋላ"):
        prompt = t("reg_step_photo", lang)
        keyboard = get_photo_step_keyboard(lang)
        await update.effective_message.reply_text(prompt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return REG_PHOTO

    if text in (t("btn_cancel", lang), "❌ Cancel", "❌ ሰርዝ", "Cancel", "ሰርዝ", "/cancel"):
        return await reg_cancel_handler(update, context, lang)

    normalized = normalize_phone_number(text)
    if not normalized:
        err_msg = t("reg_err_phone_invalid", lang)
        keyboard = get_phone_step_keyboard(lang)
        await update.effective_message.reply_text(err_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return REG_PHONE

    if context.user_data is not None:
        context.user_data["phone"] = normalized
        context.user_data["phone_source"] = "MANUAL_INPUT"
        context.user_data["phone_verified"] = False

    prompt = t("reg_step_location", lang)
    keyboard = get_location_step_keyboard(lang)
    await update.effective_message.reply_text(prompt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    return REG_LOCATION


async def show_registration_summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> int:
    """Render registration verification summary before final submission."""
    user = update.effective_user
    full_name = html.escape(f"{user.first_name if user else ''} {user.last_name or '' if user else ''}".strip())
    phone = (context.user_data.get("phone", "N/A") if context.user_data else "N/A")
    source_val = (context.user_data.get("phone_source", "MANUAL_INPUT") if context.user_data else "MANUAL_INPUT")
    source_str = "Telegram Contact" if source_val == "TELEGRAM_CONTACT" else "Manual"
    if lang == "am":
        source_str = "በቴሌግራም የተጋራ" if source_val == "TELEGRAM_CONTACT" else "በጽሑፍ የገባ"
    address = html.escape((context.user_data.get("address", "N/A") if context.user_data else "N/A"))

    summary_text = t(
        "reg_summary",
        lang,
        name=full_name,
        phone=phone,
        source=source_str,
        address=address,
    )
    keyboard = get_confirm_registration_keyboard(lang)
    if update.effective_message:
        await update.effective_message.reply_text(
            summary_text, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )
    return REG_CONFIRM


async def reg_location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle residential location shared via Telegram Location button."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    loc = update.effective_message.location
    if not loc:
        err_msg = t("reg_err_location_required", lang)
        keyboard = get_location_step_keyboard(lang)
        await update.effective_message.reply_text(err_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return REG_LOCATION

    if context.user_data is not None:
        context.user_data["latitude"] = loc.latitude
        context.user_data["longitude"] = loc.longitude
        context.user_data["address"] = f"GPS: {loc.latitude:.5f}, {loc.longitude:.5f}"

    return await show_registration_summary(update, context, lang)


async def reg_location_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle manual residential address text input or navigation buttons."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    text = (update.effective_message.text or "").strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_back", lang), "⬅️ Back", "⬅️ ወደኋላ", "Back", "ወደኋላ"):
        prompt = t("reg_step_phone", lang)
        keyboard = get_phone_step_keyboard(lang)
        await update.effective_message.reply_text(prompt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return REG_PHONE

    if text in (t("btn_cancel", lang), "❌ Cancel", "❌ ሰርዝ", "Cancel", "ሰርዝ", "/cancel"):
        return await reg_cancel_handler(update, context, lang)

    if len(text) < 3:
        err_msg = t("reg_err_location_required", lang)
        keyboard = get_location_step_keyboard(lang)
        await update.effective_message.reply_text(err_msg, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return REG_LOCATION

    if context.user_data is not None:
        context.user_data["address"] = text
        context.user_data["latitude"] = None
        context.user_data["longitude"] = None

    return await show_registration_summary(update, context, lang)


async def reg_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle final confirmation and persistence of customer registration."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    text = (update.effective_message.text or "").strip()
    user = update.effective_user
    user_id = user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_back", lang), "⬅️ Back", "⬅️ ወደኋላ", "Back", "ወደኋላ"):
        prompt = t("reg_step_location", lang)
        keyboard = get_location_step_keyboard(lang)
        await update.effective_message.reply_text(prompt, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return REG_LOCATION

    if text in (t("btn_cancel", lang), "❌ Cancel", "❌ ሰርዝ", "Cancel", "ሰርዝ", "/cancel"):
        return await reg_cancel_handler(update, context, lang)

    if text in ("🔄 Restart", "🔄 እንደገና ጀምር", "Restart", "እንደገና"):
        return await prompt_registration_consent(update, context, lang)

    confirm_label = t("btn_confirm_submit", lang)
    if text in (confirm_label, "✅ Confirm & Submit", "✅ አረጋግጥና ላክ", "Confirm", "አረጋግጥ", "yes"):
        settings = get_settings()
        u_data = context.user_data or {}
        with get_db_session() as session:
            cust = submit_customer_registration(
                session=session,
                telegram_id=user_id,
                first_name=user.first_name or "Reader",
                last_name=user.last_name,
                username=user.username,
                phone_number=u_data.get("phone", ""),
                phone_source=u_data.get("phone_source", "MANUAL_INPUT"),
                phone_verified=u_data.get("phone_verified", False),
                address=u_data.get("address", ""),
                latitude=u_data.get("latitude"),
                longitude=u_data.get("longitude"),
                national_id_file_id=u_data.get("photo_file_id"),
                consent_given=u_data.get("consent_given", True),
                consent_policy_version=settings.consent_policy_version,
            )
            cust_id = cust.id
            cust_name = cust.first_name
            cust_phone = cust.phone_number
            cust_addr = cust.address

        if context.user_data is not None:
            context.user_data.clear()

        success_text = t("reg_submitted_success", lang)
        pending_markup = ReplyKeyboardMarkup(
            [
                [
                    KeyboardButton(t("btn_change_language", lang)),
                    KeyboardButton(t("btn_cust_help", lang)),
                ]
            ],
            resize_keyboard=True,
        )
        await update.effective_message.reply_text(
            success_text, reply_markup=pending_markup, parse_mode=ParseMode.HTML
        )

        await notify_admins(
            bot=context.bot,
            event_key="notify_reg_submitted_admin",
            id=cust_id,
            name=cust_name,
            phone=cust_phone,
            address=cust_addr,
        )
        return ConversationHandler.END

    await show_registration_summary(update, context, lang)
    return REG_CONFIRM


async def reg_cancel_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str = DEFAULT_LANGUAGE,
) -> int:
    """Abort registration and remove keyboard."""
    if context.user_data is not None:
        context.user_data.clear()
    cancel_text = t("reg_cancelled", lang)
    if update.effective_message:
        await update.effective_message.reply_text(
            cancel_text, reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML
        )
    return ConversationHandler.END


async def reg_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Command fallback /cancel to abort active registration conversation."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
    return await reg_cancel_handler(update, context, lang)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command to list commands appropriate to user role in their preferred language."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if is_owner(user_id):
        help_text = t("desc_admin_help", lang)
    else:
        help_text = t("desc_cust_help", lang)

    await update.effective_message.reply_text(help_text, parse_mode=ParseMode.HTML)



async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ping command for connectivity latency checks."""
    if not update.effective_message:
        return
    await update.effective_message.reply_text("🏓 Pong! Bot service is online.")


# ==============================================================================
# Owner Handlers: Customer Approvals
# ==============================================================================


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to list all pending customer registrations."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Access denied: This command is restricted to library owners.")
        return

    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        pending = get_pending_customers(session, actor_telegram_id=user_id)
        if not pending:
            empty_msg = (
                "✅ There are no pending customer registrations at this time."
                if lang == "en"
                else "✅ በአሁን ወቅት በመጠባበቅ ላይ ያሉ ደንበኞች የሉም።"
            )
            await update.effective_message.reply_text(empty_msg)
            return

        header = (
            f"📋 <b>Pending Registrations ({len(pending)}):</b>"
            if lang == "en"
            else f"📋 <b>በመጠባበቅ ላይ ያሉ ደንበኞች ({len(pending)})፦</b>"
        )
        await update.effective_message.reply_text(header, parse_mode=ParseMode.HTML)

        for cust in pending:
            full_name = html.escape(f"{cust.first_name} {cust.last_name or ''}".strip())
            uname = f"@{html.escape(cust.username)}" if cust.username else "<i>none</i>"
            registered_at = cust.created_at.strftime("%Y-%m-%d %H:%M UTC")
            phone_disp = f"{cust.phone_number} ({cust.phone_source or 'Manual'})" if cust.phone_number else "Not provided"
            addr_disp = cust.address or "Not provided"
            id_disp = "Uploaded ✅" if cust.national_id_file_id else "Not uploaded ❌"
            consent_disp = f"Given ✅ (v{cust.consent_policy_version or '1.0'})" if cust.consent_given else "Pending"

            card = (
                f"👤 <b>Customer #{cust.id}</b>\n"
                f"• Name: <b>{full_name}</b>\n"
                f"• Username: {uname}\n"
                f"• Telegram ID: <code>{cust.telegram_id}</code>\n"
                f"• Phone: <b>{phone_disp}</b>\n"
                f"• Address: <i>{html.escape(addr_disp)}</i>\n"
                f"• National ID: {id_disp}\n"
                f"• Consent: {consent_disp}\n"
                f"• Registered: {registered_at}"
            ) if lang == "en" else (
                f"👤 <b>ደንበኛ #{cust.id}</b>\n"
                f"• ስም፦ <b>{full_name}</b>\n"
                f"• የተጠቃሚ ስም፦ {uname}\n"
                f"• ቴሌግራም ID፦ <code>{cust.telegram_id}</code>\n"
                f"• ስልክ፦ <b>{phone_disp}</b>\n"
                f"• አድራሻ፦ <i>{html.escape(addr_disp)}</i>\n"
                f"• ብሔራዊ መታወቂያ፦ {id_disp}\n"
                f"• ፈቃድ፦ {consent_disp}\n"
                f"• የተመዘገበበት፦ {registered_at}"
            )
            buttons = []
            if cust.national_id_file_id:
                buttons.append([
                    InlineKeyboardButton(
                        "🆔 View ID Photo" if lang == "en" else "🆔 የመታወቂያ ፎቶ እይ",
                        callback_data=f"view_id_photo:{cust.id}",
                    )
                ])
            buttons.append([
                InlineKeyboardButton(
                    "✅ Approve" if lang == "en" else "✅ አጽድቅ",
                    callback_data=f"approve_cust:{cust.id}",
                ),
                InlineKeyboardButton(
                    "❌ Reject" if lang == "en" else "❌ ውድቅ አድርግ",
                    callback_data=f"reject_cust:{cust.id}",
                ),
            ])
            keyboard = InlineKeyboardMarkup(buttons)
            await update.effective_message.reply_text(card, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def view_id_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback to display a customer's National ID photo to authorized owner."""
    query = update.callback_query
    if not query or not query.data:
        return

    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    _, _, id_str = query.data.partition(":")
    if not id_str.isdigit():
        await query.answer("Invalid callback data.")
        return

    customer_id = int(id_str)
    with get_db_session() as session:
        cust = session.get(Customer, customer_id)
        if not cust or not cust.national_id_file_id:
            await query.answer("No ID photo found for this customer.", show_alert=True)
            return
        file_id = cust.national_id_file_id
        name = html.escape(f"{cust.first_name} {cust.last_name or ''}".strip())

    await query.answer("Displaying ID photo...")
    try:
        await context.bot.send_photo(
            chat_id=user_id,
            photo=file_id,
            caption=f"🆔 <b>National ID Photo:</b> Customer #{customer_id} (<b>{name}</b>)",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning("Could not send ID photo to owner %s: %s", user_id, exc)
        if query.message:
            await query.message.reply_text(
                f"⚠️ Could not retrieve ID photo from Telegram: {html.escape(str(exc))}"
            )


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to approve a customer by ID: /approve <customer_id>."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Access denied: This command is restricted to library owners.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /approve <customer_id>\nExample: /approve 1")
        return

    customer_id = int(context.args[0])
    with get_db_session() as session:
        try:
            cust = approve_customer(session, customer_id, actor_telegram_id=user_id)
            name = html.escape(f"{cust.first_name} {cust.last_name or ''}".strip())
            cust_telegram_id = cust.telegram_id
            cust_name = cust.first_name
            await update.effective_message.reply_text(
                f"✅ Customer <b>{name}</b> (#{cust.id}, Telegram ID: <code>{cust.telegram_id}</code>) has been <b>APPROVED</b>.",
                parse_mode=ParseMode.HTML,
            )
        except CustomerNotFoundError:
            await update.effective_message.reply_text(f"❌ Customer #{customer_id} was not found.")
            return
        except InvalidCustomerStatusError as exc:
            await update.effective_message.reply_text(f"⚠️ {html.escape(str(exc))}")
            return

    await notify_customer(
        bot=context.bot,
        customer_telegram_id=cust_telegram_id,
        event_key="notify_customer_approved",
        name=cust_name,
    )


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to reject a customer by ID: /reject <customer_id> [reason]."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Access denied: This command is restricted to library owners.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /reject <customer_id> [reason]\nExample: /reject 1 Ineligible")
        return

    customer_id = int(context.args[0])
    reason = " ".join(context.args[1:]).strip() if len(context.args) > 1 else None

    with get_db_session() as session:
        try:
            cust = reject_customer(session, customer_id, actor_telegram_id=user_id, reason=reason)
            name = html.escape(f"{cust.first_name} {cust.last_name or ''}".strip())
            cust_telegram_id = cust.telegram_id
            rejection_reason = cust.rejection_reason
            await update.effective_message.reply_text(
                f"❌ Customer <b>{name}</b> (#{cust.id}) has been <b>REJECTED</b>.",
                parse_mode=ParseMode.HTML,
            )
        except CustomerNotFoundError:
            await update.effective_message.reply_text(f"❌ Customer #{customer_id} was not found.")
            return
        except InvalidCustomerStatusError as exc:
            await update.effective_message.reply_text(f"⚠️ {html.escape(str(exc))}")
            return

    reason_line = f"Reason: {rejection_reason}" if rejection_reason else ""
    await notify_customer(
        bot=context.bot,
        customer_telegram_id=cust_telegram_id,
        event_key="notify_customer_rejected",
        reason_line=reason_line,
    )


async def customer_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callbacks for approving or rejecting customer registrations.

    Includes repeated-callback guards and owner authorization checks.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    data = query.data
    action, _, id_str = data.partition(":")
    if action not in ("approve_cust", "reject_cust") or not id_str.isdigit():
        await query.answer("Invalid callback data.")
        return

    customer_id = int(id_str)
    cust_telegram_id = None
    cust_first_name = None
    rejection_reason = None

    with get_db_session() as session:
        try:
            if action == "approve_cust":
                cust = approve_customer(session, customer_id, actor_telegram_id=user_id)
                cust_telegram_id = cust.telegram_id
                cust_first_name = cust.first_name
                await query.answer(f"Customer #{cust.id} approved!")
                new_text = (
                    f"✅ <b>Approved:</b> Customer #{cust.id} "
                    f"({html.escape(cust.first_name)} {html.escape(cust.last_name or '')})\n"
                    f"Telegram ID: <code>{cust.telegram_id}</code>"
                )
            else:
                cust = reject_customer(session, customer_id, actor_telegram_id=user_id)
                cust_telegram_id = cust.telegram_id
                rejection_reason = cust.rejection_reason
                await query.answer(f"Customer #{cust.id} rejected.")
                new_text = (
                    f"❌ <b>Rejected:</b> Customer #{cust.id} "
                    f"({html.escape(cust.first_name)} {html.escape(cust.last_name or '')})"
                )

            await query.edit_message_text(new_text, parse_mode=ParseMode.HTML)
        except CustomerNotFoundError:
            await query.answer("Customer not found.", show_alert=True)
            await query.edit_message_text("❌ Customer record not found.")
            return
        except InvalidCustomerStatusError as exc:
            await query.answer("Notice: Customer is already processed.", show_alert=False)
            await query.edit_message_text(f"ℹ️ {html.escape(str(exc))}")
            return

    if action == "approve_cust" and cust_telegram_id:
        await notify_customer(
            bot=context.bot,
            customer_telegram_id=cust_telegram_id,
            event_key="notify_customer_approved",
            name=cust_first_name or "Reader",
        )
    elif action == "reject_cust" and cust_telegram_id:
        reason_line = f"Reason: {rejection_reason}" if rejection_reason else ""
        await notify_customer(
            bot=context.bot,
            customer_telegram_id=cust_telegram_id,
            event_key="notify_customer_rejected",
            reason_line=reason_line,
        )


# ==============================================================================
# Owner Handlers: Rejected Customer Management & Reconsideration
# ==============================================================================

REJECTED_PAGE_SIZE = 5


async def _render_rejected_customers_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    page: int,
    edit_message: bool = False,
) -> None:
    """Render a paginated view of rejected customer accounts with Reapprove options."""
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        rejected = get_rejected_customers(session, actor_telegram_id=user_id)

        if not rejected:
            empty_msg = t("rejected_empty", lang)
            if edit_message and update.callback_query:
                await update.callback_query.edit_message_text(empty_msg)
            elif update.effective_message:
                await update.effective_message.reply_text(empty_msg)
            return

        total_count = len(rejected)
        total_pages = max(1, (total_count + REJECTED_PAGE_SIZE - 1) // REJECTED_PAGE_SIZE)
        page = max(1, min(page, total_pages))

        start_idx = (page - 1) * REJECTED_PAGE_SIZE
        end_idx = start_idx + REJECTED_PAGE_SIZE
        page_customers = rejected[start_idx:end_idx]

        header = t("rejected_list_header", lang, total=total_count, page=page, total_pages=total_pages)
        cards_text = [header]

        for cust in page_customers:
            full_name = html.escape(f"{cust.first_name} {cust.last_name or ''}".strip())
            uname = f"@{html.escape(cust.username)}" if cust.username else "<i>none</i>"
            rej_date = (
                cust.rejected_at.strftime("%Y-%m-%d %H:%M UTC")
                if cust.rejected_at
                else (cust.updated_at.strftime("%Y-%m-%d %H:%M UTC") if cust.updated_at else "N/A")
            )
            reason = (
                html.escape(cust.rejection_reason)
                if cust.rejection_reason
                else t("reason_not_specified", lang)
            )
            card = t(
                "rejected_card",
                lang,
                id=cust.id,
                name=full_name,
                username=uname,
                telegram_id=cust.telegram_id,
                rejected_at=rej_date,
                reason=reason,
            )
            cards_text.append(card)

        # Inline buttons: Reapprove button for each customer on page
        inline_buttons: List[List[InlineKeyboardButton]] = []
        for cust in page_customers:
            btn_label = t("btn_reapprove", lang, id=cust.id)
            inline_buttons.append([
                InlineKeyboardButton(btn_label, callback_data=f"reapprove_cust:{cust.id}")
            ])

        nav_row: List[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(t("btn_prev", lang), callback_data=f"admin_rejected_page:{page - 1}")
            )
        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton(t("btn_next", lang), callback_data=f"admin_rejected_page:{page + 1}")
            )
        if nav_row:
            inline_buttons.append(nav_row)

        inline_buttons.append([
            InlineKeyboardButton(t("btn_back_admin", lang), callback_data="admin_menu_back")
        ])

        reply_markup = InlineKeyboardMarkup(inline_buttons)
        full_text = "\n\n".join(cards_text)

        if edit_message and update.callback_query:
            await update.callback_query.edit_message_text(
                full_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
            )
        elif update.effective_message:
            await update.effective_message.reply_text(
                full_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
            )


async def rejected_customers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command / button handler to list rejected customers with pagination."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Access denied: This command is restricted to library owners.")
        return

    page = 1
    if context.args and context.args[0].isdigit():
        page = max(1, int(context.args[0]))

    await _render_rejected_customers_page(update, context, user_id=user_id, page=page)


async def rejected_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pagination callback for rejected customers list."""
    query = update.callback_query
    if not query or not query.data:
        return

    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    _, _, page_str = query.data.partition(":")
    page = int(page_str) if page_str.isdigit() else 1
    await query.answer()
    await _render_rejected_customers_page(update, context, user_id=user_id, page=page, edit_message=True)


async def reapprove_customer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback to reapprove a rejected customer account."""
    query = update.callback_query
    if not query or not query.data:
        return

    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    _, _, id_str = query.data.partition(":")
    if not id_str.isdigit():
        await query.answer("Invalid callback data.")
        return

    customer_id = int(id_str)
    cust_telegram_id = None
    cust_name = None
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        try:
            cust = reapprove_customer(session, customer_id, actor_telegram_id=user_id)
            cust_telegram_id = cust.telegram_id
            cust_name = cust.first_name
            name = html.escape(f"{cust.first_name} {cust.last_name or ''}".strip())
            await query.answer(f"Customer #{cust.id} reapproved!")
            success_text = t("reapproved_success", lang, id=cust.id, name=name)
            await query.edit_message_text(success_text, parse_mode=ParseMode.HTML)
        except CustomerNotFoundError:
            await query.answer("Customer not found.", show_alert=True)
            await query.edit_message_text("❌ Customer record not found.")
            return
        except InvalidCustomerStatusError as exc:
            await query.answer("Customer already processed.", show_alert=False)
            await query.edit_message_text(f"ℹ️ {html.escape(str(exc))}")
            return

    if cust_telegram_id:
        await notify_customer(
            bot=context.bot,
            customer_telegram_id=cust_telegram_id,
            event_key="notify_customer_approved",
            name=cust_name or "Reader",
        )



async def admin_menu_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to admin menu from inline record list."""
    query = update.callback_query
    if not query:
        return

    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    await query.answer()
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    name = html.escape(query.from_user.first_name or "Admin")
    text = t("welcome_admin", lang, name=name)
    keyboard = get_admin_reply_keyboard(lang)
    if query.message:
        await query.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# ==============================================================================
# Owner Handlers: Book Cataloguing & Stock Receiving (Guided & CLI)
# ==============================================================================


async def start_add_book_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for owner guided add book conversation."""
    if not update.effective_message or not update.effective_user:
        return ConversationHandler.END

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Access denied: This command is restricted to library owners.")
        return ConversationHandler.END

    # Clear prior flow state
    for k in list(context.user_data.keys()):
        if k.startswith("add_book_") or k == "is_existing_book":
            context.user_data.pop(k, None)

    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    await update.effective_message.reply_text(
        t("add_book_step_isbn", lang),
        reply_markup=get_isbn_step_keyboard(lang),
        parse_mode=ParseMode.HTML,
    )
    return ADD_BOOK_ISBN


async def addbook_entry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Smart entry for /addbook: if args with '|' passed, runs legacy CLI; else launches guided flow."""
    if context.args and ("|" in " ".join(context.args) or len(context.args) >= 4):
        await addbook_command(update, context)
        return ConversationHandler.END
    return await start_add_book_flow(update, context)


async def add_book_isbn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: Validate ISBN, check for existing title, or proceed to Title."""
    if not update.effective_message or not update.effective_message.text or not update.effective_user:
        return ADD_BOOK_ISBN

    text = update.effective_message.text.strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_cancel", lang), t("btn_cancel", "en"), t("btn_cancel", "am"), "Cancel", "ሰርዝ", "❌ Cancel", "❌ ሰርዝ"):
        return await add_book_cancel_handler(update, context)

    # Check for Skip button or skip text
    if text in (t("btn_skip", lang), t("btn_skip", "en"), t("btn_skip", "am"), "Skip", "እለፍ", "⏭️ Skip", "⏭️ እለፍ") or text.lower() in ("skip", "null", "none"):
        # The existing database schema enforces books.isbn NOT NULL UNIQUE.
        # Explain the limitation and propose the smallest safe change rather than silently saving fake data.
        await update.effective_message.reply_text(
            t("add_book_isbn_required_note", lang),
            reply_markup=get_isbn_step_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_ISBN

    try:
        canonical_isbn = normalize_isbn(text)
    except InvalidISBNError as exc:
        await update.effective_message.reply_text(
            f"⚠️ <b>Invalid ISBN format:</b> {html.escape(str(exc))}\n\n"
            f"Please enter a valid 10- or 13-digit ISBN (e.g. <code>978-0-306-40615-7</code> or <code>0306406152</code>):",
            reply_markup=get_isbn_step_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_ISBN

    with get_db_session() as session:
        existing = session.query(Book).filter(Book.isbn == canonical_isbn).first()
        if existing:
            avail = sum(1 for c in existing.copies if c.status == BookCopyStatus.ON_SHELF.value)
            context.user_data["add_book_isbn"] = canonical_isbn
            context.user_data["add_book_title"] = existing.title
            context.user_data["add_book_author"] = existing.author
            context.user_data["add_book_price"] = str(existing.rental_price)
            context.user_data["add_book_category"] = existing.category
            context.user_data["add_book_pages"] = existing.page_count
            context.user_data["add_book_desc"] = existing.description
            context.user_data["is_existing_book"] = True

            msg = t(
                "add_book_isbn_exists",
                lang,
                title=html.escape(existing.title),
                author=html.escape(existing.author),
                available=avail,
                total=len(existing.copies),
            )
            await update.effective_message.reply_text(
                msg,
                reply_markup=get_existing_book_action_keyboard(lang),
                parse_mode=ParseMode.HTML,
            )
            return ADD_BOOK_COPIES

    context.user_data["add_book_isbn"] = canonical_isbn
    context.user_data["is_existing_book"] = False

    await update.effective_message.reply_text(
        t("add_book_step_title", lang),
        reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
        parse_mode=ParseMode.HTML,
    )
    return ADD_BOOK_TITLE


async def add_book_title_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2: Collect book title."""
    if not update.effective_message or not update.effective_message.text or not update.effective_user:
        return ADD_BOOK_TITLE

    text = update.effective_message.text.strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_cancel", lang), t("btn_cancel", "en"), t("btn_cancel", "am"), "Cancel", "ሰርዝ", "❌ Cancel", "❌ ሰርዝ"):
        return await add_book_cancel_handler(update, context)

    if text in (t("btn_back", lang), t("btn_back", "en"), t("btn_back", "am"), "Back", "ወደኋላ", "⬅️ Back", "⬅️ ወደኋላ"):
        await update.effective_message.reply_text(
            t("add_book_step_isbn", lang),
            reply_markup=get_isbn_step_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_ISBN

    if not text:
        await update.effective_message.reply_text("⚠️ Title cannot be empty. Please enter the book title:")
        return ADD_BOOK_TITLE

    context.user_data["add_book_title"] = text
    await update.effective_message.reply_text(
        t("add_book_step_author", lang),
        reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
        parse_mode=ParseMode.HTML,
    )
    return ADD_BOOK_AUTHOR


async def add_book_author_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 3: Collect book author."""
    if not update.effective_message or not update.effective_message.text or not update.effective_user:
        return ADD_BOOK_AUTHOR

    text = update.effective_message.text.strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_cancel", lang), t("btn_cancel", "en"), t("btn_cancel", "am"), "Cancel", "ሰርዝ", "❌ Cancel", "❌ ሰርዝ"):
        return await add_book_cancel_handler(update, context)

    if text in (t("btn_back", lang), t("btn_back", "en"), t("btn_back", "am"), "Back", "ወደኋላ", "⬅️ Back", "⬅️ ወደኋላ"):
        await update.effective_message.reply_text(
            t("add_book_step_title", lang),
            reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_TITLE

    if text in (t("btn_skip", lang), t("btn_skip", "en"), t("btn_skip", "am"), "Skip", "እለፍ", "⏭️ Skip", "⏭️ እለፍ") or text.lower() in ("null", "none"):
        author_err = (
            "⚠️ <b>Author is Mandatory:</b> The database schema enforces a mandatory author for all catalogued titles (<code>author NOT NULL</code>). Please enter the author name:"
            if lang == "en"
            else "⚠️ <b>ደራሲ የግድ ያስፈልጋል፦</b> በካታሎጉ ውስጥ ለእያንዳንዱ መጽሐፍ የደራሲ ስም መመዝገብ አለበት (<code>author NOT NULL</code>)። እባክዎን የደራሲውን ስም ያስገቡ፦"
        )
        await update.effective_message.reply_text(
            author_err,
            reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_AUTHOR

    if not text:
        await update.effective_message.reply_text("⚠️ Author cannot be empty. Please enter the author name:")
        return ADD_BOOK_AUTHOR

    context.user_data["add_book_author"] = text
    await update.effective_message.reply_text(
        t("add_book_step_price", lang),
        reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
        parse_mode=ParseMode.HTML,
    )
    return ADD_BOOK_PRICE


async def add_book_price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 4: Collect rental fee."""
    if not update.effective_message or not update.effective_message.text or not update.effective_user:
        return ADD_BOOK_PRICE

    text = update.effective_message.text.strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_cancel", lang), t("btn_cancel", "en"), t("btn_cancel", "am"), "Cancel", "ሰርዝ", "❌ Cancel", "❌ ሰርዝ"):
        return await add_book_cancel_handler(update, context)

    if text in (t("btn_back", lang), t("btn_back", "en"), t("btn_back", "am"), "Back", "ወደኋላ", "⬅️ Back", "⬅️ ወደኋላ"):
        await update.effective_message.reply_text(
            t("add_book_step_author", lang),
            reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_AUTHOR

    try:
        dec_price = Decimal(text)
        if dec_price <= Decimal("0.00"):
            raise ValueError()
    except (InvalidOperation, ValueError):
        await update.effective_message.reply_text(
            "⚠️ Invalid rental fee. Please enter a positive number in ETB (e.g. <code>15.00</code> or <code>20</code>):",
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_PRICE

    context.user_data["add_book_price"] = str(dec_price)
    await update.effective_message.reply_text(
        t("add_book_step_metadata", lang),
        reply_markup=get_step_nav_keyboard(lang, allow_skip=True),
        parse_mode=ParseMode.HTML,
    )
    return ADD_BOOK_METADATA


async def add_book_metadata_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 5: Collect optional category, page count, and description."""
    if not update.effective_message or not update.effective_message.text or not update.effective_user:
        return ADD_BOOK_METADATA

    text = update.effective_message.text.strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_cancel", lang), t("btn_cancel", "en"), t("btn_cancel", "am"), "Cancel", "ሰርዝ", "❌ Cancel", "❌ ሰርዝ"):
        return await add_book_cancel_handler(update, context)

    if text in (t("btn_back", lang), t("btn_back", "en"), t("btn_back", "am"), "Back", "ወደኋላ", "⬅️ Back", "⬅️ ወደኋላ"):
        await update.effective_message.reply_text(
            t("add_book_step_price", lang),
            reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_PRICE

    if text in (t("btn_skip", lang), t("btn_skip", "en"), t("btn_skip", "am"), "Skip", "እለፍ", "⏭️ Skip", "⏭️ እለፍ"):
        context.user_data["add_book_category"] = None
        context.user_data["add_book_pages"] = None
        context.user_data["add_book_desc"] = None
    else:
        parts = [p.strip() for p in text.split("|")]
        raw_cat = parts[0] if parts and parts[0] else None
        if raw_cat and raw_cat.strip().lower() in ("null", "none", "n/a", "-"):
            raw_cat = None
        context.user_data["add_book_category"] = raw_cat

        raw_pages = None
        if len(parts) > 1 and parts[1].strip().isdigit():
            raw_pages = int(parts[1].strip())
        context.user_data["add_book_pages"] = raw_pages

        raw_desc = parts[2] if len(parts) > 2 and parts[2] else None
        if raw_desc and raw_desc.strip().lower() in ("null", "none", "n/a", "-"):
            raw_desc = None
        context.user_data["add_book_desc"] = raw_desc

    await update.effective_message.reply_text(
        t("add_book_step_copies", lang),
        reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
        parse_mode=ParseMode.HTML,
    )
    return ADD_BOOK_COPIES


async def add_book_copies_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 6: Collect physical copy quantity and show summary."""
    if not update.effective_message or not update.effective_message.text or not update.effective_user:
        return ADD_BOOK_COPIES

    text = update.effective_message.text.strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_cancel", lang), t("btn_cancel", "en"), t("btn_cancel", "am"), "Cancel", "ሰርዝ", "❌ Cancel", "❌ ሰርዝ"):
        return await add_book_cancel_handler(update, context)

    if text in (t("btn_back", lang), t("btn_back", "en"), t("btn_back", "am"), "Back", "ወደኋላ", "⬅️ Back", "⬅️ ወደኋላ"):
        if context.user_data.get("is_existing_book"):
            await update.effective_message.reply_text(
                t("add_book_step_isbn", lang),
                reply_markup=get_isbn_step_keyboard(lang),
                parse_mode=ParseMode.HTML,
            )
            return ADD_BOOK_ISBN
        await update.effective_message.reply_text(
            t("add_book_step_metadata", lang),
            reply_markup=get_step_nav_keyboard(lang, allow_skip=True),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_METADATA

    if text in (t("btn_add_copies", lang), t("btn_add_copies", "en"), t("btn_add_copies", "am"), "➕ Add Physical Copies", "➕ ቅጂዎችን ጨምር"):
        await update.effective_message.reply_text(
            "📦 Please enter the quantity of physical copies received (e.g. <code>2</code> or <code>5</code>):",
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_COPIES

    try:
        qty = int(text)
        if qty < 1:
            raise ValueError()
    except ValueError:
        await update.effective_message.reply_text(
            "⚠️ Quantity must be a positive integer of at least 1 (e.g. <code>1</code>, <code>3</code>, <code>5</code>):",
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_COPIES

    context.user_data["add_book_quantity"] = qty

    summary = t(
        "add_book_confirm_summary",
        lang,
        title=html.escape(context.user_data.get("add_book_title", "")),
        author=html.escape(context.user_data.get("add_book_author", "")),
        isbn=context.user_data.get("add_book_isbn", ""),
        price=context.user_data.get("add_book_price", "0.00"),
        quantity=qty,
        category=html.escape(context.user_data.get("add_book_category") or "General"),
        page_count=context.user_data.get("add_book_pages") or "N/A",
        description=html.escape(context.user_data.get("add_book_desc") or "None"),
    )
    await update.effective_message.reply_text(
        summary,
        reply_markup=get_add_book_confirm_keyboard(lang),
        parse_mode=ParseMode.HTML,
    )
    return ADD_BOOK_CONFIRM


async def add_book_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 7: Atomically catalogue book and receive stock copies."""
    if not update.effective_message or not update.effective_message.text or not update.effective_user:
        return ADD_BOOK_CONFIRM

    text = update.effective_message.text.strip()
    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    if text in (t("btn_cancel", lang), t("btn_cancel", "en"), t("btn_cancel", "am"), "Cancel", "ሰርዝ", "❌ Cancel", "❌ ሰርዝ"):
        return await add_book_cancel_handler(update, context)

    if text in (t("btn_back", lang), t("btn_back", "en"), t("btn_back", "am"), "Back", "ወደኋላ", "⬅️ Back", "⬅️ ወደኋላ"):
        await update.effective_message.reply_text(
            t("add_book_step_copies", lang),
            reply_markup=get_step_nav_keyboard(lang, allow_skip=False),
            parse_mode=ParseMode.HTML,
        )
        return ADD_BOOK_COPIES

    if text in (
        t("btn_confirm_save", lang),
        t("btn_confirm_save", "en"),
        t("btn_confirm_save", "am"),
        "Confirm & Save",
        "አረጋግጥና አስቀምጥ",
        "✅ Confirm & Save",
        "✅ አረጋግጥና አስቀምጥ",
    ):
        isbn = context.user_data.get("add_book_isbn")
        if not isbn:
            await update.effective_message.reply_text(
                "ℹ️ This book submission has already been processed.",
                reply_markup=get_admin_reply_keyboard(lang),
            )
            return ConversationHandler.END

        qty = context.user_data.get("add_book_quantity", 1)
        title = context.user_data.get("add_book_title")
        author = context.user_data.get("add_book_author")
        price_str = context.user_data.get("add_book_price")
        page_count = context.user_data.get("add_book_pages")
        category = context.user_data.get("add_book_category")
        description = context.user_data.get("add_book_desc")

        with get_db_session() as session:
            try:
                book, copies = record_received_copies(
                    session=session,
                    isbn=isbn,
                    quantity=qty,
                    title=title,
                    author=author,
                    rental_price=Decimal(price_str) if price_str else None,
                    page_count=page_count,
                    category=category,
                    description=description,
                    actor=f"OWNER:{user_id}",
                )
                avail = sum(1 for c in book.copies if c.status == BookCopyStatus.ON_SHELF.value)
                barcodes = ", ".join(f"<code>{c.barcode}</code>" for c in copies[:5])
                if len(copies) > 5:
                    barcodes += f" (+{len(copies) - 5} more)"

                resp = t(
                    "add_book_saved_success",
                    lang,
                    title=html.escape(book.title),
                    author=html.escape(book.author),
                    isbn=book.isbn,
                    price=str(book.rental_price),
                    quantity=len(copies),
                    available=avail,
                    barcodes=barcodes,
                )
                await update.effective_message.reply_text(
                    resp,
                    reply_markup=get_admin_reply_keyboard(lang),
                    parse_mode=ParseMode.HTML,
                )
                await announce_new_stock(bot=context.bot, title=book.title, author=book.author)
                await notify_admins(
                    bot=context.bot,
                    event_key="notify_book_created_admin",
                    title=book.title,
                    author=book.author,
                    isbn=book.isbn,
                )
            except Exception as exc:
                logger.error("Failed to add book and stock: %s", exc, exc_info=True)
                await update.effective_message.reply_text(
                    f"❌ <b>Error saving book:</b> {html.escape(str(exc))}",
                    reply_markup=get_admin_reply_keyboard(lang),
                    parse_mode=ParseMode.HTML,
                )

        # Clear state
        for k in list(context.user_data.keys()):
            if k.startswith("add_book_") or k == "is_existing_book":
                context.user_data.pop(k, None)
        return ConversationHandler.END

    await update.effective_message.reply_text(
        "Please press <b>Confirm & Save</b> to complete, or <b>Cancel</b>.",
        reply_markup=get_add_book_confirm_keyboard(lang),
        parse_mode=ParseMode.HTML,
    )
    return ADD_BOOK_CONFIRM


async def add_book_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel add book conversation and restore owner keyboard."""
    user_id = update.effective_user.id if update.effective_user else 0
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

    for k in list(context.user_data.keys()):
        if k.startswith("add_book_") or k == "is_existing_book":
            context.user_data.pop(k, None)

    if update.effective_message:
        await update.effective_message.reply_text(
            t("add_book_cancelled", lang),
            reply_markup=get_admin_reply_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )
    return ConversationHandler.END


async def addbook_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to catalogue a new book title.

    Syntax: /addbook <isbn> | <title> | <author> | <price> [| <pages> | <category> | <description>]
    """
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Access denied: This command is restricted to library owners.")
        return

    raw_args = " ".join(context.args) if context.args else ""
    parts = [p.strip() for p in raw_args.split("|")]

    if len(parts) < 4:
        usage_text = (
            "📖 <b>Add Book Usage:</b>\n"
            "<code>/addbook &lt;isbn&gt; | &lt;title&gt; | &lt;author&gt; | &lt;price&gt; [| pages | category | desc]</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/addbook 978-0-306-40615-7 | Principles of Neural Science | Eric Kandel | 15.00 | 1414 | Science | Key neurobiology text</code>"
        )
        await update.effective_message.reply_text(usage_text, parse_mode=ParseMode.HTML)
        return

    isbn, title, author, price_str = parts[:4]
    page_count = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
    category = parts[5] if len(parts) > 5 and parts[5] else None
    description = parts[6] if len(parts) > 6 and parts[6] else None

    with get_db_session() as session:
        try:
            book = create_book(
                session=session,
                isbn=isbn,
                title=title,
                author=author,
                rental_price=price_str,
                page_count=page_count,
                category=category,
                description=description,
                actor_telegram_id=user_id,
            )

            response = (
                f"✅ <b>Book Catalogued Successfully!</b>\n\n"
                f"• Title: <b>{html.escape(book.title)}</b>\n"
                f"• Author: <b>{html.escape(book.author)}</b>\n"
                f"• Canonical ISBN: <code>{book.isbn}</code>\n"
                f"• Rental Price: <b>${book.rental_price}</b>\n"
                f"• Category: {html.escape(book.category or 'General')}\n"
                f"• Page Count: {book.page_count or 'N/A'}\n\n"
                f"<i>To receive physical stock for this book, run:</i>\n"
                f"<code>/receive {book.isbn} &lt;quantity&gt;</code>"
            )
            await update.effective_message.reply_text(response, parse_mode=ParseMode.HTML)
            await notify_admins(
                bot=context.bot,
                event_key="notify_book_created_admin",
                title=book.title,
                author=book.author,
                isbn=book.isbn,
            )

        except InvalidISBNError as exc:
            await update.effective_message.reply_text(f"❌ <b>Invalid ISBN:</b> {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
        except (ValueError, TypeError, InvalidOperation) as exc:
            await update.effective_message.reply_text(f"⚠️ <b>Error:</b> {html.escape(str(exc))}", parse_mode=ParseMode.HTML)


async def receive_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to receive newly arrived physical copies for an existing title.

    Syntax: /receive <isbn> <quantity>
    """
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Access denied: This command is restricted to library owners.")
        return

    if not context.args or len(context.args) < 2 or not context.args[1].isdigit():
        usage = (
            "📦 <b>Receive Stock Usage:</b>\n"
            "<code>/receive &lt;isbn&gt; &lt;quantity&gt;</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/receive 978-0-306-40615-7 5</code>"
        )
        await update.effective_message.reply_text(usage, parse_mode=ParseMode.HTML)
        return

    isbn = context.args[0]
    quantity = int(context.args[1])
    if quantity < 1:
        await update.effective_message.reply_text("⚠️ Quantity must be at least 1.")
        return

    with get_db_session() as session:
        try:
            book, copies = receive_stock_for_isbn(
                session=session,
                isbn=isbn,
                quantity=quantity,
                actor_telegram_id=user_id,
            )

            barcodes = ", ".join(f"<code>{c.barcode}</code>" for c in copies[:5])
            if len(copies) > 5:
                barcodes += f" (+{len(copies) - 5} more)"

            resp = (
                f"📦 <b>Stock Received Successfully!</b>\n\n"
                f"• Title: <b>{html.escape(book.title)}</b>\n"
                f"• ISBN: <code>{book.isbn}</code>\n"
                f"• Copies Added: <b>{len(copies)}</b>\n"
                f"• Generated Barcodes: {barcodes}\n"
                f"• Status of New Copies: <b>ON_SHELF</b>\n"
                f"• Total Physical Copies for Title: <b>{len(book.copies)}</b>"
            )
            await update.effective_message.reply_text(resp, parse_mode=ParseMode.HTML)
            await announce_new_stock(
                bot=context.bot,
                title=book.title,
                author=book.author,
            )

        except MissingBookDetailsError as exc:
            await update.effective_message.reply_text(
                f"❌ {html.escape(str(exc))}\nUse <code>/addbook</code> to register this title first.",
                parse_mode=ParseMode.HTML,
            )
        except InvalidISBNError as exc:
            await update.effective_message.reply_text(f"❌ <b>Invalid ISBN:</b> {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
        except ValueError as exc:
            await update.effective_message.reply_text(f"⚠️ {html.escape(str(exc))}")


async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to view global inventory summary or inspect individual title copies.

    Syntax: /inventory [isbn_or_id]
    """
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Access denied: This command is restricted to library owners.")
        return

    with get_db_session() as session:
        if not context.args:
            # Overall inventory summary
            summary = get_overall_inventory_summary(session)
            counts = summary["counts_by_status"]

            msg = (
                "📊 <b>Library Inventory Summary</b>\n\n"
                f"• Total Catalogued Titles: <b>{summary['total_titles']}</b>\n"
                f"• Total Physical Copies: <b>{summary['total_copies']}</b>\n\n"
                f"<b>Physical Copies by Status:</b>\n"
                f"🟢 Available (ON_SHELF): <b>{counts.get(BookCopyStatus.ON_SHELF.value, 0)}</b>\n"
                f"🟡 Reserved: <b>{counts.get(BookCopyStatus.RESERVED.value, 0)}</b>\n"
                f"🔵 Rented: <b>{counts.get(BookCopyStatus.RENTED.value, 0)}</b>\n"
                f"🟠 Overdue: <b>{counts.get(BookCopyStatus.OVERDUE.value, 0)}</b>\n"
                f"🔴 Damaged: <b>{counts.get(BookCopyStatus.DAMAGED.value, 0)}</b>\n"
                f"⚫ Lost: <b>{counts.get(BookCopyStatus.LOST.value, 0)}</b>\n\n"
                "<i>To inspect physical copies for a title, run:</i>\n"
                "<code>/inventory &lt;isbn_or_id&gt;</code>"
            )
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)
            return

        # Specific book inspection
        identifier = context.args[0]
        details = get_book_inventory_details(session, identifier)
        if details is None:
            await update.effective_message.reply_text(f"❌ Book '{identifier}' not found in catalogue.")
            return

        counts = details["status_counts"]
        copies_text = ""
        for c in details["copies"][:15]:
            notes = f" — <i>{html.escape(c['condition_notes'])}</i>" if c.get("condition_notes") else ""
            copies_text += f"\n• Copy #{c['copy_number']} (<code>{c['barcode']}</code>): <b>{c['status']}</b>{notes}"

        if len(details["copies"]) > 15:
            copies_text += f"\n<i>...and {len(details['copies']) - 15} more copies</i>"

        msg = (
            f"📖 <b>{html.escape(details['title'])}</b> by {html.escape(details['author'])}\n"
            f"• ISBN: <code>{details['isbn']}</code>\n"
            f"• Rental Price: ${details['rental_price']}\n"
            f"• Category: {html.escape(details['category'] or 'General')}\n\n"
            f"<b>Inventory Breakdown:</b>\n"
            f"Available: <b>{counts.get(BookCopyStatus.ON_SHELF.value, 0)}</b> | "
            f"Reserved: <b>{counts.get(BookCopyStatus.RESERVED.value, 0)}</b> | "
            f"Rented: <b>{counts.get(BookCopyStatus.RENTED.value, 0)}</b> | "
            f"Overdue: <b>{counts.get(BookCopyStatus.OVERDUE.value, 0)}</b> | "
            f"Damaged: <b>{counts.get(BookCopyStatus.DAMAGED.value, 0)}</b> | "
            f"Lost: <b>{counts.get(BookCopyStatus.LOST.value, 0)}</b>\n\n"
            f"<b>Physical Copies ({details['total_copies']}):</b>{copies_text}"
        )
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)


# ==============================================================================
# Customer Handlers: Book Search & Catalog Browsing
# ==============================================================================


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Customer command to search catalogue books by title, author, category, or ISBN.

    Restricted strictly to APPROVED customers and owners. Provides interactive search options when called without args.
    """
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id

    # Authorization verification
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        if not is_owner(user_id):
            customer = get_customer_by_telegram_id(session, user_id)
            if customer is None:
                await update.effective_message.reply_text("Please register first by typing /start.")
                return
            if customer.status != CustomerStatus.APPROVED.value:
                await update.effective_message.reply_text(
                    f"⏳ Your account status is <b>{customer.status}</b>. "
                    f"You must be an <b>APPROVED</b> customer to search the library catalogue.",
                    parse_mode=ParseMode.HTML,
                )
                return

        query = " ".join(context.args).strip() if context.args else ""
        if not query:
            prompt = (
                "🔍 <b>Find a Book in the Catalogue:</b>\n\n"
                "Choose how you want to search or browse our books:\n"
                "• Search by title, author, category, or ISBN\n"
                "• Browse all currently active titles\n\n"
                "<i>You can also type:</i> <code>/search &lt;query&gt;</code>"
            ) if lang == "en" else (
                "🔍 <b>በካታሎግ ውስጥ መጽሐፍ ይፈልጉ፦</b>\n\n"
                "መጻሕፍትን ለመፈለግ ወይም ለማሰስ ከታች ካሉት አማራጮች አንዱን ይምረጡ፦\n"
                "• በርዕስ፣ በደራሲ፣ በምድብ ወይም በISBN ይፈልጉ\n"
                "• ያሉትን መጻሕፍት በሙሉ ይመልከቱ\n\n"
                "<i>በጽሑፍ መላክም ይችላሉ፦</i> <code>/search &lt;የሚፈልጉት ቃል&gt;</code>"
            )
            await update.effective_message.reply_text(
                prompt,
                reply_markup=get_book_search_menu_keyboard(lang),
                parse_mode=ParseMode.HTML,
            )
            return

        results = search_books(session, query, limit=10)
        if not results:
            await update.effective_message.reply_text(
                f"🔍 No books found matching '<b>{html.escape(query)}</b>'. "
                f"Try searching by another title, author, or category keyword.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📚 Browse All Books" if lang == "en" else "📚 ሁሉንም ተመልከት", callback_data="search_mode:browse"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
            return

        response_lines = [f"📚 <b>Search Results for '{html.escape(query)}' ({len(results)}):</b>\n"]
        buttons = []
        for book in results:
            avail = book["available_copies"]
            stock_indicator = f"🟢 <b>{avail} available</b>" if avail > 0 else "🔴 <i>Out of stock</i>"

            card = (
                f"📖 <b>{html.escape(book['title'])}</b>\n"
                f"• Book ID: <code>{book['id']}</code> (use <code>/rent {book['id']}</code>)\n"
                f"• Author: <b>{html.escape(book['author'])}</b>\n"
                f"• ISBN: <code>{book['isbn']}</code>\n"
                f"• Category: {html.escape(book['category'] or 'General')} | Pages: {book['page_count'] or 'N/A'}\n"
                f"• Rental Fee: <b>${book['rental_price']}</b>\n"
                f"• Physical Copies: {stock_indicator} ({book['total_copies']} total)\n"
            )
            response_lines.append(card)

            short_title = book['title'][:22] + "..." if len(book['title']) > 22 else book['title']
            if avail > 0:
                buttons.append([
                    InlineKeyboardButton(
                        f"📖 Request '{short_title}'" if lang == "en" else f"📖 ተዋስ '{short_title}'",
                        callback_data=f"req_book:{book['id']}",
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        f"🔴 '{short_title}' (Out of Stock)" if lang == "en" else f"🔴 '{short_title}' (አልቋል)",
                        callback_data=f"book_oos:{book['id']}",
                    )
                ])

        kb = InlineKeyboardMarkup(buttons) if buttons else None
        await update.effective_message.reply_text("\n".join(response_lines), reply_markup=kb, parse_mode=ParseMode.HTML)


async def books_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Browse the catalogue (delegates to empty/broad search for approved users)."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        if not is_owner(user_id):
            customer = get_customer_by_telegram_id(session, user_id)
            if customer is None or customer.status != CustomerStatus.APPROVED.value:
                status_str = customer.status if customer else "UNREGISTERED"
                await update.effective_message.reply_text(
                    f"⏳ Your account status is <b>{status_str}</b>. "
                    f"Catalogue access is reserved for <b>APPROVED</b> customers.",
                    parse_mode=ParseMode.HTML,
                )
                return

        # Perform a listing of top titles
        results = search_books(session, query="", limit=10)
        if not results:
            # If query is empty, search_books returns []; do a direct query
            from app.models.book import Book
            books = session.query(Book).order_by(Book.title.asc()).limit(10).all()
            if not books:
                await update.effective_message.reply_text("📚 The library catalogue is currently empty. Check back soon!")
                return
            results = []
            for b in books:
                avail = sum(1 for c in b.copies if c.status == BookCopyStatus.ON_SHELF.value)
                results.append({
                    "id": b.id,
                    "isbn": b.isbn,
                    "title": b.title,
                    "author": b.author,
                    "rental_price": b.rental_price,
                    "page_count": b.page_count,
                    "category": b.category,
                    "available_copies": avail,
                    "total_copies": len(b.copies),
                })

        response_lines = ["📚 <b>Library Catalogue:</b>\n"]
        buttons = []
        for book in results:
            avail = book["available_copies"]
            stock_indicator = f"🟢 <b>{avail} available</b>" if avail > 0 else "🔴 <i>Out of stock</i>"
            card = (
                f"📖 <b>{html.escape(book['title'])}</b> by {html.escape(book['author'])}\n"
                f"• Book ID: <code>{book['id']}</code> (use <code>/rent {book['id']}</code>)\n"
                f"• ISBN: <code>{book['isbn']}</code> | Fee: <b>${book['rental_price']}</b>\n"
                f"• Stock: {stock_indicator} ({book['total_copies']} total)\n"
            )
            response_lines.append(card)

            short_title = book['title'][:22] + "..." if len(book['title']) > 22 else book['title']
            if avail > 0:
                buttons.append([
                    InlineKeyboardButton(
                        f"📖 Request '{short_title}'" if lang == "en" else f"📖 ተዋስ '{short_title}'",
                        callback_data=f"req_book:{book['id']}",
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        f"🔴 '{short_title}' (Out of Stock)" if lang == "en" else f"🔴 '{short_title}' (አልቋል)",
                        callback_data=f"book_oos:{book['id']}",
                    )
                ])

        response_lines.append("\n<i>Use /search &lt;query&gt; to search by title, author, category, or ISBN.</i>")
        kb = InlineKeyboardMarkup(buttons) if buttons else None
        await update.effective_message.reply_text("\n".join(response_lines), reply_markup=kb, parse_mode=ParseMode.HTML)


async def search_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query handler for customer search mode selection."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    user_id = query.from_user.id
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        if not is_owner(user_id):
            customer = get_customer_by_telegram_id(session, user_id)
            if not customer or not customer.is_approved:
                status_str = customer.status if customer else "UNREGISTERED"
                await query.answer(f"Account status: {status_str}. Approval required.", show_alert=True)
                return

    _, _, mode = query.data.partition(":")
    if mode == "browse":
        await books_command(update, context)
        return

    context.user_data["awaiting_search_mode"] = mode
    labels = {
        "title": "title or keyword" if lang == "en" else "ርዕስ ወይም ቁልፍ ቃል",
        "author": "author name" if lang == "en" else "የደራሲ ስም",
        "category": "category / genre" if lang == "en" else "ምድብ",
    }
    lbl = labels.get(mode, "query")
    prompt = (
        f"🔎 <b>Search by {lbl}:</b>\n\n"
        f"Please type what you are looking for (or tap a menu button):"
    ) if lang == "en" else (
        f"🔎 <b>በ{lbl} ፈልግ፦</b>\n\n"
        f"እባክዎን የሚፈልጉትን ይተይቡ፦"
    )
    if query.message:
        await query.message.reply_text(prompt, parse_mode=ParseMode.HTML)


async def book_request_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Customer clicked 'Request This Book' on an inline book card."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    user_id = query.from_user.id
    _, _, id_str = query.data.partition(":")
    if not id_str.isdigit():
        return
    book_id = int(id_str)

    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        customer = get_customer_by_telegram_id(session, user_id)
        if not customer:
            await query.answer("Please register first by typing /start", show_alert=True)
            return
        if not customer.is_approved:
            await query.answer(f"Account status is '{customer.status}'. Must be APPROVED to request rentals.", show_alert=True)
            return

        book = session.get(Book, book_id)
        if not book:
            await query.answer("Book not found in catalogue.", show_alert=True)
            return

        avail = sum(1 for c in book.copies if c.status == BookCopyStatus.ON_SHELF.value)
        if avail < 1:
            await query.answer("Sorry, all copies are currently rented or reserved.", show_alert=True)
            return

        prompt = (
            f"📖 <b>Request to Rent:</b> <i>{html.escape(book.title)}</i>\n\n"
            f"• Author: <b>{html.escape(book.author)}</b>\n"
            f"• Rental Fee: <b>{book.rental_price} ETB</b> (for 10 calendar days)\n"
            f"• Available Copies: 🟢 {avail} on shelf\n\n"
            f"Please select how you would like to provide collateral/guarantee:"
        ) if lang == "en" else (
            f"📖 <b>የመዋስ ጥያቄ፦</b> <i>{html.escape(book.title)}</i>\n\n"
            f"• ደራሲ፦ <b>{html.escape(book.author)}</b>\n"
            f"• የኪራይ ዋጋ፦ <b>{book.rental_price} ብር</b> (ለ10 ቀናት)\n"
            f"• ዝግጁ የሆኑ ቅጂዎች፦ 🟢 {avail} በመደርደሪያ ላይ\n\n"
            f"እባክዎን የዋስትና አይነትዎን ይምረጡ፦"
        )
        if query.message:
            await query.message.reply_text(
                prompt,
                reply_markup=get_rental_collateral_keyboard(lang, book.id),
                parse_mode=ParseMode.HTML,
            )


async def book_request_collateral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Customer selected Cash or Guarantee collateral; display review & confirm."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    user_id = query.from_user.id
    parts = query.data.split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        return
    collat_type = parts[1]
    book_id = int(parts[2])

    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        book = session.get(Book, book_id)
        if not book:
            await query.answer("Book not found.", show_alert=True)
            return

        collat_label = (
            "Monetary Collateral (verified upon pickup)"
            if collat_type == "cash"
            else "National ID / Document Guarantee on file"
        ) if lang == "en" else (
            "የጥሬ ገንዘብ ዋስትና (በሚወስዱበት ጊዜ የሚረጋገጥ)"
            if collat_type == "cash"
            else "የብሔራዊ መታወቂያ/የሰነድ ዋስትና"
        )

        confirm_text = (
            f"📋 <b>Review Rental Request:</b>\n\n"
            f"• <b>Book:</b> <i>{html.escape(book.title)}</i>\n"
            f"• <b>Author:</b> {html.escape(book.author)}\n"
            f"• <b>Rental Fee:</b> <b>{book.rental_price} ETB</b>\n"
            f"• <b>Collateral:</b> {collat_label}\n"
            f"• <b>Rental Period:</b> 10 calendar days\n\n"
            f"ℹ️ <i>Next Step:</i> Tap <b>Submit Rental Request</b> below. The library owner will review and reserve an available physical copy for you."
        ) if lang == "en" else (
            f"📋 <b>የኪራይ ጥያቄ ማጠቃለያ፦</b>\n\n"
            f"• <b>መጽሐፍ፦</b> <i>{html.escape(book.title)}</i>\n"
            f"• <b>ደራሲ፦</b> {html.escape(book.author)}\n"
            f"• <b>የኪራይ ዋጋ፦</b> <b>{book.rental_price} ብር</b>\n"
            f"• <b>ዋስትና፦</b> {collat_label}\n"
            f"• <b>የኪራይ ርዝማኔ፦</b> 10 የቀን መቁጠሪያ ቀናት\n\n"
            f"ℹ️ <i>ቀጣይ እርምጃ፦</i> ከታች <b>የኪራይ ጥያቄውን ላክ</b> የሚለውን ይጫኑ። የመጽሐፍ አስተዳዳሪው መርምሮ ቅጂ ይይዝልዎታል።"
        )

        if query.message:
            await query.message.reply_text(
                confirm_text,
                reply_markup=get_rental_confirm_keyboard(lang, book.id, collat_type),
                parse_mode=ParseMode.HTML,
            )


async def book_request_submit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Customer confirmed rental submission."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    user_id = query.from_user.id
    parts = query.data.split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        return
    collat_type = parts[1]
    book_id = int(parts[2])

    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        customer = get_customer_by_telegram_id(session, user_id)
        if not customer or not customer.is_approved:
            await query.answer("Approval required.", show_alert=True)
            return

        ctype = CollateralType.GUARANTEE if collat_type == "guarantee" else CollateralType.MONETARY
        g_note = f"National ID on file ({customer.phone_number})" if collat_type == "guarantee" else None

        try:
            req = submit_rental_request(
                session=session,
                customer_id=customer.id,
                book_id=book_id,
                collateral_type=ctype,
                guarantee_details=g_note,
            )
            book_title = req.book.title
            fee_str = str(req.rental_fee)
            req_id = req.id
            cust_name = f"{customer.first_name} {customer.last_name or ''}".strip()
        except CopyNotAvailableError:
            await query.answer("Sorry, all copies were just allocated to another request.", show_alert=True)
            return
        except Exception as exc:
            await query.answer(f"Error: {exc}", show_alert=True)
            return

    success_msg = (
        f"🎉 <b>Rental Request Submitted Successfully!</b>\n\n"
        f"• <b>Request ID:</b> <code>#{req_id}</code>\n"
        f"• <b>Book:</b> <i>{html.escape(book_title)}</i>\n"
        f"• <b>Rental Fee:</b> {fee_str} ETB\n"
        f"• <b>Status:</b> <b>SUBMITTED (Awaiting Owner Review)</b>\n\n"
        f"⏳ You will receive a notification here as soon as the library owner reviews your request."
    ) if lang == "en" else (
        f"🎉 <b>የኪራይ ጥያቄዎ በተሳካ ሁኔታ ተልኳል!</b>\n\n"
        f"• <b>የጥያቄ ቁጥር፦</b> <code>#{req_id}</code>\n"
        f"• <b>መጽሐፍ፦</b> <i>{html.escape(book_title)}</i>\n"
        f"• <b>የኪራይ ዋጋ፦</b> {fee_str} ብር\n"
        f"• <b>ሁኔታ፦</b> <b>ተልኳል (በአስተዳዳሪው በመገምገም ላይ)</b>\n\n"
        f"⏳ አስተዳዳሪው እንዳጸደቀው እዚህ መልዕክት ይደርስዎታል።"
    )
    if query.message:
        await query.message.edit_text(success_msg, parse_mode=ParseMode.HTML)

    # Notify owners with interactive action buttons
    settings = get_settings()
    owner_card = (
        f"📥 <b>New Rental Request #{req_id}</b>\n\n"
        f"• <b>Customer:</b> {html.escape(cust_name)} (ID: #{customer.id})\n"
        f"• <b>Book:</b> <i>{html.escape(book_title)}</i> (ID: #{book_id})\n"
        f"• <b>Fee:</b> {fee_str} ETB\n"
        f"• <b>Collateral:</b> {collat_type.upper()}\n"
        f"• <b>Status:</b> <b>SUBMITTED</b>"
    )
    owner_kb = get_owner_request_action_keyboard("en", req_id, "SUBMITTED", False, False, False)
    for oid in settings.owner_telegram_ids:
        try:
            await context.bot.send_message(chat_id=oid, text=owner_card, reply_markup=owner_kb, parse_mode=ParseMode.HTML)
        except Exception as err:
            logger.debug("Failed notifying owner %s: %s", oid, err)


async def book_out_of_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback when clicking out-of-stock badge."""
    query = update.callback_query
    if query:
        await query.answer("⚠️ This title is currently out of stock. Please check back later or choose another title.", show_alert=True)


async def rental_request_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query to cancel rental request flow."""
    query = update.callback_query
    if query:
        await query.answer("Rental request cancelled.")
        if query.message:
            await query.message.edit_text("❌ Rental request selection cancelled.")



# ==============================================================================
# Phase 4 Handlers: Rental Requests, Payments, Guarantees & Physical Checkout
# ==============================================================================


async def rent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Customer command to submit a rental request for an available book title."""
    if not update.effective_message or not update.effective_user:
        return

    user = update.effective_user
    args = context.args or []

    if not args:
        help_msg = (
            "📖 <b>How to Request a Book Rental:</b>\n\n"
            "Usage: <code>/rent &lt;book_id&gt; [guarantee note]</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/rent 1</code> — Standard rental with monetary collateral\n"
            "• <code>/rent 1 National ID #A987654</code> — Rental with non-cash guarantee\n\n"
            "💡 Use /books or /search to find book IDs."
        )
        await update.effective_message.reply_text(help_msg, parse_mode=ParseMode.HTML)
        return

    if not args[0].isdigit():
        await update.effective_message.reply_text(
            "⚠️ Book ID must be an integer. Example: <code>/rent 1</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    book_id = int(args[0])
    guarantee_text = " ".join(args[1:]).strip() if len(args) > 1 else None
    ctype = CollateralType.GUARANTEE if guarantee_text else CollateralType.MONETARY

    with get_db_session() as session:
        customer = get_customer_by_telegram_id(session, user.id)
        if not customer:
            await update.effective_message.reply_text(
                "❌ You must register first by sending /start before requesting books."
            )
            return

        if not customer.is_approved:
            await update.effective_message.reply_text(
                f"⏳ Your account status is <b>{customer.status}</b>. "
                f"Rental requests are restricted to <b>APPROVED</b> customers.",
                parse_mode=ParseMode.HTML,
            )
            return

        try:
            req = submit_rental_request(
                session=session,
                customer_id=customer.id,
                book_id=book_id,
                collateral_type=ctype,
                guarantee_details=guarantee_text,
            )
        except CustomerNotApprovedError as exc:
            await update.effective_message.reply_text(f"⛔ {html.escape(str(exc))}")
            return
        except CopyNotAvailableError as exc:
            await update.effective_message.reply_text(
                f"🔴 <b>Unavailable:</b> {html.escape(str(exc))}",
                parse_mode=ParseMode.HTML,
            )
            return
        except ValueError as exc:
            await update.effective_message.reply_text(f"⚠️ {html.escape(str(exc))}")
            return

        # Prepare customer confirmation
        book_title = req.book.title
        fee_str = str(req.rental_fee)
        collat_info = (
            f"Non-Cash Guarantee (<i>{html.escape(req.guarantee_details or '')}</i>)"
            if req.collateral_type == CollateralType.GUARANTEE.value
            else "Monetary Collateral (verified upon pickup)"
        )

        customer_reply = (
            f"✅ <b>Rental Request Submitted!</b>\n\n"
            f"• <b>Request ID:</b> <code>#{req.id}</code>\n"
            f"• <b>Book:</b> <i>{html.escape(book_title)}</i>\n"
            f"• <b>Rental Fee:</b> ${fee_str}\n"
            f"• <b>Collateral:</b> {collat_info}\n"
            f"• <b>Status:</b> <b>SUBMITTED</b> (Awaiting owner review)\n\n"
            f"⏳ You will be notified once the library owner reviews and approves your request."
        )
        await update.effective_message.reply_text(customer_reply, parse_mode=ParseMode.HTML)

        # Attempt to notify owner(s)
        settings = get_settings()
        owner_notification = (
            f"📥 <b>New Rental Request #{req.id}</b>\n\n"
            f"• <b>Customer:</b> {html.escape(customer.first_name)} {html.escape(customer.last_name or '')} (ID: #{customer.id})\n"
            f"• <b>Book:</b> <i>{html.escape(book_title)}</i> (ID: #{book_id})\n"
            f"• <b>Rental Fee:</b> ${fee_str}\n"
            f"• <b>Collateral Type:</b> {html.escape(req.collateral_type)}\n"
            f"• <b>Status:</b> <b>SUBMITTED</b>\n\n"
            f"Review and approve to reserve an available physical copy, or reject."
        )
        owner_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_req:{req.id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_req:{req.id}"),
            ]
        ])

        for owner_id in settings.owner_telegram_ids:
            try:
                await context.bot.send_message(
                    chat_id=owner_id,
                    text=owner_notification,
                    reply_markup=owner_keyboard,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as notify_err:
                logger.debug("Failed to deliver notification to owner %s: %s", owner_id, notify_err)


async def requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to inspect rental requests."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to bot owners.")
        return

    filter_status = None
    if context.args:
        raw_st = context.args[0].upper()
        if raw_st != "ALL":
            filter_status = raw_st

    with get_db_session() as session:
        requests = get_active_rental_requests(session, status=filter_status)
        if not requests:
            status_desc = f"with status '{filter_status}'" if filter_status else "in active queue"
            await update.effective_message.reply_text(f"📋 No rental requests found {status_desc}.")
            return

        lines = [f"📋 <b>Rental Requests ({len(requests)}):</b>\n"]
        for r in requests[:15]:
            cust_name = f"{r.customer.first_name} {r.customer.last_name or ''}".strip()
            fee_status = "✅ Paid" if r.rental_fee_paid else "⏳ Unpaid"
            collat_status = "✅ Verified" if r.collateral_received else "⏳ Unverified"
            copy_info = f"Copy #{r.copy_id}" if r.copy_id else "None"

            lines.append(
                f"• <b>Request #{r.id}</b> [{r.status}]\n"
                f"  Customer: {html.escape(cust_name)} (ID: #{r.customer_id})\n"
                f"  Book: <i>{html.escape(r.book.title)}</i> | Copy: {copy_info}\n"
                f"  Fee (${r.rental_fee}): {fee_status} | Collateral: {collat_status}\n"
            )

        lines.append(
            "\n<i>Commands: /approvereq &lt;id&gt; | /rejectreq &lt;id&gt; | "
            "/recordpayment &lt;id&gt; ... | /checkout &lt;id&gt;</i>"
        )
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def approvereq_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to approve a rental request and allocate a reserved copy."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to bot owners.")
        return

    args = context.args or []
    if not args or not args[0].isdigit():
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b> <code>/approvereq &lt;request_id&gt; [copy_id]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    request_id = int(args[0])
    copy_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    with get_db_session() as session:
        try:
            req = approve_rental_request(session, request_id, actor_telegram_id=user_id, copy_id=copy_id)
            allocated_copy = req.copy
            barcode = allocated_copy.barcode if allocated_copy else f"#{req.copy_id}"
            cust_tid = req.customer.telegram_id
            book_t = req.book.title
            fee_s = str(req.rental_fee)
            ctype = req.collateral_type
            await update.effective_message.reply_text(
                f"✅ <b>Request #{req.id} APPROVED!</b>\n\n"
                f"• <b>Book:</b> <i>{html.escape(req.book.title)}</i>\n"
                f"• <b>Reserved Copy:</b> <code>{barcode}</code> (Status: RESERVED)\n"
                f"• <b>Customer:</b> {html.escape(req.customer.first_name)} (ID: #{req.customer_id})\n"
                f"• <b>Rental Fee:</b> ${req.rental_fee} (Paid: {req.rental_fee_paid})\n"
                f"• <b>Collateral Received:</b> {req.collateral_received}\n\n"
                f"<b>Next steps before checkout:</b>\n"
                f"1. Verify rental fee payment: <code>/recordpayment {req.id} fee cash {req.rental_fee}</code>\n"
                f"2. Verify collateral / guarantee\n"
                f"3. Hand over book and run: <code>/checkout {req.id}</code>",
                parse_mode=ParseMode.HTML,
            )
            await notify_customer(
                bot=context.bot,
                customer_telegram_id=cust_tid,
                event_key="notify_req_approved_cust",
                id=request_id,
                book_title=book_t,
                rental_fee=fee_s,
                collateral_type=ctype,
            )
        except RentalRequestNotFoundError:
            await update.effective_message.reply_text(f"❌ RentalRequest #{request_id} not found.")
        except InvalidRentalRequestStatusError as exc:
            await update.effective_message.reply_text(f"⚠️ {html.escape(str(exc))}")
        except CopyNotAvailableError as exc:
            await update.effective_message.reply_text(
                f"🔴 <b>Allocation Failed:</b> {html.escape(str(exc))}",
                parse_mode=ParseMode.HTML,
            )
        except UnauthorizedError:
            await update.effective_message.reply_text("⛔ Unauthorized: Owner access required.")


async def rejectreq_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to reject a rental request and release any reserved copy."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to bot owners.")
        return

    args = context.args or []
    if not args or not args[0].isdigit():
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b> <code>/rejectreq &lt;request_id&gt; [reason]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    request_id = int(args[0])
    reason = " ".join(args[1:]).strip() if len(args) > 1 else None

    with get_db_session() as session:
        try:
            req = reject_rental_request(session, request_id, actor_telegram_id=user_id, reason=reason)
            reason_str = f" Reason: <i>{html.escape(req.rejection_reason)}</i>" if req.rejection_reason else ""
            cust_tid = req.customer.telegram_id
            book_t = req.book.title
            rej_reason = req.rejection_reason
            await update.effective_message.reply_text(
                f"❌ <b>Request #{req.id} REJECTED.</b>{reason_str}\n"
                f"Any allocated physical copy has been released back to ON_SHELF.",
                parse_mode=ParseMode.HTML,
            )
            reason_line = f"Reason: {rej_reason}" if rej_reason else ""
            await notify_customer(
                bot=context.bot,
                customer_telegram_id=cust_tid,
                event_key="notify_req_rejected_cust",
                id=request_id,
                book_title=book_t,
                reason_line=reason_line,
            )
        except RentalRequestNotFoundError:
            await update.effective_message.reply_text(f"❌ RentalRequest #{request_id} not found.")
        except InvalidRentalRequestStatusError as exc:
            await update.effective_message.reply_text(f"⚠️ {html.escape(str(exc))}")
        except UnauthorizedError:
            await update.effective_message.reply_text("⛔ Unauthorized: Owner access required.")


async def recordpayment_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to record manual verification of cash or bank transfer payment."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to bot owners.")
        return

    args = context.args or []
    if len(args) < 4 or not args[0].isdigit():
        usage_msg = (
            "⚠️ <b>Usage:</b>\n"
            "<code>/recordpayment &lt;request_id&gt; &lt;fee|collateral&gt; &lt;cash|bank&gt; &lt;amount&gt; [reference]</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/recordpayment 1 fee cash 5.00 Paid at front desk</code>\n"
            "• <code>/recordpayment 1 collateral bank 50.00 Ref#TX99281</code>"
        )
        await update.effective_message.reply_text(usage_msg, parse_mode=ParseMode.HTML)
        return

    request_id = int(args[0])
    raw_type = args[1].lower()
    raw_method = args[2].lower()
    raw_amount = args[3]
    ref_note = " ".join(args[4:]).strip() if len(args) > 4 else None

    # Map payment type
    if raw_type in ("fee", "rental_fee"):
        ptype = PaymentType.RENTAL_FEE
    elif raw_type in ("collateral", "collateral_deposit", "deposit"):
        ptype = PaymentType.COLLATERAL_DEPOSIT
    else:
        await update.effective_message.reply_text("⚠️ Invalid payment type. Must be 'fee' or 'collateral'.")
        return

    # Map payment method
    if raw_method in ("cash",):
        pmethod = PaymentMethod.CASH
    elif raw_method in ("bank", "bank_transfer", "transfer"):
        pmethod = PaymentMethod.BANK_TRANSFER
    else:
        await update.effective_message.reply_text("⚠️ Invalid payment method. Must be 'cash' or 'bank'.")
        return

    try:
        dec_amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        await update.effective_message.reply_text("⚠️ Invalid amount. Must be numeric (e.g. 5.00).")
        return

    with get_db_session() as session:
        try:
            payment = record_payment_verification(
                session=session,
                request_id=request_id,
                payment_type=ptype,
                payment_method=pmethod,
                amount=dec_amount,
                actor_telegram_id=user_id,
                reference=ref_note,
            )
            req = payment.request
            can_checkout, _ = req.can_checkout()
            ready_msg = f"🟢 <b>Ready for physical checkout!</b> Run <code>/checkout {req.id}</code>" if can_checkout else "⏳ Pending remaining requirements before checkout."
            cust_tid = req.customer.telegram_id
            p_type_val = payment.payment_type
            p_amt_val = str(payment.amount)
            p_meth_val = payment.payment_method
            p_req_id = payment.request_id

            await update.effective_message.reply_text(
                f"💳 <b>Payment Verified & Recorded!</b>\n\n"
                f"• <b>Payment ID:</b> #{payment.id}\n"
                f"• <b>Request ID:</b> #{req.id}\n"
                f"• <b>Type:</b> {payment.payment_type}\n"
                f"• <b>Method:</b> {payment.payment_method}\n"
                f"• <b>Amount:</b> ${payment.amount}\n"
                f"• <b>Verified By Staff:</b> {payment.verified_by}\n"
                f"• <b>Timestamp:</b> {payment.verified_at.strftime('%Y-%m-%d %H:%M:%S UTC') if payment.verified_at else 'Now'}\n"
                f"• <b>Reference:</b> {html.escape(payment.reference or 'None')}\n\n"
                f"{ready_msg}",
                parse_mode=ParseMode.HTML,
            )
            await notify_customer(
                bot=context.bot,
                customer_telegram_id=cust_tid,
                event_key="notify_payment_recorded_cust",
                type=p_type_val,
                amount=p_amt_val,
                method=p_meth_val,
                request_id=p_req_id,
            )
        except PaymentAlreadyVerifiedError as exc:
            await update.effective_message.reply_text(f"ℹ️ {html.escape(str(exc))}")
        except RentalRequestNotFoundError:
            await update.effective_message.reply_text(f"❌ RentalRequest #{request_id} not found.")
        except (ValueError, TypeError) as exc:
            await update.effective_message.reply_text(f"⚠️ {html.escape(str(exc))}")
        except UnauthorizedError:
            await update.effective_message.reply_text("⛔ Unauthorized: Owner access required.")


async def recordguarantee_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to record verified non-cash collateral guarantee."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to bot owners.")
        return

    args = context.args or []
    if len(args) < 2 or not args[0].isdigit():
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b> <code>/recordguarantee &lt;request_id&gt; &lt;details&gt;</code>\n\n"
            "<b>Example:</b> <code>/recordguarantee 1 Held National ID #1234567</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    request_id = int(args[0])
    details = " ".join(args[1:]).strip()

    with get_db_session() as session:
        try:
            payment = record_non_cash_guarantee(
                session=session,
                request_id=request_id,
                actor_telegram_id=user_id,
                guarantee_details=details,
            )
            req = payment.request
            can_checkout, _ = req.can_checkout()
            ready_msg = f"🟢 <b>Ready for physical checkout!</b> Run <code>/checkout {req.id}</code>" if can_checkout else "⏳ Pending remaining requirements before checkout."
            cust_tid = req.customer.telegram_id
            g_details = req.guarantee_details or details

            await update.effective_message.reply_text(
                f"🪪 <b>Non-Cash Guarantee Recorded!</b>\n\n"
                f"• <b>Request ID:</b> #{req.id}\n"
                f"• <b>Guarantee Details:</b> <i>{html.escape(req.guarantee_details or '')}</i>\n"
                f"• <b>Accounting Note:</b> Recorded as non-cash arrangement (No monetary collateral ledger entry created)\n"
                f"• <b>Verified By Staff:</b> {payment.verified_by}\n\n"
                f"{ready_msg}",
                parse_mode=ParseMode.HTML,
            )
            await notify_customer(
                bot=context.bot,
                customer_telegram_id=cust_tid,
                event_key="notify_guarantee_recorded_cust",
                details=g_details,
            )
        except PaymentAlreadyVerifiedError as exc:
            await update.effective_message.reply_text(f"ℹ️ {html.escape(str(exc))}")
        except RentalRequestNotFoundError:
            await update.effective_message.reply_text(f"❌ RentalRequest #{request_id} not found.")
        except UnauthorizedError:
            await update.effective_message.reply_text("⛔ Unauthorized: Owner access required.")


async def checkout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner command to confirm physical book handover and activate rental."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to bot owners.")
        return

    args = context.args or []
    if not args or not args[0].isdigit():
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b> <code>/checkout &lt;request_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    request_id = int(args[0])

    with get_db_session() as session:
        try:
            rental = confirm_physical_handover(session, request_id, actor_telegram_id=user_id)
            tz = get_rental_timezone()
            local_due = rental.due_date.astimezone(tz)
            cust_tid = rental.customer.telegram_id
            b_title = rental.copy.book.title
            b_barcode = rental.copy.barcode
            b_due = rental.due_date.strftime("%Y-%m-%d %H:%M UTC")

            await update.effective_message.reply_text(
                f"🎉 <b>Physical Handover Confirmed! Rental Activated!</b>\n\n"
                f"• <b>Rental ID:</b> #{rental.id}\n"
                f"• <b>Physical Copy Barcode:</b> <code>{rental.copy.barcode}</code>\n"
                f"• <b>Copy Status:</b> <b>RENTED</b>\n"
                f"• <b>Checkout Time:</b> {rental.checkout_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"• <b>Return Deadline:</b> <b>{local_due.strftime('%Y-%m-%d %H:%M:%S %Z')}</b>\n"
                f"  <i>(10-Calendar-Day End-of-Day convention: {rental.due_date.strftime('%Y-%m-%d %H:%M:%S UTC')})</i>\n\n"
                f"Book copy #{rental.copy_id} has been physically handed over to customer #{rental.customer_id}.",
                parse_mode=ParseMode.HTML,
            )
            await notify_customer(
                bot=context.bot,
                customer_telegram_id=cust_tid,
                event_key="notify_checkout_cust",
                book_title=b_title,
                barcode=b_barcode,
                due_date=b_due,
            )
        except RentalRequestAlreadyCompletedError:
            await update.effective_message.reply_text("ℹ️ Physical handover has already been completed for this request.")
        except CheckoutConditionsNotMetError as exc:
            await update.effective_message.reply_text(
                f"⛔ <b>Cannot Handover Yet:</b> {html.escape(str(exc))}",
                parse_mode=ParseMode.HTML,
            )
        except RentalRequestNotFoundError:
            await update.effective_message.reply_text(f"❌ RentalRequest #{request_id} not found.")
        except CopyNotAvailableError as exc:
            await update.effective_message.reply_text(f"🔴 {html.escape(str(exc))}")
        except UnauthorizedError:
            await update.effective_message.reply_text("⛔ Unauthorized: Owner access required.")


async def rental_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callbacks for approving, rejecting, or checking out rental requests.

    Includes idempotency guards against duplicate clicks and owner authorization checks.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    data = query.data
    action, _, id_str = data.partition(":")
    if action not in ("approve_req", "reject_req", "checkout_req") or not id_str.isdigit():
        await query.answer("Invalid callback data.")
        return

    request_id = int(id_str)
    with get_db_session() as session:
        try:
            if action == "approve_req":
                req = approve_rental_request(session, request_id, actor_telegram_id=user_id)
                await query.answer(f"Request #{req.id} approved!")
                barcode = req.copy.barcode if req.copy else f"#{req.copy_id}"
                cust_tid = req.customer.telegram_id
                book_t = req.book.title
                fee_s = str(req.rental_fee)
                ctype = req.collateral_type
                new_text = (
                    f"✅ <b>Approved:</b> Request #{req.id}\n"
                    f"• Book: <i>{html.escape(req.book.title)}</i>\n"
                    f"• Reserved Copy: <code>{barcode}</code>\n"
                    f"• Customer: {html.escape(req.customer.first_name)} (ID: #{req.customer_id})\n"
                    f"• Fee (${req.rental_fee}): {'✅ Paid' if req.rental_fee_paid else '⏳ Unpaid'}\n"
                    f"• Collateral: {'✅ Verified' if req.collateral_received else '⏳ Unverified'}\n\n"
                    f"<i>Verify payment via /recordpayment and confirm handover with /checkout {req.id}</i>"
                )
                lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
                kb = get_owner_request_action_keyboard(lang, req.id, req.status, req.rental_fee_paid, req.collateral_received, False)
                await query.edit_message_text(new_text, reply_markup=kb, parse_mode=ParseMode.HTML)
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=cust_tid,
                    event_key="notify_req_approved_cust",
                    id=req.id,
                    book_title=book_t,
                    rental_fee=fee_s,
                    collateral_type=ctype,
                )

            elif action == "reject_req":
                req = reject_rental_request(session, request_id, actor_telegram_id=user_id, reason="Rejected via button")
                await query.answer(f"Request #{req.id} rejected.")
                cust_tid = req.customer.telegram_id
                book_t = req.book.title
                new_text = (
                    f"❌ <b>Rejected:</b> Request #{req.id}\n"
                    f"• Book: <i>{html.escape(req.book.title)}</i>\n"
                    f"• Customer: {html.escape(req.customer.first_name)} (ID: #{req.customer_id})\n"
                    f"Any reserved physical copy has been released back to ON_SHELF."
                )
                await query.edit_message_text(new_text, parse_mode=ParseMode.HTML)
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=cust_tid,
                    event_key="notify_req_rejected_cust",
                    id=req.id,
                    book_title=book_t,
                    reason_line="Reason: Rejected via button",
                )

            elif action == "checkout_req":
                rental = confirm_physical_handover(session, request_id, actor_telegram_id=user_id)
                await query.answer("Physical handover confirmed!")
                cust_tid = rental.customer.telegram_id
                b_title = rental.copy.book.title
                b_barcode = rental.copy.barcode
                b_due = rental.due_date.strftime("%Y-%m-%d %H:%M UTC")
                new_text = (
                    f"🎉 <b>Handover Confirmed: Rental #{rental.id} Active!</b>\n"
                    f"• Barcode: <code>{rental.copy.barcode}</code>\n"
                    f"• Checkout: {rental.checkout_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"• Due Date: {rental.due_date.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
                await query.edit_message_text(new_text, parse_mode=ParseMode.HTML)
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=cust_tid,
                    event_key="notify_checkout_cust",
                    book_title=b_title,
                    barcode=b_barcode,
                    due_date=b_due,
                )

        except RentalRequestNotFoundError:
            await query.answer("Rental request not found.", show_alert=True)
            await query.edit_message_text("❌ Rental request record no longer exists.")
        except InvalidRentalRequestStatusError as exc:
            await query.answer("Notice: Request already processed.", show_alert=False)
            await query.edit_message_text(f"ℹ️ {html.escape(str(exc))}")
        except RentalRequestAlreadyCompletedError:
            await query.answer("Notice: Rental already completed.", show_alert=False)
            await query.edit_message_text("ℹ️ Physical handover has already been completed.")
        except CheckoutConditionsNotMetError as exc:
            await query.answer(f"Cannot checkout: {exc}", show_alert=True)
        except CopyNotAvailableError as exc:
            await query.answer(f"Allocation error: {exc}", show_alert=True)


async def owner_request_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle interactive owner action buttons on rental requests (approve, reject, pay, guarantee, handover)."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    parts = query.data.split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        await query.answer("Invalid request action.", show_alert=True)
        return

    action = parts[1]
    request_id = int(parts[2])

    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        try:
            if action == "approve":
                req = approve_rental_request(session, request_id, actor_telegram_id=user_id)
                can_checkout, _ = req.can_checkout()
                card = (
                    f"✅ <b>Approved: Request #{req.id}</b>\n\n"
                    f"• Book: <i>{html.escape(req.book.title)}</i>\n"
                    f"• Reserved Copy: <code>{req.copy.barcode if req.copy else 'N/A'}</code>\n"
                    f"• Customer: {html.escape(req.customer.first_name)} (ID: #{req.customer_id})\n"
                    f"• Rental Fee ({req.rental_fee} ETB): {'✅ Paid' if req.rental_fee_paid else '⏳ Unpaid'}\n"
                    f"• Collateral: {'✅ Verified' if req.collateral_received else '⏳ Unverified'}\n\n"
                    f"<i>Choose next action below:</i>"
                )
                kb = get_owner_request_action_keyboard(lang, req.id, req.status, req.rental_fee_paid, req.collateral_received, can_checkout)
                await query.edit_message_text(card, reply_markup=kb, parse_mode=ParseMode.HTML)
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=req.customer.telegram_id,
                    event_key="notify_req_approved_cust",
                    id=req.id,
                    book_title=req.book.title,
                    rental_fee=str(req.rental_fee),
                    collateral_type=req.collateral_type,
                )

            elif action == "reject":
                req = reject_rental_request(session, request_id, actor_telegram_id=user_id, reason="Rejected via action button")
                await query.edit_message_text(f"❌ <b>Rejected:</b> Request #{req.id} for <i>{html.escape(req.book.title)}</i> has been rejected and closed.", parse_mode=ParseMode.HTML)
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=req.customer.telegram_id,
                    event_key="notify_req_rejected_cust",
                    id=req.id,
                    book_title=req.book.title,
                    reason_line="Reason: Rejected by library owner",
                )

            elif action in ("pay_cash", "pay_bank"):
                pmethod = PaymentMethod.CASH if action == "pay_cash" else PaymentMethod.BANK_TRANSFER
                req_obj = session.get(RentalRequest, request_id)
                if not req_obj:
                    await query.answer("Request not found.", show_alert=True)
                    return
                payment = record_payment_verification(
                    session=session,
                    request_id=request_id,
                    payment_type=PaymentType.RENTAL_FEE,
                    payment_method=pmethod,
                    amount=req_obj.rental_fee,
                    actor_telegram_id=user_id,
                    reference=f"Verified via {pmethod.value} button",
                )
                can_checkout, _ = req_obj.can_checkout()
                card = (
                    f"💳 <b>Fee Verified: Request #{req_obj.id}</b>\n\n"
                    f"• Book: <i>{html.escape(req_obj.book.title)}</i>\n"
                    f"• Payment: {payment.amount} ETB via {pmethod.value} ✅\n"
                    f"• Collateral: {'✅ Verified' if req_obj.collateral_received else '⏳ Unverified'}\n\n"
                    f"{'🟢 <b>Ready for physical handover!</b>' if can_checkout else '⏳ Pending collateral verification before checkout.'}"
                )
                kb = get_owner_request_action_keyboard(lang, req_obj.id, req_obj.status, req_obj.rental_fee_paid, req_obj.collateral_received, can_checkout)
                await query.edit_message_text(card, reply_markup=kb, parse_mode=ParseMode.HTML)
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=req_obj.customer.telegram_id,
                    event_key="notify_payment_recorded_cust",
                    type="RENTAL_FEE",
                    amount=str(payment.amount),
                    method=pmethod.value,
                    request_id=req_obj.id,
                )

            elif action == "guarantee":
                req_obj = session.get(RentalRequest, request_id)
                if not req_obj:
                    await query.answer("Request not found.", show_alert=True)
                    return
                g_note = req_obj.guarantee_details or f"National ID on file ({req_obj.customer.phone_number})"
                payment = record_non_cash_guarantee(
                    session=session,
                    request_id=request_id,
                    guarantee_details=g_note,
                    actor_telegram_id=user_id,
                )
                can_checkout, _ = req_obj.can_checkout()
                card = (
                    f"🪪 <b>Guarantee Verified: Request #{req_obj.id}</b>\n\n"
                    f"• Book: <i>{html.escape(req_obj.book.title)}</i>\n"
                    f"• Guarantee Held: <i>{html.escape(g_note)}</i> ✅\n"
                    f"• Rental Fee: {'✅ Paid' if req_obj.rental_fee_paid else '⏳ Unpaid'}\n\n"
                    f"{'🟢 <b>Ready for physical handover!</b>' if can_checkout else '⏳ Pending rental fee payment before checkout.'}"
                )
                kb = get_owner_request_action_keyboard(lang, req_obj.id, req_obj.status, req_obj.rental_fee_paid, req_obj.collateral_received, can_checkout)
                await query.edit_message_text(card, reply_markup=kb, parse_mode=ParseMode.HTML)
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=req_obj.customer.telegram_id,
                    event_key="notify_guarantee_recorded_cust",
                    details=g_note,
                )

            elif action == "deposit_cash":
                req_obj = session.get(RentalRequest, request_id)
                if not req_obj:
                    await query.answer("Request not found.", show_alert=True)
                    return
                deposit_amt = Decimal("50.00")
                payment = record_payment_verification(
                    session=session,
                    request_id=request_id,
                    payment_type=PaymentType.COLLATERAL_DEPOSIT,
                    payment_method=PaymentMethod.CASH,
                    amount=deposit_amt,
                    actor_telegram_id=user_id,
                    reference="Cash collateral deposit",
                )
                can_checkout, _ = req_obj.can_checkout()
                card = (
                    f"💵 <b>Deposit Verified: Request #{req_obj.id}</b>\n\n"
                    f"• Book: <i>{html.escape(req_obj.book.title)}</i>\n"
                    f"• Cash Deposit: {deposit_amt} ETB ✅\n"
                    f"• Rental Fee: {'✅ Paid' if req_obj.rental_fee_paid else '⏳ Unpaid'}\n\n"
                    f"{'🟢 <b>Ready for physical handover!</b>' if can_checkout else '⏳ Pending rental fee payment.'}"
                )
                kb = get_owner_request_action_keyboard(lang, req_obj.id, req_obj.status, req_obj.rental_fee_paid, req_obj.collateral_received, can_checkout)
                await query.edit_message_text(card, reply_markup=kb, parse_mode=ParseMode.HTML)
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=req_obj.customer.telegram_id,
                    event_key="notify_payment_recorded_cust",
                    type="COLLATERAL_DEPOSIT",
                    amount=str(deposit_amt),
                    method="CASH",
                    request_id=req_obj.id,
                )

            elif action == "handover":
                rental = confirm_physical_handover(session, request_id, actor_telegram_id=user_id)
                await query.edit_message_text(
                    f"🎉 <b>Physical Handover Confirmed! Rental #{rental.id} Activated!</b>\n\n"
                    f"• Book: <i>{html.escape(rental.copy.book.title)}</i>\n"
                    f"• Copy Barcode: <code>{rental.copy.barcode}</code>\n"
                    f"• Customer: {html.escape(rental.customer.first_name)} (ID: #{rental.customer_id})\n"
                    f"• Due Date: <b>{rental.due_date.strftime('%Y-%m-%d %H:%M UTC')}</b> (10 calendar days)\n"
                    f"• Status: <b>RENTED</b>",
                    parse_mode=ParseMode.HTML,
                )
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=rental.customer.telegram_id,
                    event_key="notify_checkout_cust",
                    book_title=rental.copy.book.title,
                    barcode=rental.copy.barcode,
                    due_date=rental.due_date.strftime("%Y-%m-%d %H:%M UTC"),
                )

        except PaymentAlreadyVerifiedError:
            await query.answer("Notice: Payment/guarantee already verified.", show_alert=False)
        except RentalRequestAlreadyCompletedError:
            await query.answer("Notice: Handover already completed.", show_alert=False)
        except CheckoutConditionsNotMetError as exc:
            await query.answer(f"Cannot checkout: {exc}", show_alert=True)
        except Exception as exc:
            logger.error("Error in owner_request_action_callback: %s", exc, exc_info=True)
            await query.answer(f"Error: {exc}", show_alert=True)





# ==============================================================================
# Phase 5: Overdue, Extensions, and Return Handlers
# ==============================================================================


async def myrentals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Customer handler: View active and extended rentals, due dates, and status."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    with get_db_session() as session:
        customer = get_customer_by_telegram_id(session, user_id)
        if not customer:
            await update.effective_message.reply_text(
                "❌ You do not have an account. Use /start to register."
            )
            return

        if not customer.is_approved:
            await update.effective_message.reply_text(
                f"ℹ️ Your account status is <b>{customer.status}</b>. Only APPROVED customers can view rentals.",
                parse_mode=ParseMode.HTML,
            )
            return

        rentals = get_customer_active_rentals(session, customer.id)
        if not rentals:
            await update.effective_message.reply_text(
                "📚 You currently have no active rentals.", parse_mode=ParseMode.HTML
            )
            return

        lines = ["📖 <b>Your Active Rentals:</b>\n"]
        for r in rentals:
            summary = get_rental_overdue_summary(session, r.id)
            book_title = html.escape(r.copy.book.title) if r.copy and r.copy.book else "Unknown"
            barcode = r.copy.barcode if r.copy else "N/A"
            checkout_str = r.checkout_time.strftime("%Y-%m-%d %H:%M UTC")
            due_str = r.due_date.strftime("%Y-%m-%d %H:%M UTC")

            overdue_part = ""
            if summary["is_overdue"]:
                overdue_part = (
                    f"\n  ⚠️ <b>OVERDUE</b> by {summary['overdue_days']} day(s)! "
                    f"Accrued late fee: <b>{summary['total_overdue_fee']} ETB</b> (5 ETB/day)"
                )

            lines.append(
                f"• <b>Rental #{r.id}</b>: <i>{book_title}</i>\n"
                f"  Barcode: <code>{barcode}</code> | Status: {r.status}\n"
                f"  Checked out: {checkout_str}\n"
                f"  Due date: <b>{due_str}</b>"
                f"{overdue_part}\n"
                f"  💡 <i>Request 5-day extension: /extend {r.id}</i>\n"
            )

        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def extend_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Customer handler: Request a 5-calendar-day extension for an active rental."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not context.args or len(context.args) < 1:
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b> <code>/extend &lt;rental_id&gt;</code>\n"
            "Request a 5-calendar-day extension for your active rental (Fixed Fee: 10.00 ETB).",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        rental_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Rental ID must be a positive integer.")
        return

    with get_db_session() as session:
        try:
            extension = submit_extension_request(
                session=session,
                customer_telegram_id=user_id,
                rental_id=rental_id,
            )
            book_title = (
                html.escape(extension.rental.copy.book.title)
                if extension.rental.copy and extension.rental.copy.book
                else "Book"
            )
            new_due_str = extension.new_due_date.strftime("%Y-%m-%d %H:%M UTC")

            customer_msg = (
                f"✅ <b>Extension Requested for Rental #{rental_id}!</b>\n\n"
                f"• Book: <i>{book_title}</i>\n"
                f"• Additional Duration: <b>5 calendar days</b>\n"
                f"• Proposed Return Deadline: <b>{new_due_str}</b>\n"
                f"• Extension Fee: <b>{extension.fee} ETB</b>\n\n"
                f"ℹ️ <i>Please pay the 10.00 ETB extension fee (Cash or Bank Transfer) to library staff. "
                f"Your extension will become effective upon manual owner payment verification.</i>"
            )
            await update.effective_message.reply_text(customer_msg, parse_mode=ParseMode.HTML)

            # Notify configured library owners
            settings = get_settings()
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("💵 Approve (Cash)", callback_data=f"approve_ext_cash:{extension.id}"),
                        InlineKeyboardButton("🏦 Approve (Bank)", callback_data=f"approve_ext_bank:{extension.id}"),
                    ],
                    [
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject_ext:{extension.id}"),
                    ],
                ]
            )
            owner_msg = (
                f"📢 <b>New Extension Request Received!</b>\n\n"
                f"• Extension ID: <b>#{extension.id}</b>\n"
                f"• Rental ID: <b>#{rental_id}</b>\n"
                f"• Customer: {html.escape(extension.rental.customer.first_name)} (ID: #{extension.rental.customer_id})\n"
                f"• Book: <i>{book_title}</i>\n"
                f"• Extension Duration: 5 calendar days\n"
                f"• Proposed Due Date: {new_due_str}\n"
                f"• Extension Fee: <b>10.00 ETB</b>\n\n"
                f"Verify payment and approve or reject below, or run:\n"
                f"<code>/approveext {extension.id} &lt;cash|bank&gt; [ref]</code>\n"
                f"<code>/rejectext {extension.id} [reason]</code>"
            )
            for owner_id in settings.admin_user_ids:
                try:
                    await context.bot.send_message(
                        chat_id=owner_id,
                        text=owner_msg,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                except Exception as exc:
                    logger.warning("Failed to notify owner %s of extension request: %s", owner_id, exc)

            await notify_admins(
                bot=context.bot,
                event_key="notify_ext_requested_admin",
                id=extension.id,
                customer_name=extension.rental.customer.first_name,
                rental_id=rental_id,
            )

        except CustomerNotFoundError:
            await update.effective_message.reply_text("❌ Customer account not found. Please register with /start.")
        except CustomerNotApprovedError as exc:
            await update.effective_message.reply_text(f"⛔ {html.escape(str(exc))}")
        except RentalNotFoundError:
            await update.effective_message.reply_text(f"❌ Rental #{rental_id} was not found.")
        except UnauthorizedError:
            await update.effective_message.reply_text(f"⛔ Rental #{rental_id} does not belong to your account.")
        except RentalNotActiveError as exc:
            await update.effective_message.reply_text(f"⚠️ {html.escape(str(exc))}")
        except ActiveExtensionRequestExistsError as exc:
            await update.effective_message.reply_text(f"ℹ️ {html.escape(str(exc))}")


async def myextensions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Customer handler: View status of requested rental extensions."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    with get_db_session() as session:
        customer = get_customer_by_telegram_id(session, user_id)
        if not customer:
            await update.effective_message.reply_text("❌ Please register first using /start.")
            return

        extensions = (
            session.query(RentalExtension)
            .join(Rental)
            .filter(Rental.customer_id == customer.id)
            .order_by(RentalExtension.requested_at.desc())
            .all()
        )
        if not extensions:
            await update.effective_message.reply_text("ℹ️ You have not submitted any rental extension requests.")
            return

        lines = ["📋 <b>Your Rental Extensions:</b>\n"]
        for ext in extensions:
            book_title = (
                html.escape(ext.rental.copy.book.title)
                if ext.rental.copy and ext.rental.copy.book
                else "Book"
            )
            payment_status = "✅ Verified" if ext.payment_verified else "⏳ Unverified"
            lines.append(
                f"• <b>Extension #{ext.id}</b> for Rental #{ext.rental_id}\n"
                f"  Book: <i>{book_title}</i>\n"
                f"  Status: <b>{ext.status}</b> | Payment: {payment_status}\n"
                f"  Requested: {ext.requested_days} days | Fee: {ext.fee} ETB\n"
                f"  New Due Date: {ext.new_due_date.strftime('%Y-%m-%d %H:%M UTC')}\n"
            )

        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def overdue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Role-aware handler: List overdue rentals and accrued late fees.

    - If run by an Owner: lists all overdue rentals across the library.
    - If run by a Customer: lists their own overdue rentals and charges.
    """
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    with get_db_session() as session:
        if is_owner(user_id):
            overdue_rentals = get_all_overdue_rentals(session)
            if not overdue_rentals:
                await update.effective_message.reply_text("🎉 No rentals are currently overdue across the library!")
                return

            total_accrued = Decimal("0.00")
            lines = [f"⚠️ <b>Overdue Rentals ({len(overdue_rentals)} active):</b>\n"]
            for r, days, fee in overdue_rentals:
                total_accrued += fee
                book_title = html.escape(r.copy.book.title) if r.copy and r.copy.book else "Unknown"
                cust_name = html.escape(r.customer.first_name) if r.customer else "Unknown"
                due_str = r.due_date.strftime("%Y-%m-%d %H:%M UTC")

                lines.append(
                    f"• <b>Rental #{r.id}</b> — <i>{book_title}</i>\n"
                    f"  Customer: {cust_name} (ID: #{r.customer_id})\n"
                    f"  Due Date: {due_str}\n"
                    f"  Overdue: <b>{days} day(s)</b> | Accrued Fee: <b>{fee} ETB</b> (5 ETB/day)\n"
                    f"  Return: <code>/return {r.id} good</code>\n"
                )

            lines.append(f"\n<b>Total Outstanding Overdue Fees:</b> {total_accrued} ETB")
            await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

        else:
            customer = get_customer_by_telegram_id(session, user_id)
            if not customer:
                await update.effective_message.reply_text("❌ Please register first using /start.")
                return

            rentals = get_customer_active_rentals(session, customer.id)
            overdue_items = []
            for r in rentals:
                summary = get_rental_overdue_summary(session, r.id)
                if summary["is_overdue"]:
                    overdue_items.append((r, summary))

            if not overdue_items:
                await update.effective_message.reply_text("🎉 You have no overdue rentals. Keep it up!")
                return

            lines = ["⚠️ <b>Your Overdue Rentals:</b>\n"]
            total_fee = Decimal("0.00")
            for r, s in overdue_items:
                total_fee += s["total_overdue_fee"]
                book_title = html.escape(r.copy.book.title) if r.copy and r.copy.book else "Book"
                lines.append(
                    f"• <b>Rental #{r.id}</b>: <i>{book_title}</i>\n"
                    f"  Due: {r.due_date.strftime('%Y-%m-%d %H:%M UTC')}\n"
                    f"  Overdue by: <b>{s['overdue_days']} day(s)</b>\n"
                    f"  Accrued Fee: <b>{s['total_overdue_fee']} ETB</b> (5 ETB/day)\n"
                    f"  <i>Please return the book to the library or contact staff.</i>\n"
                )

            lines.append(f"<b>Total Overdue Fees Accrued:</b> {total_fee} ETB")
            await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def checkoverdue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only handler: Manually trigger daily overdue detection and notification dispatch."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to library owners.")
        return

    await update.effective_message.reply_text("🔄 Running overdue detection and notification job...")
    with get_db_session() as session:
        created_charges = process_overdue_rentals(session=session)
        notif_count = send_overdue_notifications(
            session=session,
            bot=context.bot,
            owner_chat_ids=get_settings().admin_user_ids,
        )

    await update.effective_message.reply_text(
        f"✅ <b>Overdue Processing Completed</b>\n"
        f"• New Daily Charges Created: <b>{len(created_charges)}</b>\n"
        f"• Overdue Notifications Dispatched: <b>{notif_count}</b>",
        parse_mode=ParseMode.HTML,
    )


async def extensions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only handler: List pending rental extension requests requiring review."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to library owners.")
        return

    with get_db_session() as session:
        pending = get_pending_extension_requests(session)
        if not pending:
            await update.effective_message.reply_text("ℹ️ No extension requests are currently pending review.")
            return

        lines = [f"📋 <b>Pending Rental Extension Requests ({len(pending)}):</b>\n"]
        for ext in pending:
            book_title = (
                html.escape(ext.rental.copy.book.title)
                if ext.rental.copy and ext.rental.copy.book
                else "Book"
            )
            cust_name = html.escape(ext.rental.customer.first_name) if ext.rental.customer else "Unknown"
            new_due_str = ext.new_due_date.strftime("%Y-%m-%d %H:%M UTC")

            lines.append(
                f"• <b>Extension #{ext.id}</b> (Rental #{ext.rental_id})\n"
                f"  Customer: {cust_name} (ID: #{ext.rental.customer_id})\n"
                f"  Book: <i>{book_title}</i>\n"
                f"  Duration: +{ext.requested_days} days | Target Due: {new_due_str}\n"
                f"  Fee: <b>{ext.fee} ETB</b> | Payment: {'✅ Verified' if ext.payment_verified else '⏳ Pending'}\n"
                f"  Action: <code>/approveext {ext.id} cash</code> or <code>/rejectext {ext.id}</code>\n"
            )

        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def approveext_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only handler: Verify payment and approve a 5-calendar-day extension."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to library owners.")
        return

    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b> <code>/approveext &lt;extension_id&gt; &lt;cash|bank&gt; [reference]</code>\n"
            "Example: <code>/approveext 1 cash</code> or <code>/approveext 1 bank TXN12345</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        ext_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Extension ID must be a valid integer.")
        return

    method_raw = context.args[1].lower()
    if method_raw in ("cash",):
        pmethod = PaymentMethod.CASH
    elif method_raw in ("bank", "bank_transfer", "transfer"):
        pmethod = PaymentMethod.BANK_TRANSFER
    else:
        await update.effective_message.reply_text(
            "❌ Invalid payment method. Must be 'cash' or 'bank'."
        )
        return

    reference = " ".join(context.args[2:]).strip() if len(context.args) > 2 else None

    with get_db_session() as session:
        try:
            ext = verify_and_approve_extension(
                session=session,
                extension_id=ext_id,
                payment_method=pmethod,
                actor_telegram_id=user_id,
                reference=reference,
            )
            book_title = (
                html.escape(ext.rental.copy.book.title)
                if ext.rental.copy and ext.rental.copy.book
                else "Book"
            )
            new_due_str = ext.new_due_date.strftime("%Y-%m-%d %H:%M UTC")

            await update.effective_message.reply_text(
                f"✅ <b>Extension #{ext.id} Approved!</b>\n\n"
                f"• Rental ID: <b>#{ext.rental_id}</b>\n"
                f"• Book: <i>{book_title}</i>\n"
                f"• New Return Deadline: <b>{new_due_str}</b>\n"
                f"• Payment Verified: <b>{ext.fee} ETB</b> via {pmethod.value}\n"
                f"• Accrued late fees (if any) remain intact.",
                parse_mode=ParseMode.HTML,
            )

            await notify_customer(
                bot=context.bot,
                customer_telegram_id=ext.rental.customer.telegram_id,
                event_key="notify_ext_approved_cust",
                rental_id=ext.rental_id,
                due_date=new_due_str,
            )

        except ExtensionNotFoundError:
            await update.effective_message.reply_text(f"❌ Extension #{ext_id} not found.")
        except ExtensionAlreadyAppliedError:
            await update.effective_message.reply_text(f"ℹ️ Extension #{ext_id} has already been applied.")
        except ExtensionPaymentNotVerifiedError as exc:
            await update.effective_message.reply_text(f"⛔ {html.escape(str(exc))}")
        except Exception as exc:
            logger.error("Error approving extension: %s", exc, exc_info=True)
            await update.effective_message.reply_text(f"❌ Error: {html.escape(str(exc))}")


async def rejectext_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only handler: Reject a rental extension request."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to library owners.")
        return

    if not context.args or len(context.args) < 1:
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b> <code>/rejectext &lt;extension_id&gt; [reason]</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        ext_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Extension ID must be a valid integer.")
        return

    reason = " ".join(context.args[1:]).strip() if len(context.args) > 1 else None

    with get_db_session() as session:
        try:
            ext = reject_rental_extension(
                session=session,
                extension_id=ext_id,
                actor_telegram_id=user_id,
                reason=reason,
            )
            await update.effective_message.reply_text(
                f"❌ <b>Extension #{ext.id} Rejected.</b>\n"
                f"Rental #{ext.rental_id} due date remains unchanged: "
                f"{ext.rental.due_date.strftime('%Y-%m-%d %H:%M UTC')}",
                parse_mode=ParseMode.HTML,
            )

            reason_line = f"Reason: {reason}" if reason else ""
            await notify_customer(
                bot=context.bot,
                customer_telegram_id=ext.rental.customer.telegram_id,
                event_key="notify_ext_rejected_cust",
                rental_id=ext.rental_id,
                due_date=ext.rental.due_date.strftime("%Y-%m-%d %H:%M UTC"),
                reason_line=reason_line,
            )

        except ExtensionNotFoundError:
            await update.effective_message.reply_text(f"❌ Extension #{ext_id} not found.")
        except ExtensionAlreadyAppliedError:
            await update.effective_message.reply_text(f"ℹ️ Extension #{ext_id} has already been applied.")


async def return_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only handler: Confirm physical book return, inspect condition, and close rental."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to library owners.")
        return

    if not context.args:
        with get_db_session() as session:
            active_rentals = (
                session.query(Rental)
                .filter(Rental.status.in_([RentalStatus.ACTIVE.value, RentalStatus.EXTENDED.value, RentalStatus.OVERDUE.value]))
                .order_by(Rental.due_date.asc())
                .limit(10)
                .all()
            )
            lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
            if not active_rentals:
                await update.effective_message.reply_text(
                    "📦 <b>No Active Rentals</b>\n\nThere are currently no active or overdue rentals to return.",
                    parse_mode=ParseMode.HTML,
                )
                return

            msg_lines = ["📦 <b>Active Rentals to Return:</b>\n"]
            buttons = []
            for r in active_rentals:
                b_title = r.copy.book.title if r.copy and r.copy.book else "Book"
                c_name = r.customer.first_name if r.customer else "Customer"
                st = "⚠️ OVERDUE" if r.status == RentalStatus.OVERDUE.value else "🔵 Active"
                msg_lines.append(
                    f"• <b>Rental #{r.id}</b> [{st}]: <i>{html.escape(b_title)}</i>\n"
                    f"  Customer: {html.escape(c_name)} (ID: #{r.customer_id}) | Barcode: <code>{r.copy.barcode if r.copy else 'N/A'}</code>\n"
                    f"  Due: {r.due_date.strftime('%Y-%m-%d %H:%M UTC')}\n"
                )
                buttons.append([
                    InlineKeyboardButton(
                        f"📦 Return #{r.id} ({b_title[:15]})",
                        callback_data=f"ret_select:{r.id}",
                    )
                ])

            msg_lines.append(
                "\n<i>Tap a rental above to inspect and confirm return, or use command:</i>\n"
                "<code>/return &lt;rental_id&gt; &lt;good|damaged|lost&gt; [notes]</code>"
            )
            await update.effective_message.reply_text(
                "\n".join(msg_lines),
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.HTML,
            )
            return

    if len(context.args) == 1:
        if not context.args[0].isdigit():
            await update.effective_message.reply_text(
                "⚠️ <b>Usage:</b> <code>/return &lt;rental_id&gt; &lt;good|damaged|lost&gt; [condition notes]</code>\n"
                "Examples:\n"
                "• <code>/return 1 good</code>\n"
                "• <code>/return 1 damaged Torn back cover</code>\n"
                "• <code>/return 1 lost Declared lost by customer</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        rental_id = int(context.args[0])
        with get_db_session() as session:
            rental = session.get(Rental, rental_id)
            if not rental:
                await update.effective_message.reply_text(f"❌ Rental #{rental_id} was not found.")
                return
            lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
            b_title = rental.copy.book.title if rental.copy and rental.copy.book else "Book"
            barcode = rental.copy.barcode if rental.copy else "N/A"
            c_name = rental.customer.first_name if rental.customer else "Customer"
            msg = (
                f"📦 <b>Process Return for Rental #{rental.id}</b>\n\n"
                f"• <b>Book:</b> <i>{html.escape(b_title)}</i>\n"
                f"• <b>Barcode:</b> <code>{barcode}</code>\n"
                f"• <b>Customer:</b> {html.escape(c_name)} (ID: #{rental.customer_id})\n"
                f"• <b>Due Date:</b> {rental.due_date.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
                f"Please inspect the physical book condition and select an action below:"
            )
            await update.effective_message.reply_text(
                msg,
                reply_markup=get_owner_return_action_keyboard(lang, rental.id),
                parse_mode=ParseMode.HTML,
            )
            return

    try:
        rental_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Rental ID must be a valid integer.")
        return

    raw_cond = context.args[1].lower()
    if raw_cond in ("good", "on_shelf", "ok", "intact"):
        condition = BookCopyStatus.ON_SHELF
    elif raw_cond in ("damaged", "damage", "broken"):
        condition = BookCopyStatus.DAMAGED
    elif raw_cond in ("lost", "missing"):
        condition = BookCopyStatus.LOST
    else:
        await update.effective_message.reply_text(
            "❌ Invalid condition. Must be 'good', 'damaged', or 'lost'."
        )
        return

    notes = " ".join(context.args[2:]).strip() if len(context.args) > 2 else None

    with get_db_session() as session:
        try:
            rental = confirm_rental_return(
                session=session,
                rental_id=rental_id,
                actor_telegram_id=user_id,
                condition_status=condition,
                damage_notes=notes,
            )
            book_title = (
                html.escape(rental.copy.book.title)
                if rental.copy and rental.copy.book
                else "Book"
            )
            barcode = rental.copy.barcode if rental.copy else "N/A"
            reconciliation = get_rental_financial_reconciliation(session, rental.id)

            status_notes = ""
            if condition == BookCopyStatus.ON_SHELF:
                status_notes = "✅ Copy returned to <b>ON_SHELF</b> inventory and is available for rental."
            elif condition == BookCopyStatus.DAMAGED:
                status_notes = "⚠️ Copy marked <b>DAMAGED</b> and quarantined from circulation."
            elif condition == BookCopyStatus.LOST:
                status_notes = "🚨 Copy marked <b>LOST</b> and removed from available circulation."

            msg = (
                f"📚 <b>Physical Return Confirmed: Rental #{rental.id} Closed</b>\n\n"
                f"• Book: <i>{book_title}</i>\n"
                f"• Physical Copy: <code>{barcode}</code>\n"
                f"• Inspected Condition: <b>{condition.value}</b>\n"
                f"• Recorded Return Time: {rental.return_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"{status_notes}\n\n"
                f"<b>Financial Reconciliation Summary:</b>\n"
                f"• Rental Fee: {reconciliation['original_rental_fee']} ETB\n"
                f"• Collateral Received: {reconciliation['monetary_collateral_received']} ETB "
                f"({'Guarantee: ' + reconciliation['guarantee_details'] if reconciliation['has_non_cash_guarantee'] else ''})\n"
                f"• Extension Fee Paid: {reconciliation['extension_fee_paid']} ETB\n"
                f"• Overdue Duration: {reconciliation['overdue_days']} day(s)\n"
                f"• Total Overdue Fees Accrued: <b>{reconciliation['accrued_overdue_charges']} ETB</b>\n"
                f"• Net Remaining Collateral: <b>{reconciliation['net_collateral_remaining']} ETB</b>\n\n"
                f"<i>Overdue charge accrual has permanently stopped for this rental.</i>"
            )
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)

            await notify_customer(
                bot=context.bot,
                customer_telegram_id=rental.customer.telegram_id,
                event_key="notify_return_confirmed_cust",
                rental_id=rental.id,
                book_title=rental.copy.book.title,
                condition=condition.value,
            )
            if reconciliation.get("net_collateral_remaining", Decimal("0.00")) > Decimal("0.00") and not reconciliation.get("has_non_cash_guarantee", False):
                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=rental.customer.telegram_id,
                    event_key="notify_refund_cust",
                    amount=str(reconciliation["net_collateral_remaining"]),
                    rental_id=rental.id,
                )

        except RentalNotFoundError:
            await update.effective_message.reply_text(f"❌ Rental #{rental_id} was not found.")
        except RentalAlreadyReturnedError:
            await update.effective_message.reply_text(f"ℹ️ Rental #{rental_id} has already been returned.")
        except InvalidReturnConditionError as exc:
            await update.effective_message.reply_text(f"❌ {html.escape(str(exc))}")


async def returndeduct_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only handler: Confirm return with an authorized collateral deduction."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to library owners.")
        return

    if not context.args or len(context.args) < 4:
        await update.effective_message.reply_text(
            "⚠️ <b>Usage:</b> <code>/returndeduct &lt;rental_id&gt; &lt;good|damaged|lost&gt; &lt;deduction_amount&gt; &lt;reason&gt;</code>\n"
            "Example: <code>/returndeduct 1 damaged 150 Torn binding replacement fee</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        rental_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Rental ID must be an integer.")
        return

    raw_cond = context.args[1].lower()
    if raw_cond in ("good", "on_shelf", "ok"):
        condition = BookCopyStatus.ON_SHELF
    elif raw_cond in ("damaged", "damage"):
        condition = BookCopyStatus.DAMAGED
    elif raw_cond in ("lost",):
        condition = BookCopyStatus.LOST
    else:
        await update.effective_message.reply_text("❌ Invalid condition. Must be 'good', 'damaged', or 'lost'.")
        return

    try:
        deduction_amt = Decimal(context.args[2])
    except (InvalidOperation, ValueError):
        await update.effective_message.reply_text("❌ Deduction amount must be a valid numeric Decimal.")
        return

    reason = " ".join(context.args[3:]).strip()
    if not reason:
        await update.effective_message.reply_text("❌ Reason is required for collateral deduction.")
        return

    with get_db_session() as session:
        try:
            rental = confirm_rental_return(
                session=session,
                rental_id=rental_id,
                actor_telegram_id=user_id,
                condition_status=condition,
                collateral_deduction=deduction_amt,
                deduction_reason=reason,
            )
            reconciliation = get_rental_financial_reconciliation(session, rental.id)
            await update.effective_message.reply_text(
                f"✅ <b>Return & Collateral Deduction Confirmed!</b>\n\n"
                f"• Rental ID: <b>#{rental.id}</b>\n"
                f"• Copy Condition: <b>{condition.value}</b>\n"
                f"• Authorized Deduction: <b>{deduction_amt} ETB</b>\n"
                f"• Reason: <i>{html.escape(reason)}</i>\n"
                f"• Net Remaining Cash Collateral: <b>{reconciliation['net_collateral_remaining']} ETB</b>",
                parse_mode=ParseMode.HTML,
            )
            await notify_customer(
                bot=context.bot,
                customer_telegram_id=rental.customer.telegram_id,
                event_key="notify_deduction_cust",
                amount=str(deduction_amt),
                rental_id=rental.id,
                reason=reason,
            )
            await notify_customer(
                bot=context.bot,
                customer_telegram_id=rental.customer.telegram_id,
                event_key="notify_return_confirmed_cust",
                rental_id=rental.id,
                book_title=rental.copy.book.title,
                condition=condition.value,
            )
        except RentalNotFoundError:
            await update.effective_message.reply_text(f"❌ Rental #{rental_id} not found.")
        except RentalAlreadyReturnedError:
            await update.effective_message.reply_text(f"ℹ️ Rental #{rental_id} has already been returned.")
        except InsufficientCollateralError as exc:
            await update.effective_message.reply_text(f"⛔ Cannot deduct collateral: {html.escape(str(exc))}")
        except Exception as exc:
            await update.effective_message.reply_text(f"❌ Error: {html.escape(str(exc))}")


async def reconcile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only handler: View complete financial reconciliation for a rental."""
    if not update.effective_message or not update.effective_user:
        return

    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.effective_message.reply_text("⛔ Unauthorized: This command is restricted to library owners.")
        return

    if not context.args or len(context.args) < 1:
        await update.effective_message.reply_text("⚠️ <b>Usage:</b> <code>/reconcile &lt;rental_id&gt;</code>", parse_mode=ParseMode.HTML)
        return

    try:
        rental_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Rental ID must be an integer.")
        return

    with get_db_session() as session:
        try:
            rec = get_rental_financial_reconciliation(session, rental_id)
            guarantee_str = f"Yes ({rec['guarantee_details']})" if rec["has_non_cash_guarantee"] else "None (Cash Only)"
            return_str = rec["return_time"].strftime("%Y-%m-%d %H:%M UTC") if rec["return_time"] else "Not Returned (Active)"

            msg = (
                f"📊 <b>Financial Reconciliation — Rental #{rec['rental_id']}</b>\n\n"
                f"• Book: <i>{html.escape(rec['book_title'])}</i> (<code>{rec['copy_barcode']}</code>)\n"
                f"• Customer ID: #{rec['customer_id']}\n"
                f"• Status: <b>{rec['status']}</b> | Return: {return_str}\n\n"
                f"<b>Revenue & Fees:</b>\n"
                f"• Rental Fee: {rec['original_rental_fee']} ETB\n"
                f"• Extension Fee Paid: {rec['extension_fee_paid']} ETB\n"
                f"• Overdue Duration: {rec['overdue_days']} day(s)\n"
                f"• Accrued Overdue Fees: <b>{rec['accrued_overdue_charges']} ETB</b> (5 ETB/day)\n\n"
                f"<b>Collateral Accounting:</b>\n"
                f"• Monetary Collateral Received: {rec['monetary_collateral_received']} ETB\n"
                f"• Non-Cash Guarantee: {html.escape(guarantee_str)}\n"
                f"• Collateral Deductions: {rec['collateral_deductions']} ETB\n"
                f"• Collateral Refunds: {rec['collateral_refunds']} ETB\n"
                f"• <b>Net Remaining Collateral:</b> <b>{rec['net_collateral_remaining']} ETB</b>\n\n"
                f"<b>Outstanding Balance:</b> {rec['unpaid_overdue_balance']} ETB"
            )
            await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)
        except RentalNotFoundError:
            await update.effective_message.reply_text(f"❌ Rental #{rental_id} was not found.")


async def extension_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query handler for owner approval/rejection buttons on rental extension requests."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    try:
        action, ext_id_str = query.data.split(":", 1)
        ext_id = int(ext_id_str)
    except (ValueError, TypeError):
        await query.answer("Invalid callback data.", show_alert=True)
        return

    with get_db_session() as session:
        try:
            if action in ("approve_ext_cash", "approve_ext_bank"):
                pmethod = PaymentMethod.CASH if action == "approve_ext_cash" else PaymentMethod.BANK_TRANSFER
                ext = verify_and_approve_extension(
                    session=session,
                    extension_id=ext_id,
                    payment_method=pmethod,
                    actor_telegram_id=user_id,
                    reference="Approved via button",
                )
                await query.answer(f"Extension #{ext.id} approved!")
                new_text = (
                    f"✅ <b>Approved: Extension #{ext.id}</b>\n"
                    f"• Rental ID: #{ext.rental_id}\n"
                    f"• Payment Verified: 10.00 ETB via {pmethod.value}\n"
                    f"• New Return Deadline: {ext.new_due_date.strftime('%Y-%m-%d %H:%M UTC')}"
                )
                await query.edit_message_text(new_text, parse_mode=ParseMode.HTML)

                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=ext.rental.customer.telegram_id,
                    event_key="notify_ext_approved_cust",
                    rental_id=ext.rental_id,
                    due_date=ext.new_due_date.strftime("%Y-%m-%d %H:%M UTC"),
                )

            elif action == "reject_ext":
                ext = reject_rental_extension(
                    session=session,
                    extension_id=ext_id,
                    actor_telegram_id=user_id,
                    reason="Rejected via button",
                )
                await query.answer(f"Extension #{ext.id} rejected.")
                new_text = (
                    f"❌ <b>Rejected: Extension #{ext.id}</b>\n"
                    f"• Rental ID: #{ext.rental_id}\n"
                    f"Due date remains unchanged."
                )
                await query.edit_message_text(new_text, parse_mode=ParseMode.HTML)

                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=ext.rental.customer.telegram_id,
                    event_key="notify_ext_rejected_cust",
                    rental_id=ext.rental_id,
                    due_date=ext.rental.due_date.strftime("%Y-%m-%d %H:%M UTC"),
                    reason_line="Reason: Rejected via button",
                )

        except ExtensionNotFoundError:
            await query.answer("Extension request not found.", show_alert=True)
            await query.edit_message_text("❌ Extension request no longer exists.")
        except ExtensionAlreadyAppliedError:
            await query.answer("Notice: Extension already processed.", show_alert=False)
            await query.edit_message_text("ℹ️ Extension request has already been applied.")
        except Exception as exc:
            await query.answer(f"Error: {exc}", show_alert=True)


async def owner_return_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query handler for owner return action buttons (good, damaged, lost, reconcile, ret_select)."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Unauthorized: Owner access required.", show_alert=True)
        return

    data = query.data
    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE

        if data.startswith("ret_select:"):
            _, _, id_str = data.partition(":")
            if not id_str.isdigit():
                return
            rental_id = int(id_str)
            rental = session.get(Rental, rental_id)
            if not rental:
                await query.answer("Rental not found.", show_alert=True)
                return

            b_title = rental.copy.book.title if rental.copy and rental.copy.book else "Book"
            barcode = rental.copy.barcode if rental.copy else "N/A"
            c_name = rental.customer.first_name if rental.customer else "Customer"
            msg = (
                f"📦 <b>Process Return for Rental #{rental.id}</b>\n\n"
                f"• <b>Book:</b> <i>{html.escape(b_title)}</i>\n"
                f"• <b>Barcode:</b> <code>{barcode}</code>\n"
                f"• <b>Customer:</b> {html.escape(c_name)} (ID: #{rental.customer_id})\n"
                f"• <b>Due Date:</b> {rental.due_date.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
                f"Please inspect the physical book condition and select an action below:"
            )
            await query.edit_message_text(
                msg,
                reply_markup=get_owner_return_action_keyboard(lang, rental.id),
                parse_mode=ParseMode.HTML,
            )
            return

        if data.startswith("ret_act:"):
            parts = data.split(":")
            if len(parts) < 3:
                await query.answer("Invalid callback format.", show_alert=True)
                return

            sub_action = parts[1]
            if sub_action == "reconcile":
                if not parts[2].isdigit():
                    await query.answer("Invalid rental ID.", show_alert=True)
                    return
                rental_id = int(parts[2])
                try:
                    rec = get_rental_financial_reconciliation(session, rental_id)
                    guarantee_str = f"Yes ({rec['guarantee_details']})" if rec["has_non_cash_guarantee"] else "None (Cash Only)"
                    return_str = rec["return_time"].strftime("%Y-%m-%d %H:%M UTC") if rec["return_time"] else "Not Returned (Active)"
                    msg = (
                        f"📊 <b>Financial Reconciliation — Rental #{rec['rental_id']}</b>\n\n"
                        f"• Book: <i>{html.escape(rec['book_title'])}</i> (<code>{rec['copy_barcode']}</code>)\n"
                        f"• Status: <b>{rec['status']}</b> | Return: {return_str}\n\n"
                        f"• Rental Fee: {rec['original_rental_fee']} ETB\n"
                        f"• Extension Fee: {rec['extension_fee_paid']} ETB\n"
                        f"• Overdue Duration: {rec['overdue_days']} day(s) ({rec['accrued_overdue_charges']} ETB)\n"
                        f"• Net Remaining Collateral: <b>{rec['net_collateral_remaining']} ETB</b>\n"
                        f"• Non-Cash Guarantee: {html.escape(guarantee_str)}"
                    )
                    await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
                except RentalNotFoundError:
                    await query.answer("Rental not found.", show_alert=True)
                return

            if sub_action == "prompt_deduct":
                if len(parts) < 4 or not parts[3].isdigit():
                    await query.answer("Invalid callback format.", show_alert=True)
                    return
                action = parts[2]
                rental_id = int(parts[3])
                rec = get_rental_financial_reconciliation(session, rental_id)
                cond_title = "DAMAGED" if action == "damaged" else "LOST"
                deduct_help = (
                    f"📝 <b>Authorize Collateral Deduction — Rental #{rec['rental_id']}</b>\n\n"
                    f"• Book: <i>{html.escape(rec['book_title'])}</i>\n"
                    f"• Inspected Condition: <b>{cond_title}</b>\n"
                    f"• Net Remaining Collateral: <b>{rec['net_collateral_remaining']} ETB</b>\n\n"
                    f"To record an authorized deduction with audit logging, send:\n"
                    f"<code>/returndeduct {rental_id} {action} &lt;amount&gt; &lt;reason&gt;</code>\n\n"
                    f"<b>Example:</b>\n"
                    f"<code>/returndeduct {rental_id} {action} 150 Torn binding replacement fee</code>\n\n"
                    f"Or tap below to confirm return without deducting collateral:"
                )
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Confirm Return (No Deduction)", callback_data=f"ret_act:confirm_nodeduct:{action}:{rental_id}"),
                    ],
                    [
                        InlineKeyboardButton("⬅️ Back to Return Review", callback_data=f"ret_act:{action}:{rental_id}"),
                    ],
                ])
                await query.edit_message_text(deduct_help, reply_markup=kb, parse_mode=ParseMode.HTML)
                return

            is_no_deduct_confirm = False
            if sub_action == "confirm_nodeduct":
                if len(parts) < 4 or not parts[3].isdigit():
                    await query.answer("Invalid callback format.", show_alert=True)
                    return
                action = parts[2]
                rental_id = int(parts[3])
                is_no_deduct_confirm = True
            else:
                action = sub_action
                if not parts[2].isdigit():
                    await query.answer("Invalid callback format.", show_alert=True)
                    return
                rental_id = int(parts[2])

            cond_map = {
                "good": BookCopyStatus.ON_SHELF,
                "damaged": BookCopyStatus.DAMAGED,
                "lost": BookCopyStatus.LOST,
            }
            condition = cond_map.get(action)
            if not condition:
                await query.answer("Unknown return action.", show_alert=True)
                return

            # Selecting Damaged or Lost must NOT automatically deduct or forfeit collateral.
            # Show pre-return financial reconciliation summary before finalizing, and ask owner to authorize deduction.
            if action in ("damaged", "lost") and not is_no_deduct_confirm:
                try:
                    rec = get_rental_financial_reconciliation(session, rental_id)
                except RentalNotFoundError:
                    await query.answer("Rental not found.", show_alert=True)
                    return

                rental_obj = session.get(Rental, rental_id)
                c_name = f"{rental_obj.customer.first_name} (ID: #{rental_obj.customer_id})" if rental_obj and rental_obj.customer else f"Customer #{rec['customer_id']}"
                guarantee_str = f"Yes ({rec['guarantee_details']})" if rec["has_non_cash_guarantee"] else "None (Cash Deposit)"
                cond_title = "DAMAGED" if action == "damaged" else "LOST"
                prompt_msg = (
                    f"⚠️ <b>Return Inspection: Book Marked as {cond_title}</b>\n\n"
                    f"<b>📊 Pre-Return Reconciliation Summary (Rental #{rec['rental_id']}):</b>\n"
                    f"• Book: <i>{html.escape(rec['book_title'])}</i> (<code>{rec['copy_barcode']}</code>)\n"
                    f"• Customer: {html.escape(c_name)}\n"
                    f"• Original Rental Fee: {rec['original_rental_fee']} ETB\n"
                    f"• Accrued Overdue Charges: {rec['accrued_overdue_charges']} ETB ({rec['overdue_days']} days)\n"
                    f"• Monetary Collateral Deposited: {rec['monetary_collateral_received']} ETB\n"
                    f"• Net Remaining Cash Collateral: <b>{rec['net_collateral_remaining']} ETB</b>\n"
                    f"• Non-Cash Guarantee: {html.escape(guarantee_str)}\n\n"
                    f"🛡️ <b>Collateral Protection Rule:</b>\n"
                    f"Marking a book as {cond_title} does <b>NOT</b> automatically deduct or forfeit collateral.\n"
                    f"Any deduction requires explicit owner authorization with an exact amount and recorded reason.\n\n"
                    f"<i>Choose how to proceed:</i>\n"
                    f"• <b>Confirm (No Deduction):</b> Close return as {cond_title} and refund net remaining collateral normally.\n"
                    f"• <b>Authorize Deduction:</b> Send <code>/returndeduct {rental_id} {action} &lt;amount&gt; &lt;reason&gt;</code>"
                )
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Confirm Return (No Deduction)", callback_data=f"ret_act:confirm_nodeduct:{action}:{rental_id}"),
                    ],
                    [
                        InlineKeyboardButton("📝 Authorize Deduction", callback_data=f"ret_act:prompt_deduct:{action}:{rental_id}"),
                    ],
                    [
                        InlineKeyboardButton("⬅️ Back to Condition Menu", callback_data=f"ret_select:{rental_id}"),
                    ],
                ])
                await query.edit_message_text(prompt_msg, reply_markup=kb, parse_mode=ParseMode.HTML)
                return

            notes = f"Returned via {action} button" + (" (no deduction)" if is_no_deduct_confirm else "")
            try:
                rental = confirm_rental_return(
                    session=session,
                    rental_id=rental_id,
                    actor_telegram_id=user_id,
                    condition_status=condition,
                    damage_notes=notes,
                )
                b_title = rental.copy.book.title if rental.copy and rental.copy.book else "Book"
                reconciliation = get_rental_financial_reconciliation(session, rental.id)
                msg = (
                    f"📚 <b>Physical Return Confirmed: Rental #{rental.id} Closed</b>\n\n"
                    f"• Book: <i>{html.escape(b_title)}</i>\n"
                    f"• Inspected Condition: <b>{condition.value}</b>\n"
                    f"• Recorded Return Time: {rental.return_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                    f"• Total Overdue Fees Accrued: <b>{reconciliation['accrued_overdue_charges']} ETB</b>\n"
                    f"• Net Remaining Collateral: <b>{reconciliation['net_collateral_remaining']} ETB</b>"
                )
                await query.edit_message_text(msg, parse_mode=ParseMode.HTML)

                await notify_customer(
                    bot=context.bot,
                    customer_telegram_id=rental.customer.telegram_id,
                    event_key="notify_return_confirmed_cust",
                    rental_id=rental.id,
                    book_title=b_title,
                    condition=condition.value,
                )
                if reconciliation.get("net_collateral_remaining", Decimal("0.00")) > Decimal("0.00") and not reconciliation.get("has_non_cash_guarantee", False):
                    await notify_customer(
                        bot=context.bot,
                        customer_telegram_id=rental.customer.telegram_id,
                        event_key="notify_refund_cust",
                        amount=str(reconciliation["net_collateral_remaining"]),
                        rental_id=rental.id,
                    )
            except RentalAlreadyReturnedError:
                await query.answer("Notice: Rental already returned.", show_alert=False)
                await query.edit_message_text("ℹ️ Rental has already been returned.")
            except Exception as exc:
                logger.error("Error in owner_return_action_callback: %s", exc, exc_info=True)
                await query.answer(f"Error: {exc}", show_alert=True)



# ==============================================================================
# Customer & Admin Reply Keyboard Button Handler
# ==============================================================================


async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages from customer and admin reply keyboards."""
    if not update.effective_message or not update.effective_message.text or not update.effective_user:
        return

    text = update.effective_message.text.strip()
    user_id = update.effective_user.id

    with get_db_session() as session:
        lang = get_customer_language(session, user_id) or DEFAULT_LANGUAGE
        customer = get_customer_by_telegram_id(session, user_id)

    # Intercept query if user is in an active search mode
    user_data = getattr(context, "user_data", None)
    awaiting_search = user_data.get("awaiting_search_mode") if isinstance(user_data, dict) else None
    if awaiting_search and not text.startswith(("/", "⬅️", "❌", "➕", "👥", "🚫", "📚", "📝", "💳", "⏳", "⚠️", "📦", "📊", "❓", "🌐", "🔎", "📋")):
        user_data.pop("awaiting_search_mode", None)
        with get_db_session() as session:
            results = search_books(session, text, limit=10)
            if not results:
                await update.effective_message.reply_text(
                    f"🔍 No books found matching '<b>{html.escape(text)}</b>'. Try another keyword or browse all books.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📚 Browse All Books" if lang == "en" else "📚 ሁሉንም ተመልከት", callback_data="search_mode:browse"),
                    ]]),
                    parse_mode=ParseMode.HTML,
                )
                return

            response_lines = [f"📚 <b>Search Results for '{html.escape(text)}' ({len(results)}):</b>\n"]
            buttons = []
            for book in results:
                avail = book["available_copies"]
                stock_indicator = f"🟢 <b>{avail} available</b>" if avail > 0 else "🔴 <i>Out of stock</i>"
                card = (
                    f"📖 <b>{html.escape(book['title'])}</b>\n"
                    f"• Author: <b>{html.escape(book['author'])}</b>\n"
                    f"• ISBN: <code>{book['isbn']}</code>\n"
                    f"• Category: {html.escape(book['category'] or 'General')} | Pages: {book['page_count'] or 'N/A'}\n"
                    f"• Rental Fee: <b>${book['rental_price']}</b>\n"
                    f"• Physical Copies: {stock_indicator} ({book['total_copies']} total)\n"
                )
                response_lines.append(card)
                short_title = book['title'][:22] + "..." if len(book['title']) > 22 else book['title']
                if avail > 0:
                    buttons.append([
                        InlineKeyboardButton(
                            f"📖 Request '{short_title}'" if lang == "en" else f"📖 ተዋስ '{short_title}'",
                            callback_data=f"req_book:{book['id']}",
                        )
                    ])
                else:
                    buttons.append([
                        InlineKeyboardButton(
                            f"🔴 '{short_title}' (Out of Stock)" if lang == "en" else f"🔴 '{short_title}' (አልቋል)",
                            callback_data=f"book_oos:{book['id']}",
                        )
                    ])

            kb = InlineKeyboardMarkup(buttons) if buttons else None
            await update.effective_message.reply_text("\n".join(response_lines), reply_markup=kb, parse_mode=ParseMode.HTML)
            return

    # Clear awaiting search mode if user selected a different menu action
    if isinstance(user_data, dict):
        user_data.pop("awaiting_search_mode", None)

    # 1. Change Language button (accessible by both admins and customers)
    if text in (
        t("btn_change_language", "en"),
        t("btn_change_language", "am"),
        "🌐 Change Language",
        "🌐 ቋንቋ ቀይር",
    ):
        await language_command(update, context)
        return

    # 2. Administrator Navigation Buttons
    if is_owner(user_id):
        if text in (
            t("btn_admin_add_book", "en"),
            t("btn_admin_add_book", "am"),
            "➕ Add New Book",
            "➕ አዲስ መጽሐፍ ጨምር",
            t("btn_admin_books", "en"),
            t("btn_admin_books", "am"),
            "📚 Manage Books & Stock",
            "📚 መጻሕፍትና ክምችት ማስተዳደር",
        ):
            return await start_add_book_flow(update, context)

        if text in (
            t("btn_admin_pending", "en"),
            t("btn_admin_pending", "am"),
            "👥 Pending Customers",
            "👥 በመጠባበቅ ላይ ያሉ ደንበኞች",
        ):
            await pending_command(update, context)
            return

        if text in (
            t("btn_admin_rejected", "en"),
            t("btn_admin_rejected", "am"),
            "🚫 Rejected Customers",
            "🚫 የተከለከሉ ደንበኞች",
        ):
            await rejected_customers_command(update, context)
            return

        if text in (
            t("btn_admin_requests", "en"),
            t("btn_admin_requests", "am"),
            "📝 Rental Requests",
            "📝 የኪራይ ጥያቄዎች",
        ):
            await update.effective_message.reply_text(t("desc_admin_requests", lang), parse_mode=ParseMode.HTML)
            await requests_command(update, context)
            return

        if text in (
            t("btn_admin_payments", "en"),
            t("btn_admin_payments", "am"),
            "💳 Payment Verification",
            "💳 የክፍያ ማረጋገጫ",
        ):
            await update.effective_message.reply_text(t("desc_admin_payments", lang), parse_mode=ParseMode.HTML)
            return

        if text in (
            t("btn_admin_extensions", "en"),
            t("btn_admin_extensions", "am"),
            "⏳ Extension Requests",
            "⏳ የማራዘሚያ ጥያቄዎች",
        ):
            await extensions_command(update, context)
            return

        if text in (
            t("btn_admin_overdue", "en"),
            t("btn_admin_overdue", "am"),
            "⚠️ Overdue Rentals",
            "⚠️ ጊዜያቸው ያለፈባቸው",
        ):
            await overdue_command(update, context)
            return

        if text in (
            t("btn_admin_returns", "en"),
            t("btn_admin_returns", "am"),
            "📦 Confirm Returns",
            "📦 የመመለሻ ማረጋገጫ",
        ):
            await update.effective_message.reply_text(t("desc_admin_returns", lang), parse_mode=ParseMode.HTML)
            await return_command(update, context)
            return

        if text in (
            t("btn_admin_inventory", "en"),
            t("btn_admin_inventory", "am"),
            "📊 Inventory Summary",
            "📊 የክምችት ማጠቃለያ",
        ):
            await inventory_command(update, context)
            return

        if text in (
            t("btn_admin_help", "en"),
            t("btn_admin_help", "am"),
            "❓ Admin Help",
            "❓ የአስተዳዳሪ እገዛ",
        ):
            await help_command(update, context)
            return

    # 3. Customer Navigation Buttons
    if text in (
        t("btn_cust_search", "en"),
        t("btn_cust_search", "am"),
        "🔎 Search Books",
        "🔎 መጻሕፍት ፈልግ",
        "🔎 Find a Book",
        "🔎 መጽሐፍ ፈልግ",
    ):
        if customer and customer.status != CustomerStatus.APPROVED.value:
            await update.effective_message.reply_text(
                t("action_not_permitted_status", lang, status=customer.status),
                parse_mode=ParseMode.HTML,
            )
            return
        await update.effective_message.reply_text(
            t("desc_cust_search", lang),
            reply_markup=get_book_search_menu_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )
        return

    if text in (
        t("btn_cust_browse", "en"),
        t("btn_cust_browse", "am"),
        "📚 Browse Books",
        "📚 መጻሕፍትን ተመልከት",
    ):
        if customer and customer.status != CustomerStatus.APPROVED.value:
            await update.effective_message.reply_text(
                t("action_not_permitted_status", lang, status=customer.status),
                parse_mode=ParseMode.HTML,
            )
            return
        await update.effective_message.reply_text(t("desc_cust_browse", lang), parse_mode=ParseMode.HTML)
        await books_command(update, context)
        return

    if text in (
        t("btn_cust_rent", "en"),
        t("btn_cust_rent", "am"),
        "📖 Request a Rental",
        "📖 የኪራይ ጥያቄ አቅርብ",
    ):
        if customer and customer.status != CustomerStatus.APPROVED.value:
            await update.effective_message.reply_text(
                t("action_not_permitted_status", lang, status=customer.status),
                parse_mode=ParseMode.HTML,
            )
            return
        await update.effective_message.reply_text(t("desc_cust_rent", lang), parse_mode=ParseMode.HTML)
        return

    if text in (
        t("btn_cust_myrentals", "en"),
        t("btn_cust_myrentals", "am"),
        "📋 My Rentals",
        "📋 ኪራዮቼ",
    ):
        await update.effective_message.reply_text(t("desc_cust_myrentals", lang), parse_mode=ParseMode.HTML)
        await myrentals_command(update, context)
        return

    if text in (
        t("btn_cust_extensions", "en"),
        t("btn_cust_extensions", "am"),
        "⏳ My Extensions",
        "⏳ የማራዘሚያ ጥያቄዎቼ",
    ):
        await update.effective_message.reply_text(t("desc_cust_extensions", lang), parse_mode=ParseMode.HTML)
        await myextensions_command(update, context)
        return

    if text in (
        t("btn_cust_help", "en"),
        t("btn_cust_help", "am"),
        "❓ Help",
        "❓ እገዛ",
    ):
        await help_command(update, context)
        return

    # 4. Fallback for unrecognized text
    await update.effective_message.reply_text(
        t("unexpected_text_guidance", lang), parse_mode=ParseMode.HTML
    )


# ==============================================================================
# Global Uncaught Error Handler
# ==============================================================================


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global uncaught exception handler to prevent bot crash and log errors safely."""
    logger.error("Exception while handling an update: %s", context.error, exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An unexpected internal error occurred while processing your request. "
                "Our engineers have been notified. Please try again shortly."
            )
        except Exception as send_err:
            logger.error("Failed to notify user about error: %s", send_err)
