"""Tests for the Phase 2 menu-driven customer interface."""

from decimal import Decimal
from datetime import datetime, timedelta, timezone
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import Session
from telegram import CallbackQuery, Chat, InlineKeyboardMarkup, Message, Update, User

from app.bot.customer_ui import (
    browse_books,
    customer_book_callback,
    customer_confirm_request_callback,
    customer_payments,
    customer_profile,
    customer_rental_callback,
    customer_search_results,
    customer_request_callback,
)
from app.bot.bot import create_bot_application
from app.bot.handlers import handle_menu_button
from app.localization import get_customer_reply_keyboard
from app.models.customer import Customer
from app.models.book import BookCopy
from app.models.enums import CustomerStatus, RentalStatus
from app.models.rental import Rental
from app.services.book_catalog import create_book, receive_stock_for_isbn
from app.services.customer import register_customer
from app.services.isbn import calculate_isbn13_check_digit
from app.services.ledger import record_ledger_entry
from app.models.enums import LedgerTransactionType
from app.services.rental_request import submit_rental_request


OWNER_ID = 12345


def make_message_update(user_id: int, text: str = ""):
    user = User(id=user_id, first_name="Reader", is_bot=False)
    message = AsyncMock(spec=Message)
    message.text = text
    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_message = message
    update.effective_chat = Chat(id=user_id, type="private")
    update.callback_query = None
    context = MagicMock()
    context.user_data = {}
    context.args = []
    return update, context


def make_callback_update(user_id: int, data: str):
    user = User(id=user_id, first_name="Reader", is_bot=False)
    query = AsyncMock(spec=CallbackQuery)
    query.from_user = user
    query.data = data
    query.message = AsyncMock(spec=Message)
    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_message = None
    update.callback_query = query
    context = MagicMock()
    context.user_data = {}
    return update, context


def approved_customer(session: Session, telegram_id: int = 7001) -> Customer:
    customer, _ = register_customer(session, telegram_id=telegram_id, first_name="Reader")
    customer.status = CustomerStatus.APPROVED.value
    customer.language = "en"
    session.flush()
    return customer


def catalog_book(session: Session, index: int = 0):
    isbn_prefix = f"9780306406{index:02d}"
    book = create_book(
        session,
        isbn=isbn_prefix + calculate_isbn13_check_digit(isbn_prefix),
        title=f"Book {index}",
        author="Author",
        rental_price=Decimal("10.00"),
        actor_telegram_id=OWNER_ID,
    )
    receive_stock_for_isbn(session, book.isbn, 1, actor_telegram_id=OWNER_ID)
    session.flush()
    return book


def callbacks(markup: InlineKeyboardMarkup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_customer_keyboard_contains_phase_2_menu() -> None:
    markup = get_customer_reply_keyboard("en")
    labels = [button.text for row in markup.keyboard for button in row]

    assert "📚 Browse Books" in labels
    assert "🔎 Search Books" in labels
    assert "📋 My Rentals" in labels
    assert "💰 My Payments" in labels
    assert "👤 My Profile" in labels
    assert "🌐 Change Language" in labels
    assert "❓ Help" in labels


def test_customer_rental_callbacks_are_registered(valid_env_vars: dict) -> None:
    application = create_bot_application()
    callback_patterns = [
        handler.pattern.pattern
        for handler in application.handlers[0]
        if hasattr(handler, "pattern") and handler.pattern is not None
    ]

    customer_pattern = next(pattern for pattern in callback_patterns if pattern.startswith("^customer:"))
    assert "rental:" in customer_pattern
    assert "extend:" in customer_pattern


@pytest.mark.asyncio
async def test_browse_books_paginates_and_hides_unavailable(
    db_session: Session, valid_env_vars: dict
) -> None:
    approved_customer(db_session)
    for index in range(6):
        catalog_book(db_session, index)
    unavailable = catalog_book(db_session, 10)
    db_session.query(BookCopy).filter(BookCopy.book_id == unavailable.id).first().status = "RENTED"
    db_session.commit()

    update, context = make_message_update(7001)
    await browse_books(update, context)

    text = update.effective_message.reply_text.call_args[0][0]
    markup = update.effective_message.reply_text.call_args.kwargs["reply_markup"]
    assert "Page 1/2" in text
    assert "Book 10" not in text
    assert "customer:books:2" in callbacks(markup)


@pytest.mark.asyncio
async def test_book_details_then_confirmation_and_duplicate_guard(
    db_session: Session, valid_env_vars: dict
) -> None:
    customer = approved_customer(db_session, 7002)
    book = catalog_book(db_session)

    details_update, details_context = make_callback_update(7002, f"customer:book:{book.id}")
    await customer_book_callback(details_update, details_context)
    details_markup = details_update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert f"customer:request:{book.id}" in callbacks(details_markup)

    request_update, request_context = make_callback_update(7002, f"customer:request:{book.id}")
    await customer_request_callback(request_update, request_context)
    confirm_markup = request_update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert f"customer:confirm:{book.id}" in callbacks(confirm_markup)

    confirm_update, confirm_context = make_callback_update(7002, f"customer:confirm:{book.id}")
    await customer_confirm_request_callback(confirm_update, confirm_context)
    assert "submitted" in confirm_update.callback_query.edit_message_text.call_args[0][0]

    duplicate_update, duplicate_context = make_callback_update(7002, f"customer:request:{book.id}")
    await customer_request_callback(duplicate_update, duplicate_context)
    duplicate_update.callback_query.answer.assert_awaited()
    assert "already" in duplicate_update.callback_query.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_conversational_search_payments_and_profile(
    db_session: Session, valid_env_vars: dict
) -> None:
    customer = approved_customer(db_session, 7003)
    customer.phone_number = "+251911223344"
    book = catalog_book(db_session)
    record_ledger_entry(
        db_session,
        customer.id,
        LedgerTransactionType.RENTAL_FEE,
        Decimal("10.00"),
        notes="test",
    )
    db_session.commit()

    prompt_update, context = make_message_update(7003, "🔎 Search Books")
    await handle_menu_button(prompt_update, context)
    assert "What book are you looking for" in prompt_update.effective_message.reply_text.call_args[0][0]
    assert context.user_data["customer_search"] is True

    result_update, result_context = make_message_update(7003, "Book 0")
    result_context.user_data = context.user_data
    await handle_menu_button(result_update, result_context)
    assert "Book 0" in result_update.effective_message.reply_text.call_args[0][0]

    payments_update, payments_context = make_message_update(7003, "💰 My Payments")
    await customer_payments(payments_update, payments_context)
    assert "RENTAL FEE" in payments_update.effective_message.reply_text.call_args[0][0]

    profile_update, profile_context = make_message_update(7003)
    await customer_profile(profile_update, profile_context)
    profile_text = profile_update.effective_message.reply_text.call_args[0][0]
    assert "+251****44" in profile_text
    assert "National ID" not in profile_text


@pytest.mark.asyncio
async def test_search_pagination_preserves_query_and_supports_author_and_isbn(
    db_session: Session, valid_env_vars: dict
) -> None:
    approved_customer(db_session, 7005)
    books = [catalog_book(db_session, index) for index in range(6)]
    books[0].author = "Unique Author"
    db_session.commit()

    first_update, first_context = make_message_update(7005)
    await customer_search_results(first_update, first_context, "Book", page=1)
    markup = first_update.effective_message.reply_text.call_args.kwargs["reply_markup"]
    search_callbacks = callbacks(markup)
    token = hashlib.sha256(b"Book").hexdigest()[:10]
    assert f"customer:search:{token}:2" in search_callbacks

    page_update, page_context = make_callback_update(7005, f"customer:search:{token}:2")
    page_context.user_data = first_context.user_data
    from app.bot.customer_ui import customer_ui_callback

    await customer_ui_callback(page_update, page_context)
    assert "Book 5" in page_update.callback_query.message.reply_text.call_args[0][0]

    page_update, page_context = make_callback_update(7005, f"customer:search:{token}:2")
    await customer_search_results(page_update, page_context, "Book", page=2)
    assert "Book 5" in page_update.callback_query.message.reply_text.call_args[0][0]

    author_update, author_context = make_message_update(7005)
    await customer_search_results(author_update, author_context, "Unique Author")
    assert "Book 0" in author_update.effective_message.reply_text.call_args[0][0]

    isbn_update, isbn_context = make_message_update(7005)
    await customer_search_results(isbn_update, isbn_context, books[0].isbn)
    assert "Book 0" in isbn_update.effective_message.reply_text.call_args[0][0]


def make_active_rental(session: Session, customer: Customer, book) -> Rental:
    copy = session.query(BookCopy).filter(BookCopy.book_id == book.id).first()
    assert copy is not None
    copy.status = "RENTED"
    now = datetime.now(timezone.utc)
    rental = Rental(
        copy_id=copy.id,
        customer_id=customer.id,
        checkout_time=now - timedelta(days=20),
        due_date=now - timedelta(days=3),
        status=RentalStatus.ACTIVE.value,
    )
    session.add(rental)
    session.flush()
    return rental


@pytest.mark.asyncio
async def test_rentals_display_overdue_estimate_without_ledger_write(
    db_session: Session, valid_env_vars: dict
) -> None:
    customer = approved_customer(db_session, 7006)
    book = catalog_book(db_session)
    rental = make_active_rental(db_session, customer, book)
    db_session.commit()

    before = len(customer.ledger_entries)
    update, context = make_message_update(7006, "📋 My Rentals")
    from app.bot.customer_ui import customer_rentals

    await customer_rentals(update, context)

    text = update.effective_message.reply_text.call_args[0][0]
    assert "OVERDUE" in text
    assert "day(s)" in text
    assert "ETB" in text
    db_session.refresh(customer)
    assert len(customer.ledger_entries) == before
    assert f"customer:rental:{rental.id}" in callbacks(
        update.effective_message.reply_text.call_args.kwargs["reply_markup"]
    )


@pytest.mark.asyncio
async def test_rental_callbacks_enforce_customer_ownership_and_approval(
    db_session: Session, valid_env_vars: dict
) -> None:
    owner = approved_customer(db_session, 7007)
    book = catalog_book(db_session)
    rental = make_active_rental(db_session, owner, book)
    unapproved = register_customer(
        db_session, telegram_id=7008, first_name="Pending"
    )[0]
    db_session.commit()

    unauthorized_update, unauthorized_context = make_callback_update(
        7008, f"customer:rental:{rental.id}"
    )
    await customer_rental_callback(unauthorized_update, unauthorized_context)
    assert unauthorized_update.callback_query.answer.call_args.kwargs["show_alert"] is True

    extension_update, extension_context = make_callback_update(
        7008, f"customer:extend:{rental.id}"
    )
    from app.bot.customer_ui import customer_extension_callback

    await customer_extension_callback(extension_update, extension_context)
    assert extension_update.callback_query.answer.call_args.kwargs["show_alert"] is True

    invalid_update, invalid_context = make_callback_update(7007, "customer:rental:not-an-id")
    await customer_rental_callback(invalid_update, invalid_context)
    assert invalid_update.callback_query.answer.call_args.kwargs["show_alert"] is True


@pytest.mark.asyncio
async def test_customer_confirmation_uses_amharic_translation(
    db_session: Session, valid_env_vars: dict
) -> None:
    customer = approved_customer(db_session, 7009)
    customer.language = "am"
    book = catalog_book(db_session)
    db_session.commit()

    update, context = make_callback_update(7009, f"customer:request:{book.id}")
    await customer_request_callback(update, context)

    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "የኪራይ ጥያቄ" in text
    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert any(
        button.text == "✅ አረጋግጥ"
        for row in markup.inline_keyboard
        for button in row
    )


@pytest.mark.asyncio
async def test_customer_callback_cannot_access_another_customer_book_request(
    db_session: Session, valid_env_vars: dict
) -> None:
    approved_customer(db_session, 7004)
    book = catalog_book(db_session)

    update, context = make_callback_update(7999, f"customer:request:{book.id}")
    await customer_request_callback(update, context)

    update.callback_query.answer.assert_awaited()
    assert update.callback_query.answer.call_args.kwargs["show_alert"] is True
