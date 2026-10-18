"""Centralized event notification service for BookRent Bot.

Handles dispatching localized Telegram alerts to customers and administrators
for all library lifecycle events with failure suppression, retry handling,
and sensitive data protection.
"""

import asyncio
import concurrent.futures
import inspect
import logging
from typing import Any, Dict, List, Optional
from telegram.constants import ParseMode
from telegram.error import TelegramError

from app.config import get_settings
from app.database.session import get_db_session
from app.localization import DEFAULT_LANGUAGE, t
from app.logging_config import SensitiveDataFilter
from app.services.customer import get_customer_language


logger = logging.getLogger(__name__)


def _dispatch_coroutine_safe(coro: Any) -> Any:
    """Execute an async coroutine safely across both sync and async contexts."""
    if inspect.iscoroutine(coro):
        try:
            loop = asyncio.get_running_loop()
            # If we're already running in an event loop, create a task or run via thread executor
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, coro).result(timeout=10)
        except RuntimeError:
            return asyncio.run(coro)
    return coro


async def _send_telegram_message_with_retry(
    bot: Any,
    chat_id: int,
    text: str,
    parse_mode: str = ParseMode.HTML,
    max_retries: int = 1,
) -> bool:
    """Send a Telegram message with optional retry and safe error suppression."""
    if not bot or not chat_id:
        return False

    attempts = max(1, max_retries + 1)
    for attempt in range(attempts):
        try:
            res = bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            if inspect.isawaitable(res):
                await res
            return True
        except TelegramError as tel_err:
            masked_chat = str(chat_id)[:4] + "****" if len(str(chat_id)) > 4 else "****"
            logger.warning(
                "Failed to deliver notification to chat %s (attempt %d/%d): %s",
                masked_chat,
                attempt + 1,
                attempts,
                tel_err,
            )
            if attempt < attempts - 1:
                await asyncio.sleep(0.5)
        except Exception as exc:
            logger.error("Unexpected error delivering notification: %s", exc)
            return False

    return False


async def notify_customer(
    bot: Any,
    customer_telegram_id: int,
    event_key: str,
    language: Optional[str] = None,
    **kwargs: Any,
) -> bool:
    """Dispatch a localized notification to a specific customer for a business event.

    Args:
        bot: python-telegram-bot Bot instance.
        customer_telegram_id: Recipient customer's Telegram user ID.
        event_key: Localization translation key (e.g. 'notify_customer_approved').
        language: Optional explicit language override; otherwise queried from DB.
        **kwargs: Formatting parameters passed to localization template.

    Returns:
        True if message was delivered successfully, False otherwise.
    """
    if bot is None or not customer_telegram_id:
        return False

    lang = language
    if not lang:
        try:
            with get_db_session() as session:
                lang = get_customer_language(session, customer_telegram_id) or DEFAULT_LANGUAGE
        except Exception as db_err:
            logger.warning("Could not query customer language for notification: %s", db_err)
            lang = DEFAULT_LANGUAGE

    message_text = t(event_key, lang, **kwargs)
    retries = get_settings().notification_retry_attempts
    return await _send_telegram_message_with_retry(
        bot=bot,
        chat_id=customer_telegram_id,
        text=message_text,
        max_retries=retries,
    )


async def notify_admins(
    bot: Any,
    event_key: str,
    admin_ids: Optional[List[int]] = None,
    **kwargs: Any,
) -> int:
    """Dispatch a localized notification to all configured administrators.

    Args:
        bot: python-telegram-bot Bot instance.
        event_key: Localization translation key (e.g. 'notify_new_registration_admin').
        admin_ids: Optional explicit admin IDs list; defaults to ADMIN_USER_IDS.
        **kwargs: Formatting parameters passed to localization template.

    Returns:
        Number of administrators successfully notified.
    """
    if bot is None:
        return 0

    target_admin_ids = admin_ids if admin_ids is not None else get_settings().admin_user_ids
    if not target_admin_ids:
        return 0

    success_count = 0
    retries = get_settings().notification_retry_attempts

    for admin_id in target_admin_ids:
        try:
            with get_db_session() as session:
                lang = get_customer_language(session, admin_id) or DEFAULT_LANGUAGE
        except Exception:
            lang = DEFAULT_LANGUAGE

        text = t(event_key, lang, **kwargs)
        sent = await _send_telegram_message_with_retry(
            bot=bot,
            chat_id=admin_id,
            text=text,
            max_retries=retries,
        )
        if sent:
            success_count += 1

    return success_count


def notify_customer_sync(
    bot: Any,
    customer_telegram_id: int,
    event_key: str,
    language: Optional[str] = None,
    **kwargs: Any,
) -> bool:
    """Synchronous bridge for notify_customer, safe to call from background jobs."""
    coro = notify_customer(
        bot=bot,
        customer_telegram_id=customer_telegram_id,
        event_key=event_key,
        language=language,
        **kwargs,
    )
    return bool(_dispatch_coroutine_safe(coro))


def notify_admins_sync(
    bot: Any,
    event_key: str,
    admin_ids: Optional[List[int]] = None,
    **kwargs: Any,
) -> int:
    """Synchronous bridge for notify_admins, safe to call from background jobs."""
    coro = notify_admins(
        bot=bot,
        event_key=event_key,
        admin_ids=admin_ids,
        **kwargs,
    )
    result = _dispatch_coroutine_safe(coro)
    return int(result) if isinstance(result, int) else 0


async def announce_new_stock(
    bot: Any,
    title: str,
    author: str,
) -> int:
    """Announce new book stock to all approved customers if ANNOUNCE_NEW_BOOKS is configured."""
    settings = get_settings()
    if not settings.announce_new_books or not bot:
        return 0

    count = 0
    try:
        from app.models.customer import Customer
        from app.models.enums import CustomerStatus

        with get_db_session() as session:
            customers = session.query(Customer).filter(Customer.status == CustomerStatus.APPROVED.value).all()
            for cust in customers:
                if cust.telegram_id:
                    sent = await notify_customer(
                        bot=bot,
                        customer_telegram_id=cust.telegram_id,
                        event_key="notify_book_announced_cust",
                        language=cust.language,
                        title=title,
                        author=author,
                    )
                    if sent:
                        count += 1
    except Exception as exc:
        logger.warning("Error announcing new stock: %s", exc)

    return count

