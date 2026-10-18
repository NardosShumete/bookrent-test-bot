"""Comprehensive tests for guided Telegram workflows:
- Owner guided book creation and inventory receiving
- Existing ISBN detection and copy addition
- Interactive back/cancel and invalid input handling
- Customer interactive search, browse, and inline rental requesting
- Collateral options and request confirmation
- Owner quick-action callbacks for requests (approve, pay, guarantee, handover)
- Interactive return workflows and financial reconciliation
- Unauthorized access and duplicate click handling
- Bilingual English and Amharic support
- Verification that legacy commands remain 100% operational
"""

from decimal import Decimal
import html
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.orm import Session
from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.ext import ConversationHandler

from app.bot.handlers import (
    ADD_BOOK_AUTHOR,
    ADD_BOOK_CONFIRM,
    ADD_BOOK_COPIES,
    ADD_BOOK_ISBN,
    ADD_BOOK_METADATA,
    ADD_BOOK_PRICE,
    ADD_BOOK_TITLE,
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
    book_out_of_stock_callback,
    book_request_collateral_callback,
    book_request_select_callback,
    book_request_submit_callback,
    books_command,
    handle_menu_button,
    owner_request_action_callback,
    owner_return_action_callback,
    receive_command,
    rent_command,
    requests_command,
    return_command,
    returndeduct_command,
    search_command,
    search_mode_callback,
    start_add_book_flow,
)
from app.models.book import Book
from app.models.customer import Customer
from app.models.enums import BookCopyStatus, CollateralType, CustomerStatus, RentalRequestStatus, RentalStatus
from app.models.rental import Rental
from app.models.rental_request import RentalRequest
from app.services.book_catalog import create_book, receive_stock_for_isbn
from app.services.customer import register_customer, set_customer_language
from app.services.rental_request import (
    approve_rental_request,
    confirm_physical_handover,
    record_payment_verification,
    submit_rental_request,
)

OWNER_ID = 12345
CUSTOMER_ID = 8888
UNAPPROVED_CUSTOMER_ID = 9999
STRANGER_ID = 7777


def make_mock_msg_update(user_id: int, text: str = "", args: list = None, user_data: dict = None):
    """Create a mock Update and Context for text/command handler testing."""
    user = User(id=user_id, first_name="TestUser", is_bot=False, username="testuser")
    chat = Chat(id=user_id, type="private")
    message = AsyncMock(spec=Message)
    message.text = text
    message.reply_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message
    update.callback_query = None

    context = MagicMock()
    context.args = args or []
    context.user_data = user_data if user_data is not None else {}
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    return update, context


def make_mock_query_update(user_id: int, data: str):
    """Create a mock Update and Context for callback query handler testing."""
    user = User(id=user_id, first_name="TestUser", is_bot=False)
    query = AsyncMock(spec=CallbackQuery)
    query.from_user = user
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = AsyncMock(spec=Message)
    query.message.reply_text = AsyncMock()
    query.message.edit_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.effective_user = user
    update.callback_query = query
    update.effective_message = query.message

    context = MagicMock()
    context.args = []
    context.user_data = {}
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    return update, context


# ==============================================================================
# 1. Guided Owner Add Book Workflow
# ==============================================================================


@pytest.mark.asyncio
async def test_guided_add_book_full_flow(db_session: Session, valid_env_vars: dict) -> None:
    """Test full 7-step guided owner conversation to add a new book title and copies."""
    # 0. Entry
    u0, ctx0 = make_mock_msg_update(OWNER_ID, "/addbook")
    next_state = await addbook_entry_command(u0, ctx0)
    assert next_state == ADD_BOOK_ISBN
    assert "ISBN" in u0.effective_message.reply_text.call_args[0][0]

    # Step 1: Valid ISBN
    u1, ctx1 = make_mock_msg_update(OWNER_ID, "978-0-13-235088-4", user_data=ctx0.user_data)
    next_state = await add_book_isbn_handler(u1, ctx1)
    assert next_state == ADD_BOOK_TITLE
    assert "title" in u1.effective_message.reply_text.call_args[0][0].lower()

    # Step 2: Title
    u2, ctx2 = make_mock_msg_update(OWNER_ID, "Clean Code Guided", user_data=ctx1.user_data)
    next_state = await add_book_title_handler(u2, ctx2)
    assert next_state == ADD_BOOK_AUTHOR
    assert "author" in u2.effective_message.reply_text.call_args[0][0].lower()

    # Step 3: Author
    u3, ctx3 = make_mock_msg_update(OWNER_ID, "Robert C. Martin", user_data=ctx2.user_data)
    next_state = await add_book_author_handler(u3, ctx3)
    assert next_state == ADD_BOOK_PRICE
    assert "rental fee" in u3.effective_message.reply_text.call_args[0][0].lower()

    # Step 4: Rental Price
    u4, ctx4 = make_mock_msg_update(OWNER_ID, "12.50", user_data=ctx3.user_data)
    next_state = await add_book_price_handler(u4, ctx4)
    assert next_state == ADD_BOOK_METADATA

    # Step 5: Optional Metadata
    u5, ctx5 = make_mock_msg_update(OWNER_ID, "Programming | 464 | Software Craftsmanship", user_data=ctx4.user_data)
    next_state = await add_book_metadata_handler(u5, ctx5)
    assert next_state == ADD_BOOK_COPIES
    assert "copies" in u5.effective_message.reply_text.call_args[0][0].lower()

    # Step 6: Copies quantity
    u6, ctx6 = make_mock_msg_update(OWNER_ID, "3", user_data=ctx5.user_data)
    next_state = await add_book_copies_handler(u6, ctx6)
    assert next_state == ADD_BOOK_CONFIRM
    summary_text = u6.effective_message.reply_text.call_args[0][0]
    assert "Clean Code Guided" in summary_text
    assert "Robert C. Martin" in summary_text
    assert "12.50" in summary_text

    # Step 7: Final Confirmation
    u7, ctx7 = make_mock_msg_update(OWNER_ID, "✅ Confirm & Save", user_data=ctx6.user_data)
    next_state = await add_book_confirm_handler(u7, ctx7)
    assert next_state == ConversationHandler.END
    success_text = u7.effective_message.reply_text.call_args[0][0]
    assert "Added Successfully" in success_text
    assert "3 copies" in success_text

    # Verify database state
    db_session.expire_all()
    book = db_session.query(Book).filter(Book.isbn == "9780132350884").first()
    assert book is not None
    assert book.title == "Clean Code Guided"
    assert len(book.copies) == 3
    assert all(c.status == BookCopyStatus.ON_SHELF.value for c in book.copies)


@pytest.mark.asyncio
async def test_guided_add_book_existing_isbn_offers_add_copies(db_session: Session, valid_env_vars: dict) -> None:
    """When an existing ISBN is entered, bot detects it and allows adding copies directly."""
    # Pre-catalogue a book
    create_book(db_session, "9780306406157", "Existing Book", "Old Author", Decimal("5.00"), actor_telegram_id=OWNER_ID)
    receive_stock_for_isbn(db_session, "9780306406157", 2, actor_telegram_id=OWNER_ID)
    db_session.commit()

    u1, ctx1 = make_mock_msg_update(OWNER_ID, "978-0-306-40615-7")
    next_state = await add_book_isbn_handler(u1, ctx1)
    # Immediately jumps to ADD_BOOK_COPIES
    assert next_state == ADD_BOOK_COPIES
    reply_text = u1.effective_message.reply_text.call_args[0][0]
    assert "Already Catalogued" in reply_text
    assert "Existing Book" in reply_text

    # Owner adds 4 more copies
    u2, ctx2 = make_mock_msg_update(OWNER_ID, "4", user_data=ctx1.user_data)
    next_state = await add_book_copies_handler(u2, ctx2)
    assert next_state == ADD_BOOK_CONFIRM

    # Confirm
    u3, ctx3 = make_mock_msg_update(OWNER_ID, "✅ Confirm & Save", user_data=ctx2.user_data)
    next_state = await add_book_confirm_handler(u3, ctx3)
    assert next_state == ConversationHandler.END

    db_session.expire_all()
    book = db_session.query(Book).filter(Book.isbn == "9780306406157").first()
    assert len(book.copies) == 6


@pytest.mark.asyncio
async def test_guided_add_book_validation_back_and_cancel(db_session: Session, valid_env_vars: dict) -> None:
    """Test validation errors, Back button navigation, and Cancel operation."""
    # Non-owner blocked
    u_stranger, ctx_stranger = make_mock_msg_update(STRANGER_ID, "/addbook")
    assert await start_add_book_flow(u_stranger, ctx_stranger) == ConversationHandler.END
    assert "restricted" in u_stranger.effective_message.reply_text.call_args[0][0]

    # Invalid ISBN
    u_inv, ctx_inv = make_mock_msg_update(OWNER_ID, "not-an-isbn")
    assert await add_book_isbn_handler(u_inv, ctx_inv) == ADD_BOOK_ISBN
    assert "Invalid ISBN" in u_inv.effective_message.reply_text.call_args[0][0]

    # Valid ISBN, proceed to title
    u_isbn, ctx_isbn = make_mock_msg_update(OWNER_ID, "978-0-13-449416-6")
    assert await add_book_isbn_handler(u_isbn, ctx_isbn) == ADD_BOOK_TITLE

    # Back from Title returns to ISBN
    u_back, ctx_back = make_mock_msg_update(OWNER_ID, "⬅️ Back", user_data=ctx_isbn.user_data)
    assert await add_book_title_handler(u_back, ctx_back) == ADD_BOOK_ISBN

    # Cancel resets state
    u_cancel, ctx_cancel = make_mock_msg_update(OWNER_ID, "❌ Cancel", user_data={"add_book_isbn": "9780134494166"})
    assert await add_book_cancel_handler(u_cancel, ctx_cancel) == ConversationHandler.END
    assert "cancelled" in u_cancel.effective_message.reply_text.call_args[0][0].lower()
    assert len(ctx_cancel.user_data) == 0


@pytest.mark.asyncio
async def test_legacy_commands_remain_functional(db_session: Session, valid_env_vars: dict) -> None:
    """Legacy pipe /addbook and /receive commands work identically for power users."""
    u1, ctx1 = make_mock_msg_update(
        OWNER_ID,
        "/addbook",
        args=["978-0-201-61622-4", "|", "The Pragmatic Programmer", "|", "Hunt & Thomas", "|", "16.00"],
    )
    res = await addbook_entry_command(u1, ctx1)
    assert res == ConversationHandler.END
    assert "Book Catalogued Successfully" in u1.effective_message.reply_text.call_args[0][0]

    u2, ctx2 = make_mock_msg_update(OWNER_ID, "/receive", args=["978-0-201-61622-4", "5"])
    await receive_command(u2, ctx2)
    assert "Stock Received Successfully" in u2.effective_message.reply_text.call_args[0][0]


# ==============================================================================
# 2. Customer Interactive Search & Rental Request Workflows
# ==============================================================================


@pytest.mark.asyncio
async def test_customer_interactive_search_and_rent(db_session: Session, valid_env_vars: dict) -> None:
    """Customer searches catalogue, selects book via inline button, picks collateral, and confirms."""
    # Setup approved customer and a book with stock
    cust, _ = register_customer(db_session, telegram_id=CUSTOMER_ID, first_name="Abebe")
    cust.status = CustomerStatus.APPROVED.value
    book = create_book(db_session, "9780131103627", "The C Programming Language", "Kernighan & Ritchie", Decimal("8.00"), actor_telegram_id=OWNER_ID)
    receive_stock_for_isbn(db_session, "9780131103627", 2, actor_telegram_id=OWNER_ID)
    db_session.commit()

    # 1. Customer runs /search without args -> prompts search menu
    u_s, ctx_s = make_mock_msg_update(CUSTOMER_ID, "")
    await search_command(u_s, ctx_s)
    reply_text = u_s.effective_message.reply_text.call_args[0][0]
    reply_kw = u_s.effective_message.reply_text.call_args[1]
    assert "Find a Book in the Catalogue" in reply_text
    assert reply_kw["reply_markup"] is not None

    # 2. Customer clicks Title search mode
    u_mode, ctx_mode = make_mock_query_update(CUSTOMER_ID, "search_mode:title")
    await search_mode_callback(u_mode, ctx_mode)
    assert ctx_mode.user_data.get("awaiting_search_mode") == "title"

    # 3. Customer types title keyword "Programming"
    u_type, ctx_type = make_mock_msg_update(CUSTOMER_ID, "Programming", user_data=ctx_mode.user_data)
    await handle_menu_button(u_type, ctx_type)
    assert "The C Programming Language" in u_type.effective_message.reply_text.call_args[0][0]
    # Verify inline request button is attached
    kb = u_type.effective_message.reply_text.call_args[1]["reply_markup"]
    assert any(btn.callback_data == f"req_book:{book.id}" for row in kb.inline_keyboard for btn in row)

    # 4. Customer clicks 'Request This Book'
    u_sel, ctx_sel = make_mock_query_update(CUSTOMER_ID, f"req_book:{book.id}")
    await book_request_select_callback(u_sel, ctx_sel)
    collat_text = u_sel.callback_query.message.reply_text.call_args[0][0]
    assert "Request to Rent" in collat_text
    assert "The C Programming Language" in collat_text

    # 5. Customer picks National ID Guarantee collateral
    u_collat, ctx_collat = make_mock_query_update(CUSTOMER_ID, f"req_collat:guarantee:{book.id}")
    await book_request_collateral_callback(u_collat, ctx_collat)
    review_text = u_collat.callback_query.message.reply_text.call_args[0][0]
    assert "Review Rental Request" in review_text
    assert "National ID / Document Guarantee" in review_text

    # 6. Customer confirms submission
    u_sub, ctx_sub = make_mock_query_update(CUSTOMER_ID, f"req_submit:guarantee:{book.id}")
    await book_request_submit_callback(u_sub, ctx_sub)
    u_sub.callback_query.message.edit_text.assert_awaited()
    assert "Rental Request Submitted Successfully" in u_sub.callback_query.message.edit_text.call_args[0][0]

    # Verify request in database
    db_session.expire_all()
    req = db_session.query(RentalRequest).filter(RentalRequest.customer_id == cust.id).first()
    assert req is not None
    assert req.status == RentalRequestStatus.SUBMITTED.value


@pytest.mark.asyncio
async def test_customer_out_of_stock_inline_behavior(db_session: Session, valid_env_vars: dict) -> None:
    """When a book has 0 copies, it shows out-of-stock badge and answers alert without creating request."""
    cust, _ = register_customer(db_session, telegram_id=CUSTOMER_ID, first_name="Abebe")
    cust.status = CustomerStatus.APPROVED.value
    book = create_book(db_session, "9780262033848", "Introduction to Algorithms", "CLRS", Decimal("25.00"), actor_telegram_id=OWNER_ID)
    db_session.commit()

    u_oos, ctx_oos = make_mock_query_update(CUSTOMER_ID, f"book_oos:{book.id}")
    await book_out_of_stock_callback(u_oos, ctx_oos)
    u_oos.callback_query.answer.assert_awaited_with(
        "⚠️ This title is currently out of stock. Please check back later or choose another title.",
        show_alert=True,
    )

    # No request created
    assert db_session.query(RentalRequest).count() == 0


@pytest.mark.asyncio
async def test_unapproved_customer_cannot_request_via_button(db_session: Session, valid_env_vars: dict) -> None:
    """Unapproved customer clicking request callback is blocked with an alert."""
    cust, _ = register_customer(db_session, telegram_id=UNAPPROVED_CUSTOMER_ID, first_name="PendingUser")
    book = create_book(db_session, "9780132350884", "Clean Code", "Robert Martin", Decimal("10.00"), actor_telegram_id=OWNER_ID)
    receive_stock_for_isbn(db_session, "9780132350884", 1, actor_telegram_id=OWNER_ID)
    db_session.commit()

    u_query, ctx_query = make_mock_query_update(UNAPPROVED_CUSTOMER_ID, f"req_book:{book.id}")
    await book_request_select_callback(u_query, ctx_query)
    u_query.callback_query.answer.assert_awaited()
    alert_text = u_query.callback_query.answer.call_args[0][0]
    assert "APPROVED" in alert_text


# ==============================================================================
# 3. Owner Quick-Action Workflows (Approval, Payments, Returns)
# ==============================================================================


@pytest.mark.asyncio
async def test_owner_quick_action_request_approval_and_handover(db_session: Session, valid_env_vars: dict) -> None:
    """Owner approves request, records cash fee and guarantee via inline buttons, and hands over book."""
    cust, _ = register_customer(db_session, telegram_id=CUSTOMER_ID, first_name="Abebe")
    cust.status = CustomerStatus.APPROVED.value
    book = create_book(db_session, "9780132350884", "Clean Code", "Robert Martin", Decimal("10.00"), actor_telegram_id=OWNER_ID)
    receive_stock_for_isbn(db_session, "9780132350884", 1, actor_telegram_id=OWNER_ID)
    req = submit_rental_request(db_session, cust.id, book.id)
    db_session.commit()

    # 1. Owner clicks Approve
    u1, ctx1 = make_mock_query_update(OWNER_ID, f"req_act:approve:{req.id}")
    await owner_request_action_callback(u1, ctx1)
    u1.callback_query.edit_message_text.assert_awaited()
    assert "APPROVED" in u1.callback_query.edit_message_text.call_args[0][0].upper()

    # 2. Owner verifies fee via Cash button
    u2, ctx2 = make_mock_query_update(OWNER_ID, f"req_act:pay_cash:{req.id}")
    await owner_request_action_callback(u2, ctx2)
    assert "Fee Verified" in u2.callback_query.edit_message_text.call_args[0][0]

    # 3. Owner records non-cash guarantee via button
    u3, ctx3 = make_mock_query_update(OWNER_ID, f"req_act:guarantee:{req.id}")
    await owner_request_action_callback(u3, ctx3)
    assert "Guarantee Verified" in u3.callback_query.edit_message_text.call_args[0][0]

    # 4. Owner confirms physical handover
    u4, ctx4 = make_mock_query_update(OWNER_ID, f"req_act:handover:{req.id}")
    await owner_request_action_callback(u4, ctx4)
    assert "Physical Handover Confirmed" in u4.callback_query.edit_message_text.call_args[0][0]

    # Verify rental is active in DB
    db_session.expire_all()
    rental = db_session.query(Rental).filter(Rental.customer_id == cust.id).first()
    assert rental is not None
    assert rental.status == RentalStatus.ACTIVE.value
    assert rental.copy.status == BookCopyStatus.RENTED.value


@pytest.mark.asyncio
async def test_owner_return_interactive_flow(db_session: Session, valid_env_vars: dict) -> None:
    """Owner lists active rentals via /return, inspects rental, and confirms return in good condition."""
    cust, _ = register_customer(db_session, telegram_id=CUSTOMER_ID, first_name="Abebe")
    cust.status = CustomerStatus.APPROVED.value
    book = create_book(db_session, "9780132350884", "Clean Code", "Robert Martin", Decimal("10.00"), actor_telegram_id=OWNER_ID)
    receive_stock_for_isbn(db_session, "9780132350884", 1, actor_telegram_id=OWNER_ID)
    req = submit_rental_request(db_session, cust.id, book.id)
    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    record_payment_verification(db_session, req.id, "RENTAL_FEE", "CASH", req.rental_fee, actor_telegram_id=OWNER_ID)
    record_payment_verification(db_session, req.id, "COLLATERAL_DEPOSIT", "CASH", Decimal("50.00"), actor_telegram_id=OWNER_ID)
    rental = confirm_physical_handover(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.commit()

    # 1. Owner runs /return with no args -> lists active rentals
    u_ret, ctx_ret = make_mock_msg_update(OWNER_ID, "/return")
    await return_command(u_ret, ctx_ret)
    assert "Active Rentals to Return" in u_ret.effective_message.reply_text.call_args[0][0]
    kb = u_ret.effective_message.reply_text.call_args[1]["reply_markup"]
    assert any(f"ret_select:{rental.id}" in btn.callback_data for row in kb.inline_keyboard for btn in row)

    # 2. Owner selects rental to return
    u_sel, ctx_sel = make_mock_query_update(OWNER_ID, f"ret_select:{rental.id}")
    await owner_return_action_callback(u_sel, ctx_sel)
    assert "Process Return" in u_sel.callback_query.edit_message_text.call_args[0][0]

    # 3. Owner clicks 'Return (Good Condition)'
    u_good, ctx_good = make_mock_query_update(OWNER_ID, f"ret_act:good:{rental.id}")
    await owner_return_action_callback(u_good, ctx_good)
    return_summary = u_good.callback_query.edit_message_text.call_args[0][0]
    assert "Physical Return Confirmed" in return_summary

    # Verify rental is closed and copy is ON_SHELF
    db_session.expire_all()
    closed_rental = db_session.get(Rental, rental.id)
    assert closed_rental.status == RentalStatus.RETURNED.value
    assert closed_rental.copy.status == BookCopyStatus.ON_SHELF.value


@pytest.mark.asyncio
async def test_owner_action_blocked_for_non_owners(db_session: Session, valid_env_vars: dict) -> None:
    """Non-owners tapping owner quick-action buttons receive an authorization error."""
    u_req, ctx_req = make_mock_query_update(STRANGER_ID, "req_act:approve:1")
    await owner_request_action_callback(u_req, ctx_req)
    u_req.callback_query.answer.assert_awaited_with("⛔ Unauthorized: Owner access required.", show_alert=True)

    u_ret, ctx_ret = make_mock_query_update(STRANGER_ID, "ret_act:good:1")
    await owner_return_action_callback(u_ret, ctx_ret)
    u_ret.callback_query.answer.assert_awaited_with("⛔ Unauthorized: Owner access required.", show_alert=True)


@pytest.mark.asyncio
async def test_guided_add_book_amharic(db_session: Session, valid_env_vars: dict) -> None:
    """Owner with Amharic language preference sees Amharic guided prompts."""
    set_customer_language(db_session, telegram_id=OWNER_ID, language="am", first_name="Admin")
    db_session.flush()

    u0, ctx0 = make_mock_msg_update(OWNER_ID, "/addbook")
    next_state = await addbook_entry_command(u0, ctx0)
    assert next_state == ADD_BOOK_ISBN
    assert "የመጽሐፉ ISBN" in u0.effective_message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_customer_interactive_search_amharic(db_session: Session, valid_env_vars: dict) -> None:
    """Approved customer with Amharic preference sees Amharic search options."""
    cust, _ = register_customer(db_session, telegram_id=CUSTOMER_ID, first_name="Abebe")
    cust.status = CustomerStatus.APPROVED.value
    cust.language = "am"
    db_session.flush()

    u_s, ctx_s = make_mock_msg_update(CUSTOMER_ID, "")
    await search_command(u_s, ctx_s)
    reply_text = u_s.effective_message.reply_text.call_args[0][0]
    assert "በካታሎግ ውስጥ መጽሐፍ ይፈልጉ" in reply_text


@pytest.mark.asyncio
async def test_manage_books_and_stock_button_triggers_guided_add_book_flow(
    db_session: Session, valid_env_vars: dict
) -> None:
    """The '📚 Manage Books & Stock' button triggers the exact same guided flow as /addbook."""
    # English test
    set_customer_language(db_session, telegram_id=OWNER_ID, language="en", first_name="Admin")
    db_session.flush()

    u_en, ctx_en = make_mock_msg_update(OWNER_ID, "📚 Manage Books & Stock")
    state_en = await handle_menu_button(u_en, ctx_en)
    assert state_en == ADD_BOOK_ISBN
    text_en = u_en.effective_message.reply_text.call_args[0][0]
    assert "Step 1 of 6: Book ISBN" in text_en
    assert "/addbook" in text_en
    assert "/receive" in text_en

    # Amharic test
    set_customer_language(db_session, telegram_id=OWNER_ID, language="am", first_name="Admin")
    db_session.flush()

    u_am, ctx_am = make_mock_msg_update(OWNER_ID, "📚 መጻሕፍትና ክምችት ማስተዳደር")
    state_am = await handle_menu_button(u_am, ctx_am)
    assert state_am == ADD_BOOK_ISBN
    text_am = u_am.effective_message.reply_text.call_args[0][0]
    assert "ደረጃ 1 ከ 6፦ የመጽሐፉ ISBN" in text_am
    assert "/addbook" in text_am
    assert "/receive" in text_am


@pytest.mark.asyncio
async def test_add_book_skip_isbn_explains_schema_limitation(
    db_session: Session, valid_env_vars: dict
) -> None:
    """Tapping Skip on ISBN step explains schema limitation and proposes smallest safe change."""
    set_customer_language(db_session, telegram_id=OWNER_ID, language="en", first_name="Admin")
    db_session.flush()

    u0, ctx0 = make_mock_msg_update(OWNER_ID, "/addbook")
    state0 = await addbook_entry_command(u0, ctx0)
    assert state0 == ADD_BOOK_ISBN

    # Verify visible Skip button is provided on reply markup
    kb = u0.effective_message.reply_text.call_args[1]["reply_markup"]
    skip_found = any("Skip" in btn.text or "እለፍ" in btn.text for row in kb.keyboard for btn in row)
    assert skip_found, "Visible Skip button must be provided for ISBN step"

    # Owner taps Skip
    u_skip, ctx_skip = make_mock_msg_update(OWNER_ID, "⏭️ Skip", user_data=ctx0.user_data)
    state_skip = await add_book_isbn_handler(u_skip, ctx_skip)
    assert state_skip == ADD_BOOK_ISBN
    skip_reply = u_skip.effective_message.reply_text.call_args[0][0]
    assert "Database Schema Limitation" in skip_reply
    assert "books.isbn NOT NULL UNIQUE" in skip_reply
    assert "Alembic" in skip_reply
    assert "nullable=True" in skip_reply


@pytest.mark.asyncio
async def test_add_book_optional_fields_stores_sql_null_not_string_null(
    db_session: Session, valid_env_vars: dict
) -> None:
    """Skipping or entering null on metadata fields stores actual NULL/None, never string 'null'."""
    set_customer_language(db_session, telegram_id=OWNER_ID, language="en", first_name="Admin")
    db_session.flush()

    # Step 1: ISBN
    ctx = {}
    u1, ctx1 = make_mock_msg_update(OWNER_ID, "978-0-13-110362-7", user_data=ctx)
    assert await add_book_isbn_handler(u1, ctx1) == ADD_BOOK_TITLE

    # Step 2: Title
    u2, ctx2 = make_mock_msg_update(OWNER_ID, "The C Programming Language", user_data=ctx)
    assert await add_book_title_handler(u2, ctx2) == ADD_BOOK_AUTHOR

    # Step 3: Author attempt to skip -> rejected because schema author is NOT NULL
    u3_skip, ctx3_skip = make_mock_msg_update(OWNER_ID, "⏭️ Skip", user_data=ctx)
    assert await add_book_author_handler(u3_skip, ctx3_skip) == ADD_BOOK_AUTHOR
    assert "Author is Mandatory" in u3_skip.effective_message.reply_text.call_args[0][0]

    # Step 3: Provide valid author
    u3, ctx3 = make_mock_msg_update(OWNER_ID, "Kernighan & Ritchie", user_data=ctx)
    assert await add_book_author_handler(u3, ctx3) == ADD_BOOK_PRICE

    # Step 4: Price
    u4, ctx4 = make_mock_msg_update(OWNER_ID, "20.00", user_data=ctx)
    assert await add_book_price_handler(u4, ctx4) == ADD_BOOK_METADATA

    # Step 5: Metadata with literal 'null' and 'none' strings
    u5, ctx5 = make_mock_msg_update(OWNER_ID, "Programming | null | None", user_data=ctx)
    assert await add_book_metadata_handler(u5, ctx5) == ADD_BOOK_COPIES
    assert ctx["add_book_category"] == "Programming"
    assert ctx["add_book_pages"] is None
    assert ctx["add_book_desc"] is None

    # Step 6: Copies
    u6, ctx6 = make_mock_msg_update(OWNER_ID, "2", user_data=ctx)
    assert await add_book_copies_handler(u6, ctx6) == ADD_BOOK_CONFIRM

    # Step 7: Confirm & Save
    u7, ctx7 = make_mock_msg_update(OWNER_ID, "✅ Confirm & Save", user_data=ctx)
    assert await add_book_confirm_handler(u7, ctx7) == ConversationHandler.END

    # Verify database model record has real SQL NULLs, NOT string "null"
    book = db_session.query(Book).filter(Book.isbn == "9780131103627").first()
    assert book is not None
    assert book.category == "Programming"
    assert book.page_count is None
    assert book.description is None
    assert book.page_count != "null"
    assert book.description != "null"
    assert book.description != "None"


@pytest.mark.asyncio
async def test_damaged_return_protects_collateral_requires_authorization(
    db_session: Session, valid_env_vars: dict
) -> None:
    """Selecting Damaged does not automatically deduct/forfeit collateral, displays reconciliation first."""
    # Setup approved customer, book, and rental with monetary collateral
    cust, _ = register_customer(db_session, telegram_id=CUSTOMER_ID, first_name="Abebe")
    cust.status = CustomerStatus.APPROVED.value
    book = create_book(db_session, "9780306406157", "Principles", "Kandel", Decimal("15.00"), actor_telegram_id=OWNER_ID)
    receive_stock_for_isbn(db_session, "9780306406157", 1, actor_telegram_id=OWNER_ID)
    req = submit_rental_request(db_session, cust.id, book.id, CollateralType.MONETARY)
    approve_rental_request(db_session, req.id, actor_telegram_id=OWNER_ID)
    record_payment_verification(db_session, req.id, "RENTAL_FEE", "CASH", Decimal("15.00"), actor_telegram_id=OWNER_ID)
    record_payment_verification(db_session, req.id, "COLLATERAL_DEPOSIT", "CASH", Decimal("200.00"), actor_telegram_id=OWNER_ID)
    rental = confirm_physical_handover(db_session, req.id, actor_telegram_id=OWNER_ID)
    db_session.flush()

    # Owner selects Damaged return action
    u_dam, ctx_dam = make_mock_query_update(OWNER_ID, f"ret_act:damaged:{rental.id}")
    await owner_return_action_callback(u_dam, ctx_dam)

    # Verify rental is STILL ACTIVE (not closed, no automatic collateral deduction!)
    db_session.expire_all()
    active_rental = db_session.get(Rental, rental.id)
    assert active_rental.status == RentalStatus.ACTIVE.value

    # Verify pre-return financial reconciliation summary is displayed
    card_text = u_dam.callback_query.edit_message_text.call_args[0][0]
    assert "Pre-Return Reconciliation Summary" in card_text
    assert "Collateral Protection Rule" in card_text
    assert "200.00 ETB" in card_text
    assert "automatically deduct or forfeit collateral" in card_text

    # Owner selects Confirm Return (No Deduction)
    u_confirm, ctx_confirm = make_mock_query_update(OWNER_ID, f"ret_act:confirm_nodeduct:damaged:{rental.id}")
    await owner_return_action_callback(u_confirm, ctx_confirm)

    # Verify rental is now closed, copy is DAMAGED, and collateral is preserved for refund
    db_session.expire_all()
    closed_rental = db_session.get(Rental, rental.id)
    assert closed_rental.status == RentalStatus.RETURNED.value
    assert closed_rental.copy.status == BookCopyStatus.DAMAGED.value
    summary_text = u_confirm.callback_query.edit_message_text.call_args[0][0]
    assert "Physical Return Confirmed" in summary_text
    assert "200.00 ETB" in summary_text


@pytest.mark.asyncio
async def test_repeated_confirmation_guard(db_session: Session, valid_env_vars: dict) -> None:
    """Repeatedly tapping Confirm & Save after context is cleared is safely guarded."""
    u_rep, ctx_rep = make_mock_msg_update(OWNER_ID, "✅ Confirm & Save", user_data={})
    state = await add_book_confirm_handler(u_rep, ctx_rep)
    assert state == ConversationHandler.END
    assert "already been processed" in u_rep.effective_message.reply_text.call_args[0][0]


