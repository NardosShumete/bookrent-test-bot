"""Telegram bot initialization and handler registration."""

import logging
from typing import Optional
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)


from app.bot.handlers import (
    ADD_BOOK_AUTHOR,
    ADD_BOOK_CONFIRM,
    ADD_BOOK_COPIES,
    ADD_BOOK_ISBN,
    ADD_BOOK_METADATA,
    ADD_BOOK_PRICE,
    ADD_BOOK_TITLE,
    REG_CONFIRM,
    REG_CONSENT,
    REG_LOCATION,
    REG_PHONE,
    REG_PHOTO,
    add_book_author_handler,
    add_book_cancel_handler,
    add_book_confirm_handler,
    add_book_copies_handler,
    add_book_isbn_handler,
    add_book_metadata_handler,
    add_book_price_handler,
    add_book_title_handler,
    addbook_command,
    addbook_entry_command,
    admin_menu_back_callback,
    approve_command,
    approveext_command,
    approvereq_command,
    book_out_of_stock_callback,
    book_request_collateral_callback,
    book_request_select_callback,
    book_request_submit_callback,
    books_command,
    checkout_command,
    checkoverdue_command,
    customer_approval_callback,
    extend_command,
    extension_callback,
    extensions_command,
    global_error_handler,
    handle_menu_button,
    help_command,
    inventory_command,
    language_command,
    language_selection_callback,
    myextensions_command,
    myrentals_command,
    overdue_command,
    owner_request_action_callback,
    owner_return_action_callback,
    pending_command,
    ping_command,
    reapprove_customer_callback,
    receive_command,
    reconcile_command,
    recordguarantee_command,
    recordpayment_command,
    reg_cancel_command,
    reg_confirm_handler,
    reg_consent_handler,
    reg_location_handler,
    reg_location_text_handler,
    reg_phone_contact_handler,
    reg_phone_text_handler,
    reg_photo_handler,
    reg_photo_text_handler,
    register_command,
    reject_command,
    rejected_customers_command,
    rejected_page_callback,
    rejectext_command,
    rejectreq_command,
    rent_command,
    rental_request_callback,
    rental_request_cancel_callback,
    requests_command,
    return_command,
    returndeduct_command,
    search_command,
    search_mode_callback,
    start_add_book_flow,
    start_command,
    view_id_photo_callback,
)
from app.config import get_settings
from app.scheduler.overdue_job import setup_overdue_scheduler

logger = logging.getLogger(__name__)


def create_bot_application(token: Optional[str] = None) -> Application:
    """Build and configure the Telegram Bot Application.

    Registers customer workflows, owner administration commands,
    rental requests, payment verification, checkout handlers,
    overdue management, rental extensions, return processing,
    callback query handlers, persistent scheduler, and error handler.

    Args:
        token: Optional explicit bot token. Defaults to settings.raw_bot_token.

    Returns:
        Configured python-telegram-bot Application instance.
    """
    bot_token = token or get_settings().raw_bot_token

    request = HTTPXRequest(
        connection_pool_size=16,
        connect_timeout=20.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=10.0,
    )
    application = ApplicationBuilder().token(bot_token).request(request).build()

    # Phase 8: Multi-step customer registration & verification conversation
    registration_conversation = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("register", register_command),
            CallbackQueryHandler(language_selection_callback, pattern=r"^lang:"),
        ],
        states={
            REG_CONSENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_consent_handler),
            ],
            REG_PHOTO: [
                MessageHandler(filters.PHOTO, reg_photo_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_photo_text_handler),
            ],
            REG_PHONE: [
                MessageHandler(filters.CONTACT, reg_phone_contact_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_phone_text_handler),
            ],
            REG_LOCATION: [
                MessageHandler(filters.LOCATION, reg_location_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_location_text_handler),
            ],
            REG_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_confirm_handler),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", reg_cancel_command),
            CommandHandler("start", start_command),
            CommandHandler("register", register_command),
            MessageHandler(filters.Regex(r"^(Cancel|ሰርዝ|❌ Cancel|❌ ሰርዝ)$"), reg_cancel_command),
        ],
        allow_reentry=True,
    )
    application.add_handler(registration_conversation)
    application.add_handler(CommandHandler("cancel", reg_cancel_command))
    application.add_handler(CommandHandler("register", register_command))

    # Foundation commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("language", language_command))

    # Owner administration: customer approvals & rejections
    application.add_handler(CommandHandler("pending", pending_command))
    application.add_handler(CommandHandler("rejected", rejected_customers_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("reject", reject_command))

    # Guided owner workflow: Add New Book & Receive Stock
    add_book_conversation = ConversationHandler(
        entry_points=[
            CommandHandler("addbook", addbook_entry_command),
            MessageHandler(
                filters.Regex(
                    r"^(➕ Add New Book|➕ አዲስ መጽሐፍ ጨምር|📚 Manage Books & Stock|📚 መጻሕፍትና ክምችት ማስተዳደር)$"
                ),
                start_add_book_flow,
            ),
        ],
        states={
            ADD_BOOK_ISBN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_book_isbn_handler),
            ],
            ADD_BOOK_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_book_title_handler),
            ],
            ADD_BOOK_AUTHOR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_book_author_handler),
            ],
            ADD_BOOK_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_book_price_handler),
            ],
            ADD_BOOK_METADATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_book_metadata_handler),
            ],
            ADD_BOOK_COPIES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_book_copies_handler),
            ],
            ADD_BOOK_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_book_confirm_handler),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", add_book_cancel_handler),
            MessageHandler(filters.Regex(r"^(Cancel|ሰርዝ|❌ Cancel|❌ ሰርዝ)$"), add_book_cancel_handler),
        ],
        allow_reentry=True,
    )
    application.add_handler(add_book_conversation)

    # Owner administration: catalogue & inventory
    application.add_handler(CommandHandler("addbook", addbook_command))
    application.add_handler(CommandHandler("receive", receive_command))
    application.add_handler(CommandHandler("inventory", inventory_command))

    # Customer & catalogue discovery
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("books", books_command))

    # Customer rental requests & management
    application.add_handler(CommandHandler("rent", rent_command))
    application.add_handler(CommandHandler("myrentals", myrentals_command))
    application.add_handler(CommandHandler("extend", extend_command))
    application.add_handler(CommandHandler("myextensions", myextensions_command))

    # Role-aware overdue checks
    application.add_handler(CommandHandler("overdue", overdue_command))

    # Owner administration: rental requests, payments, and checkout
    application.add_handler(CommandHandler("requests", requests_command))
    application.add_handler(CommandHandler("approvereq", approvereq_command))
    application.add_handler(CommandHandler("rejectreq", rejectreq_command))
    application.add_handler(CommandHandler("recordpayment", recordpayment_command))
    application.add_handler(CommandHandler("recordguarantee", recordguarantee_command))
    application.add_handler(CommandHandler("checkout", checkout_command))

    # Owner administration: overdue, extensions, and return processing (Phase 5)
    application.add_handler(CommandHandler("checkoverdue", checkoverdue_command))
    application.add_handler(CommandHandler("extensions", extensions_command))
    application.add_handler(CommandHandler("approveext", approveext_command))
    application.add_handler(CommandHandler("rejectext", rejectext_command))
    application.add_handler(CommandHandler("return", return_command))
    application.add_handler(CommandHandler("returndeduct", returndeduct_command))
    application.add_handler(CommandHandler("reconcile", reconcile_command))

    # Callback queries (language selection, customer approvals, rejected pagination, reapprove, requests, extensions, ID photo)
    application.add_handler(
        CallbackQueryHandler(language_selection_callback, pattern=r"^lang:")
    )
    application.add_handler(
        CallbackQueryHandler(view_id_photo_callback, pattern=r"^view_id_photo:")
    )
    application.add_handler(
        CallbackQueryHandler(customer_approval_callback, pattern=r"^(approve_cust|reject_cust):")
    )
    application.add_handler(
        CallbackQueryHandler(rejected_page_callback, pattern=r"^admin_rejected_page:")
    )
    application.add_handler(
        CallbackQueryHandler(reapprove_customer_callback, pattern=r"^reapprove_cust:")
    )
    application.add_handler(
        CallbackQueryHandler(admin_menu_back_callback, pattern=r"^admin_menu_back$")
    )
    application.add_handler(
        CallbackQueryHandler(rental_request_callback, pattern=r"^(approve_req|reject_req|checkout_req):")
    )
    application.add_handler(
        CallbackQueryHandler(extension_callback, pattern=r"^(approve_ext_cash|approve_ext_bank|reject_ext):")
    )
    application.add_handler(
        CallbackQueryHandler(search_mode_callback, pattern=r"^search_mode:")
    )
    application.add_handler(
        CallbackQueryHandler(book_request_select_callback, pattern=r"^req_book:")
    )
    application.add_handler(
        CallbackQueryHandler(book_request_collateral_callback, pattern=r"^req_collat:")
    )
    application.add_handler(
        CallbackQueryHandler(book_request_submit_callback, pattern=r"^req_submit:")
    )
    application.add_handler(
        CallbackQueryHandler(book_out_of_stock_callback, pattern=r"^book_oos:")
    )
    application.add_handler(
        CallbackQueryHandler(rental_request_cancel_callback, pattern=r"^req_cancel$")
    )
    application.add_handler(
        CallbackQueryHandler(owner_request_action_callback, pattern=r"^req_act:")
    )
    application.add_handler(
        CallbackQueryHandler(owner_return_action_callback, pattern=r"^(ret_act:|ret_select:)")
    )

    # Reply keyboard navigation text buttons
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_button)
    )

    # Register background task scheduler (overdue daily check)
    setup_overdue_scheduler(application)

    # Register global uncaught error handler
    application.add_error_handler(global_error_handler)

    logger.info("Telegram Bot Application initialized successfully with Phase 8 handlers.")
    return application


