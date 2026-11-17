"""Menu-driven customer views and callbacks for the Telegram bot."""

import html
import hashlib
import math
from decimal import Decimal
from typing import Any, Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.database.session import get_db_session
from app.localization import (
    DEFAULT_LANGUAGE,
    get_customer_reply_keyboard,
    t,
)
from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import (
    BookCopyStatus,
    CustomerStatus,
    RentalRequestStatus,
)
from app.models.exceptions import (
    ActiveExtensionRequestExistsError,
    CopyNotAvailableError,
    CustomerNotApprovedError,
    CustomerNotFoundError,
    RentalNotActiveError,
    RentalNotFoundError,
    UnauthorizedError,
)
from app.models.ledger import CollateralLedger
from app.models.rental import Rental
from app.models.rental_request import RentalRequest
from app.services.customer import get_customer_by_telegram_id, get_customer_language
from app.services.ledger import get_customer_collateral_balance
from app.services.rental_request import submit_rental_request
from app.services.rental import submit_extension_request
from app.services.overdue import get_rental_overdue_summary


PAGE_SIZE = 5


def _remember_search_query(context: ContextTypes.DEFAULT_TYPE, query_text: str) -> str:
    token = hashlib.sha256(query_text.encode()).hexdigest()[:10]
    context.user_data.setdefault("customer_search_queries", {})[token] = query_text
    return token


def _lang(session: Any, user_id: int) -> str:
    return get_customer_language(session, user_id) or DEFAULT_LANGUAGE


def _customer_is_allowed(customer: Customer | None) -> bool:
    return bool(customer and customer.status == CustomerStatus.APPROVED.value)


def _navigation_keyboard(lang: str, *, back: str = "customer:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("btn_cust_back", lang), callback_data=back),
                InlineKeyboardButton(t("btn_cust_home", lang), callback_data="customer:home"),
            ]
        ]
    )


def _available_books(session: Any) -> list[Book]:
    books = session.query(Book).order_by(Book.title.asc()).all()
    return [
        book
        for book in books
        if any(copy.status == BookCopyStatus.ON_SHELF.value for copy in book.copies)
    ]


def _book_button(lang: str, book: Book) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        f"📖 {book.title[:30]}",
        callback_data=f"customer:book:{book.id}",
    )


def _book_page_keyboard(
    lang: str,
    page: int,
    pages: int,
    books: Iterable[Book],
    search_token: str | None = None,
) -> InlineKeyboardMarkup:
    rows = [
        [_book_button(lang, book)]
        for book in books
    ]
    controls: list[InlineKeyboardButton] = []
    callback_prefix = (
        f"customer:search:{search_token}:"
        if search_token is not None
        else "customer:books:"
    )
    if page > 1:
        controls.append(InlineKeyboardButton("⬅️", callback_data=f"{callback_prefix}{page - 1}"))
    if page < pages:
        controls.append(InlineKeyboardButton("➡️", callback_data=f"{callback_prefix}{page + 1}"))
    if controls:
        rows.append(controls)
    rows.append(
        [
            InlineKeyboardButton(t("btn_cust_home", lang), callback_data="customer:home"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _book_text(lang: str, book: Book, *, page: int, pages: int) -> str:
    available = sum(
        copy.status == BookCopyStatus.ON_SHELF.value for copy in book.copies
    )
    return (
        f"{t('cust_books_title', lang, page=page, pages=pages)}\n\n"
        f"📖 <b>{html.escape(book.title)}</b>\n"
        f"• {html.escape(book.author)}\n"
        f"• ISBN: <code>{html.escape(book.isbn)}</code>\n"
        f"• Available: <b>{available}</b>\n"
        f"• Rental fee: <b>{book.rental_price} ETB</b>\n"
        f"• Rental period: <b>10 days</b>"
    )


async def show_customer_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not user or not message:
        return
    with get_db_session() as session:
        lang = _lang(session, user.id)
        customer = get_customer_by_telegram_id(session, user.id)
    if not _customer_is_allowed(customer):
        return
    await message.reply_text(
        t("cust_home_prompt", lang),
        reply_markup=get_customer_reply_keyboard(lang),
    )


async def browse_books(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> None:
    user = update.effective_user
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not user or not message:
        return
    with get_db_session() as session:
        lang = _lang(session, user.id)
        customer = get_customer_by_telegram_id(session, user.id)
        if not _customer_is_allowed(customer):
            await message.reply_text(
                t(
                    "cust_status_required",
                    lang,
                    status=customer.status if customer else "UNREGISTERED",
                ),
                parse_mode=ParseMode.HTML,
            )
            return
        books = _available_books(session)
        pages = max(1, math.ceil(len(books) / PAGE_SIZE))
        page = max(1, min(page, pages))
        selected = books[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        if not selected:
            await message.reply_text(t("cust_no_books", lang), reply_markup=_navigation_keyboard(lang))
            return
        text = "\n\n".join(
            _book_text(lang, book, page=page, pages=pages) for book in selected
        )
        await message.reply_text(
            text,
            reply_markup=_book_page_keyboard(lang, page, pages, selected),
            parse_mode=ParseMode.HTML,
        )


async def customer_search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not user or not message:
        return
    with get_db_session() as session:
        lang = _lang(session, user.id)
        customer = get_customer_by_telegram_id(session, user.id)
    if not _customer_is_allowed(customer):
        await message.reply_text(t("cust_approved_required", lang))
        return
    context.user_data["customer_search"] = True
    await message.reply_text(
        f"{t('desc_cust_search', lang)}\n\n{t('cust_search_prompt', lang)}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("btn_cust_cancel", lang), callback_data="customer:cancel")]]
        ),
    )


async def customer_search_results(
    update: Update, context: ContextTypes.DEFAULT_TYPE, query_text: str, page: int = 1
) -> None:
    user = update.effective_user
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not user or not message:
        return
    with get_db_session() as session:
        lang = _lang(session, user.id)
        customer = get_customer_by_telegram_id(session, user.id)
        if not _customer_is_allowed(customer):
            return
        needle = f"%{query_text.strip()}%"
        books = (
            session.query(Book)
            .filter(
                Book.title.ilike(needle)
                | Book.author.ilike(needle)
                | Book.isbn.ilike(needle)
                | Book.category.ilike(needle)
            )
            .order_by(Book.title.asc())
            .all()
        )
        books = [
            book for book in books
            if any(copy.status == BookCopyStatus.ON_SHELF.value for copy in book.copies)
        ]
        if not books:
            await message.reply_text(
                t("cust_search_empty", lang, query=html.escape(query_text)),
                reply_markup=_navigation_keyboard(lang),
                parse_mode=ParseMode.HTML,
            )
            return
        pages = max(1, math.ceil(len(books) / PAGE_SIZE))
        page = max(1, min(page, pages))
        selected = books[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        text = "\n\n".join(
            _book_text(lang, book, page=page, pages=pages) for book in selected
        )
        await message.reply_text(
            text,
            reply_markup=_book_page_keyboard(
                lang,
                page,
                pages,
                selected,
                search_token=_remember_search_query(context, query_text.strip()),
            ),
            parse_mode=ParseMode.HTML,
        )


async def customer_book_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    user_id = query.from_user.id
    parts = query.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await query.answer(t("cust_invalid_book", DEFAULT_LANGUAGE), show_alert=True)
        return
    book_id = int(parts[2])
    with get_db_session() as session:
        lang = _lang(session, user_id)
        customer = get_customer_by_telegram_id(session, user_id)
        book = session.get(Book, book_id)
        if not _customer_is_allowed(customer) or book is None:
            await query.answer(t("cust_book_unavailable", lang), show_alert=True)
            return
        available = sum(
            copy.status == BookCopyStatus.ON_SHELF.value for copy in book.copies
        )
        if not available:
            await query.answer(t("cust_book_currently_unavailable", lang), show_alert=True)
            return
        description = html.escape(book.description or "No description available.")
        text = t(
            "cust_book_details",
            lang,
            title=html.escape(book.title),
            author=html.escape(book.author),
            isbn=html.escape(book.isbn),
            available=available,
            fee=book.rental_price,
            description=description,
        )
    await query.answer()
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t("btn_cust_request_rental", lang),
                        callback_data=f"customer:request:{book_id}",
                    )
                ],
                [
                    InlineKeyboardButton(t("btn_cust_back", lang), callback_data="customer:books:1"),
                    InlineKeyboardButton(t("btn_cust_home", lang), callback_data="customer:home"),
                ],
            ]
        ),
        parse_mode=ParseMode.HTML,
    )


async def customer_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    parts = query.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await query.answer(t("cust_invalid_request", DEFAULT_LANGUAGE), show_alert=True)
        return
    book_id = int(parts[2])
    with get_db_session() as session:
        lang = _lang(session, query.from_user.id)
        customer = get_customer_by_telegram_id(session, query.from_user.id)
        book = session.get(Book, book_id)
        duplicate = (
            session.query(RentalRequest)
            .filter(
                RentalRequest.customer_id == customer.id if customer else False,
                RentalRequest.book_id == book_id,
                RentalRequest.status.in_(
                    [RentalRequestStatus.SUBMITTED.value, RentalRequestStatus.APPROVED.value]
                ),
            )
            .first()
            if customer
            else None
        )
        if not _customer_is_allowed(customer) or book is None:
            await query.answer(t("cust_approved_required", lang), show_alert=True)
            return
        if duplicate:
            await query.answer(t("cust_pending_rental", lang), show_alert=True)
            return
        text = (
            t(
                "cust_rental_confirmation",
                lang,
                title=html.escape(book.title),
                fee=book.rental_price,
            )
        )
    await query.answer()
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t("btn_cust_confirm", lang),
                        callback_data=f"customer:confirm:{book_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        t("btn_cust_cancel", lang),
                        callback_data="customer:cancel",
                    )
                ],
            ]
        ),
        parse_mode=ParseMode.HTML,
    )


async def customer_confirm_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    book_id = int(query.data.rsplit(":", 1)[1])
    with get_db_session() as session:
        lang = _lang(session, query.from_user.id)
        customer = get_customer_by_telegram_id(session, query.from_user.id)
        if not _customer_is_allowed(customer):
            await query.answer(t("cust_approved_required", lang), show_alert=True)
            return
        duplicate = (
            session.query(RentalRequest)
            .filter(
                RentalRequest.customer_id == customer.id,
                RentalRequest.book_id == book_id,
                RentalRequest.status.in_(
                    [RentalRequestStatus.SUBMITTED.value, RentalRequestStatus.APPROVED.value]
                ),
            )
            .first()
        )
        if duplicate:
            await query.answer(t("cust_pending_rental", lang), show_alert=True)
            return
        try:
            request = submit_rental_request(
                session=session,
                customer_id=customer.id,
                book_id=book_id,
            )
        except CopyNotAvailableError:
            await query.answer(t("cust_book_allocated", lang), show_alert=True)
            return
    await query.answer()
    await query.edit_message_text(
        t("cust_request_submitted", lang, id=request.id),
        reply_markup=_navigation_keyboard(lang),
        parse_mode=ParseMode.HTML,
    )


async def customer_rentals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if not user or not message:
        return
    with get_db_session() as session:
        lang = _lang(session, user.id)
        customer = get_customer_by_telegram_id(session, user.id)
        if not _customer_is_allowed(customer):
            await message.reply_text(t("cust_rentals_approval_required", lang))
            return
        requests = (
            session.query(RentalRequest)
            .filter(
                RentalRequest.customer_id == customer.id,
                RentalRequest.status.in_(
                    [RentalRequestStatus.SUBMITTED.value, RentalRequestStatus.APPROVED.value]
                ),
            )
            .order_by(RentalRequest.created_at.desc())
            .all()
        )
        rentals = (
            session.query(Rental)
            .filter(Rental.customer_id == customer.id)
            .order_by(Rental.checkout_time.desc())
            .all()
        )
        lines = [t("cust_rentals_title", lang)]
        for request in requests:
            lines.append(
                f"⏳ Request #{request.id} — <i>{html.escape(request.book.title)}</i> "
                f"({request.status})"
            )
        for rental in rentals:
            title = html.escape(rental.copy.book.title) if rental.copy and rental.copy.book else "Book"
            due = rental.due_date.strftime("%Y-%m-%d")
            rental_line = (
                f"📖 Rental #{rental.id} — <i>{title}</i> — "
                f"{rental.status} — due {due}"
            )
            summary = get_rental_overdue_summary(session, rental.id)
            if summary["is_overdue"]:
                label = (
                    t("cust_overdue_recorded", lang)
                    if summary["charges"]
                    else t("cust_overdue_estimate", lang)
                )
                rental_line += t(
                    "cust_overdue_details",
                    lang,
                    days=summary["overdue_days"],
                    label=label,
                    amount=summary["total_overdue_fee"],
                )
            lines.append(rental_line)
        if not requests and not rentals:
            lines.append(t("cust_rentals_empty", lang))
        rental_buttons = [
            [
                InlineKeyboardButton(
                    t("btn_cust_rental_details", lang, id=rental.id),
                    callback_data=f"customer:rental:{rental.id}",
                )
            ]
            for rental in rentals
        ]
        await message.reply_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(
                rental_buttons
                + [[InlineKeyboardButton(t("btn_cust_home", lang), callback_data="customer:home")]]
            ),
            parse_mode=ParseMode.HTML,
        )


async def customer_rental_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    rental_id_text = query.data.rsplit(":", 1)[-1]
    if not rental_id_text.isdigit():
        await query.answer(t("cust_invalid_rental", DEFAULT_LANGUAGE), show_alert=True)
        return
    rental_id = int(rental_id_text)
    with get_db_session() as session:
        lang = _lang(session, query.from_user.id)
        rental = (
            session.query(Rental)
            .filter(Rental.id == rental_id)
            .join(Customer, Rental.customer_id == Customer.id)
            .filter(Customer.telegram_id == query.from_user.id)
            .first()
        )
        if rental is None:
            await query.answer(t("cust_rental_not_found", lang), show_alert=True)
            return
        title = html.escape(rental.copy.book.title) if rental.copy and rental.copy.book else "Book"
        text = t(
            "cust_rental_details",
            lang,
            id=rental.id,
            title=title,
            status=rental.status,
            due=rental.due_date.strftime("%Y-%m-%d"),
        )
        summary = get_rental_overdue_summary(session, rental.id)
        if summary["is_overdue"]:
            label = (
                t("cust_overdue_recorded", lang)
                if summary["charges"]
                else t("cust_overdue_estimate", lang)
            )
            text += t(
                "cust_overdue_details",
                lang,
                days=summary["overdue_days"],
                label=label,
                amount=summary["total_overdue_fee"],
            )
        buttons = []
        if rental.is_active:
            buttons.append(
                [
                    InlineKeyboardButton(
                        t("btn_cust_extend", lang),
                        callback_data=f"customer:extend:{rental.id}",
                    )
                ]
            )
        buttons.append([InlineKeyboardButton(t("btn_cust_home", lang), callback_data="customer:home")])
    await query.answer()
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )


async def customer_extension_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    rental_id_text = query.data.rsplit(":", 1)[-1]
    if not rental_id_text.isdigit():
        await query.answer(t("cust_invalid_rental", DEFAULT_LANGUAGE), show_alert=True)
        return
    rental_id = int(rental_id_text)
    try:
        with get_db_session() as session:
            extension = submit_extension_request(
                session=session,
                customer_telegram_id=query.from_user.id,
                rental_id=rental_id,
            )
            due_date = extension.new_due_date.strftime("%Y-%m-%d")
            lang = _lang(session, query.from_user.id)
    except (
        ActiveExtensionRequestExistsError,
        CustomerNotApprovedError,
        CustomerNotFoundError,
        RentalNotActiveError,
        RentalNotFoundError,
        UnauthorizedError,
    ) as exc:
        await query.answer(str(exc), show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        t("cust_extension_requested", lang, id=rental_id, due=due_date),
        reply_markup=_navigation_keyboard(lang),
        parse_mode=ParseMode.HTML,
    )


async def customer_payments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return
    with get_db_session() as session:
        lang = _lang(session, user.id)
        customer = get_customer_by_telegram_id(session, user.id)
        if not _customer_is_allowed(customer):
            await message.reply_text(t("cust_approved_required", lang))
            return
        entries = (
            session.query(CollateralLedger)
            .filter(CollateralLedger.customer_id == customer.id)
            .order_by(CollateralLedger.created_at.desc(), CollateralLedger.id.desc())
            .limit(50)
            .all()
        )
        balance = get_customer_collateral_balance(session, customer.id)
        lines = [
            t("cust_payments_title", lang),
            t("cust_payment_balance", lang, amount=balance),
            "",
        ]
        for entry in entries:
            lines.append(
                f"• {entry.created_at.strftime('%Y-%m-%d')} "
                f"<b>{entry.transaction_type.replace('_', ' ')}</b>: {entry.amount} ETB"
            )
        if not entries:
            lines.append(t("cust_payment_empty", lang))
        await message.reply_text(
            "\n".join(lines),
            reply_markup=_navigation_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )


async def customer_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return
    with get_db_session() as session:
        lang = _lang(session, user.id)
        customer = get_customer_by_telegram_id(session, user.id)
        if not customer:
            await message.reply_text(t("cust_profile_register", lang))
            return
        phone = customer.phone_number or "Not provided"
        if phone != "Not provided":
            phone = f"{phone[:4]}****{phone[-2:]}"
        text = (
            f"{t('cust_profile_title', lang)}\n\n"
            + t(
                "cust_profile_details",
                lang,
                name=html.escape(f"{customer.first_name} {customer.last_name or ''}"),
                status=customer.status,
                phone=html.escape(phone),
                registered=customer.created_at.strftime("%Y-%m-%d"),
                language=customer.language,
            )
        )
        await message.reply_text(
            text,
            reply_markup=_navigation_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )


async def customer_ui_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    if data == "customer:home":
        await query.answer()
        with get_db_session() as session:
            lang = _lang(session, query.from_user.id)
        await query.message.reply_text(
            t("cust_home_prompt", lang),
            reply_markup=get_customer_reply_keyboard(lang),
        )
    elif data == "customer:cancel":
        context.user_data.pop("customer_search", None)
        with get_db_session() as session:
            lang = _lang(session, query.from_user.id)
        await query.answer()
        await query.edit_message_text(
            t("cust_cancelled", lang),
            reply_markup=_navigation_keyboard(lang),
        )
    elif data.startswith("customer:books:"):
        await query.answer()
        page_text = data.rsplit(":", 1)[1]
        if not page_text.isdigit():
            await query.answer(t("cust_invalid_page", DEFAULT_LANGUAGE), show_alert=True)
            return
        page = int(page_text)
        await browse_books(update, context, page)
    elif data.startswith("customer:search:"):
        parts = data.split(":", 3)
        if len(parts) != 4 or not parts[3].isdigit():
            await query.answer(t("cust_invalid_page", DEFAULT_LANGUAGE), show_alert=True)
            return
        search_queries = context.user_data.get("customer_search_queries", {})
        query_text = search_queries.get(parts[2])
        if not query_text:
            await query.answer(t("cust_search_expired", DEFAULT_LANGUAGE), show_alert=True)
            return
        await query.answer()
        await customer_search_results(
            update,
            context,
            query_text,
            int(parts[3]),
        )
    elif data.startswith("customer:book:"):
        await customer_book_callback(update, context)
    elif data.startswith("customer:request:"):
        await customer_request_callback(update, context)
    elif data.startswith("customer:confirm:"):
        await customer_confirm_request_callback(update, context)
    elif data.startswith("customer:rental:"):
        await customer_rental_callback(update, context)
    elif data.startswith("customer:extend:"):
        await customer_extension_callback(update, context)
