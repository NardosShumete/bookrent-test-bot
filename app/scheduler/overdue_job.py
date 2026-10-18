"""Persistent and restart-safe scheduled processing for overdue detection and notifications."""

import logging
from typing import Any, Dict, Optional
from telegram.ext import Application, ContextTypes

from app.config import get_settings
from app.database.session import get_db_session
from app.services.overdue import process_overdue_rentals, send_overdue_notifications

logger = logging.getLogger(__name__)


def run_daily_overdue_job(bot: Optional[Any] = None) -> Dict[str, Any]:
    """Execute the daily overdue detection, charge generation, and notification dispatch.

    Properties:
    1. Database Idempotency: Duplicate runs or overlapping workers will NOT double-charge
       due to the unique constraint on (rental_id, overdue_date).
    2. Restart Recovery / Catch-up: Authoritative date calculations evaluate all calendar days
       elapsed since the return deadline; any missed runs during bot downtime are automatically
       detected and billed.
    3. Separation of Concerns: Charges are committed to the database before notification dispatch.
       A network or Telegram API delivery failure never loses charge records or causes double-billing.
    4. Safe Failure Handling: Catches and logs errors without leaking bot tokens or sensitive secrets.

    Args:
        bot: Optional Telegram Bot instance for sending notifications.

    Returns:
        Summary dictionary with metrics on charges created and notifications delivered.
    """
    logger.info("Starting scheduled daily overdue processing job...")
    settings = get_settings()

    summary: Dict[str, Any] = {
        "charges_created": 0,
        "notifications_sent": 0,
        "success": False,
        "error": None,
    }

    # Step 1: Detect overdue rentals and persist charges
    try:
        with get_db_session() as session:
            charges = process_overdue_rentals(session=session)
            summary["charges_created"] = len(charges)
            logger.info(
                "Overdue charge processing completed. Created %d new daily charge records.",
                len(charges),
            )
    except Exception as exc:
        logger.error(
            "Error encountered during overdue charge creation: %s",
            exc,
            exc_info=True,
        )
        summary["error"] = str(exc)
        return summary

    # Step 2: Dispatch overdue notifications if bot instance is available
    if bot is not None:
        try:
            with get_db_session() as notif_session:
                owner_ids = settings.admin_user_ids
                notif_count = send_overdue_notifications(
                    session=notif_session,
                    bot=bot,
                    owner_chat_ids=owner_ids,
                )
                summary["notifications_sent"] = notif_count
                logger.info("Successfully dispatched %d overdue notifications.", notif_count)
        except Exception as exc:
            logger.error(
                "Error encountered during overdue notification delivery: %s",
                exc,
                exc_info=True,
            )
            summary["error"] = str(exc)

    summary["success"] = True
    return summary



async def scheduled_overdue_job_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """PTB JobQueue callback executing the overdue detection routine."""
    logger.info("Triggering scheduled overdue job from Telegram JobQueue...")
    bot = context.bot if context and hasattr(context, "bot") else None
    run_daily_overdue_job(bot=bot)


def setup_overdue_scheduler(application: Application) -> bool:
    """Configure and register the overdue processing job in the PTB JobQueue.

    Schedules the job to execute every `scheduler_interval_hours` (default 24 hours),
    with an initial run 10 seconds after startup to ensure prompt recovery from restarts
    and catch up on any missed days during downtime.

    Args:
        application: The python-telegram-bot Application instance.

    Returns:
        True if scheduler successfully registered, False if job_queue unavailable.
    """
    if application.job_queue is None:
        logger.warning(
            "Application job_queue is not available. Background overdue scheduler was not registered. "
            "Ensure python-telegram-bot[job-queue] is installed."
        )
        return False

    existing_jobs = application.job_queue.get_jobs_by_name("daily_overdue_processor")
    if existing_jobs:
        logger.info("Overdue scheduler job 'daily_overdue_processor' already registered; skipping duplicate registration.")
        return True

    settings = get_settings()
    interval_seconds = getattr(settings, "scheduler_interval_hours", 24) * 3600

    # Run initial catch-up 10 seconds after startup, then repeating every interval_seconds
    application.job_queue.run_repeating(
        callback=scheduled_overdue_job_callback,
        interval=interval_seconds,
        first=10,
        name="daily_overdue_processor",
    )

    logger.info(
        "Overdue scheduler registered successfully: initial run in 10s, repeating every %d seconds.",
        interval_seconds,
    )
    return True
