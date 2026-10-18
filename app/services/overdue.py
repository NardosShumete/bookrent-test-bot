"""Overdue detection, daily charging, and notification service."""

import asyncio
import concurrent.futures
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
import logging
from typing import Any, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

from app.config import get_settings
from app.localization import DEFAULT_LANGUAGE, t
from app.models.book import BookCopy
from app.models.enums import BookCopyStatus, LedgerTransactionType, RentalStatus
from app.models.exceptions import RentalNotFoundError
from app.models.ledger import CollateralLedger
from app.models.overdue import OverdueCharge
from app.models.rental import Rental
from app.services.audit import record_audit_log
from app.services.due_date import get_rental_timezone
from app.services.ledger import record_ledger_entry

logger = logging.getLogger(__name__)

OVERDUE_DAILY_FEE = Decimal("5.00")


def calculate_overdue_days_and_dates(
    rental_or_due: Union[Rental, datetime],
    return_time: Optional[datetime] = None,
    as_of: Optional[datetime] = None,
    tz: Optional[ZoneInfo] = None,
    tz_name: Optional[str] = None,
    **kwargs: Any,
) -> Tuple[int, List[date]]:
    """Calculate the count and exact calendar dates on which a rental has accrued overdue status.

    Documented Daily Counting Rule:
    -------------------------------
    1. A rental checkout has an authoritative return deadline `due_date`, set by default to
       23:59:59 of the target calendar day in the configured rental timezone (`RENTAL_TIMEZONE`).
    2. Overdue Day 1 is the calendar day immediately following the due date in that timezone
       (`due_date.date() + 1 day`). Overdue Day k is (due_date.date() + k days).
    3. No charges accrue before the return deadline expires.
    4. Accrual stops strictly at the recorded physical `return_time`. If the book was returned,
       the evaluation cutoff is `return_time`. No charges can ever accrue for days after return.
    5. Each overdue calendar day accrues exactly 5.00 ETB.

    Args:
        rental_or_due: Rental model instance OR due_date datetime.
        return_time: Optional physical return timestamp if book was already returned.
        as_of: Evaluation reference timestamp (defaults to current UTC time).
        tz: Optional explicit ZoneInfo.
        tz_name: Optional explicit timezone string (e.g. "Africa/Addis_Ababa").

    Returns:
        Tuple of (overdue_days_count, list_of_overdue_calendar_dates).
    """
    if isinstance(rental_or_due, Rental):
        due_date = rental_or_due.due_date
        effective_return = rental_or_due.return_time if return_time is None else return_time
    else:
        due_date = rental_or_due
        effective_return = return_time

    target_tz = tz or (ZoneInfo(tz_name) if tz_name else get_rental_timezone())

    # Normalize due_date to timezone-aware UTC then shift to local timezone
    due_utc = due_date.replace(tzinfo=timezone.utc) if due_date.tzinfo is None else due_date.astimezone(timezone.utc)
    local_due = due_utc.astimezone(target_tz)
    due_cutoff_date = local_due.date()

    # Determine effective evaluation cutoff
    ref_ts = as_of or datetime.now(timezone.utc)
    if ref_ts.tzinfo is None:
        ref_ts = ref_ts.replace(tzinfo=timezone.utc)
    else:
        ref_ts = ref_ts.astimezone(timezone.utc)

    if effective_return is not None:
        ret_utc = (
            effective_return.replace(tzinfo=timezone.utc)
            if effective_return.tzinfo is None
            else effective_return.astimezone(timezone.utc)
        )
        effective_end = min(ref_ts, ret_utc)
    else:
        effective_end = ref_ts

    # If the effective end time is on or before the due date deadline, it is not overdue
    if effective_end <= due_utc:
        return 0, []

    local_end = effective_end.astimezone(target_tz)
    end_date = local_end.date()

    overdue_dates: List[date] = []
    curr = due_cutoff_date + timedelta(days=1)
    while curr <= end_date:
        overdue_dates.append(curr)
        curr += timedelta(days=1)

    return len(overdue_dates), overdue_dates


def process_overdue_rentals(
    session: Session,
    as_of: Optional[datetime] = None,
    tz: Optional[ZoneInfo] = None,
) -> List[OverdueCharge]:
    """Scan all active rentals, transition overdue items, and post deterministic daily charges.

    Idempotency & Concurrency Safeguards:
    -------------------------------------
    - Row-locks active rentals using `with_for_update()`.
    - Queries existing `OverdueCharge` records to avoid duplicate charging.
    - Database unique constraint `uq_overdue_charges_rental_date` guarantees that no day
      can be charged twice even if the scheduler runs concurrently.
    - Accurately catches up on missed days after server restarts or outages.
    - Collateral is NEVER automatically deducted or forfeited.

    Args:
        session: Active SQLAlchemy database session.
        as_of: Optional timestamp for evaluation (defaults to current UTC time).
        tz: Optional explicit ZoneInfo.

    Returns:
        List of newly created OverdueCharge instances.
    """
    eval_time = as_of or datetime.now(timezone.utc)
    target_tz = tz or get_rental_timezone()
    settings = get_settings()
    daily_fee = Decimal(str(settings.overdue_daily_fee))

    # Query all active rentals (not returned and in active/extended/overdue status)
    active_rentals = (
        session.query(Rental)
        .filter(
            Rental.return_time.is_(None),
            Rental.status.in_([
                RentalStatus.ACTIVE.value,
                RentalStatus.EXTENDED.value,
                RentalStatus.OVERDUE.value,
            ]),
        )
        .with_for_update()
        .all()
    )

    new_charges: List[OverdueCharge] = []

    for rental in active_rentals:
        overdue_days, overdue_dates = calculate_overdue_days_and_dates(
            rental_or_due=rental,
            as_of=eval_time,
            tz=target_tz,
        )

        if not overdue_dates:
            continue

        # Transition status to OVERDUE if deadline has passed
        if rental.status != RentalStatus.OVERDUE.value:
            rental.status = RentalStatus.OVERDUE.value

        # Transition copy status to OVERDUE if currently RENTED
        if rental.copy and rental.copy.status == BookCopyStatus.RENTED.value:
            rental.copy.transition_to(
                BookCopyStatus.OVERDUE,
                reason=f"Return deadline passed ({rental.due_date.isoformat()})",
            )

        # Retrieve dates already charged for this rental
        existing_charges = (
            session.query(OverdueCharge)
            .filter(OverdueCharge.rental_id == rental.id)
            .order_by(OverdueCharge.overdue_date.asc())
            .all()
        )
        charged_dates = {c.overdue_date for c in existing_charges}
        current_day_count = len(existing_charges)

        for d in overdue_dates:
            if d in charged_dates:
                continue

            current_day_count += 1
            charge = OverdueCharge(
                rental_id=rental.id,
                customer_id=rental.customer_id,
                overdue_date=d,
                day_number=current_day_count,
                amount=daily_fee,
                notification_sent=False,
            )
            session.add(charge)
            session.flush([charge])

            # Record discrete transaction in CollateralLedger
            record_ledger_entry(
                session=session,
                customer_id=rental.customer_id,
                transaction_type=LedgerTransactionType.OVERDUE_PENALTY,
                amount=daily_fee,
                rental_id=rental.id,
                notes=f"Overdue penalty for date {d.isoformat()} (Day {current_day_count})",
                actor="SYSTEM:OVERDUE_JOB",
            )

            new_charges.append(charge)
            charged_dates.add(d)

    if new_charges:
        record_audit_log(
            session=session,
            entity_type="OVERDUE_JOB",
            entity_id=0,
            action="PROCESS_OVERDUE",
            actor="SYSTEM",
            new_values={
                "charges_created": len(new_charges),
                "as_of": eval_time.isoformat(),
            },
        )

    return new_charges


def get_rental_overdue_summary(
    session: Session,
    rental_id: int,
    as_of: Optional[datetime] = None,
) -> dict[str, Any]:
    """Retrieve detailed overdue status and fee history for a rental."""
    rental = session.get(Rental, rental_id)
    if rental is None:
        raise RentalNotFoundError(f"Rental #{rental_id} not found")

    eval_time = as_of or datetime.now(timezone.utc)
    days, dates = calculate_overdue_days_and_dates(rental, as_of=eval_time)

    charges = (
        session.query(OverdueCharge)
        .filter(OverdueCharge.rental_id == rental.id)
        .order_by(OverdueCharge.overdue_date.asc())
        .all()
    )

    total_amount = sum((c.amount for c in charges), Decimal("0.00"))
    if not charges and days > 0:
        settings = get_settings()
        daily_fee = Decimal(str(settings.overdue_daily_fee))
        total_amount = daily_fee * days

    unnotified = sum(1 for c in charges if not c.notification_sent)
    is_overdue = days > 0 or rental.status == RentalStatus.OVERDUE.value or len(charges) > 0

    return {
        "rental_id": rental.id,
        "customer_id": rental.customer_id,
        "copy_id": rental.copy_id,
        "due_date": rental.due_date,
        "return_time": rental.return_time,
        "status": rental.status,
        "is_overdue": is_overdue,
        "overdue_days": days or len(charges),
        "overdue_days_count": days or len(charges),
        "total_overdue_fee": total_amount,
        "total_overdue_amount": total_amount,
        "charges": charges,
        "unnotified_count": unnotified,
    }


def get_all_overdue_rentals(
    session: Session,
    as_of: Optional[datetime] = None,
) -> List[Tuple[Rental, int, Decimal]]:
    """Retrieve an overview of all currently overdue active rentals as (rental, overdue_days, total_fee)."""
    eval_time = as_of or datetime.now(timezone.utc)
    active_rentals = (
        session.query(Rental)
        .filter(
            Rental.return_time.is_(None),
            Rental.status.in_([
                RentalStatus.ACTIVE.value,
                RentalStatus.EXTENDED.value,
                RentalStatus.OVERDUE.value,
            ]),
        )
        .order_by(Rental.due_date.asc())
        .all()
    )

    results: List[Tuple[Rental, int, Decimal]] = []
    for r in active_rentals:
        days, dates = calculate_overdue_days_and_dates(r, as_of=eval_time)
        if days > 0 or r.status == RentalStatus.OVERDUE.value:
            summary = get_rental_overdue_summary(session, r.id, as_of=eval_time)
            fee = summary["total_overdue_fee"]
            results.append((r, days or summary["overdue_days"], fee))

    return results


def _dispatch_coroutine_safe(coro_or_val: Any) -> Any:
    """Execute a coroutine safely regardless of whether an event loop is already active."""
    if inspect.iscoroutine(coro_or_val):
        try:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(asyncio.run, coro_or_val).result(timeout=10)
        except RuntimeError:
            return asyncio.run(coro_or_val)
    return coro_or_val


def send_overdue_notifications(
    session: Session,
    bot: Any = None,
    owner_chat_ids: Optional[List[int]] = None,
) -> int:
    """Deliver overdue alert notifications to customers and owners for unnotified charges.

    Decoupled from financial charge creation: failures in Telegram message delivery
    do NOT rollback or duplicate overdue charges, ensuring reliable retries.

    Args:
        session: Active SQLAlchemy database session.
        bot: Telegram bot instance.
        owner_chat_ids: Optional list of Telegram user IDs for owners.

    Returns:
        Number of rentals for which notifications were successfully sent.
    """
    if bot is None:
        return 0

    settings = get_settings()
    tz = get_rental_timezone()
    owner_ids = owner_chat_ids or settings.admin_user_ids

    # Query unnotified charges grouped by rental
    unnotified_charges = (
        session.query(OverdueCharge)
        .filter(OverdueCharge.notification_sent.is_(False))
        .order_by(OverdueCharge.rental_id, OverdueCharge.overdue_date.asc())
        .all()
    )

    if not unnotified_charges:
        return 0

    # Group by rental
    rental_map: dict[int, List[OverdueCharge]] = {}
    for c in unnotified_charges:
        rental_map.setdefault(c.rental_id, []).append(c)

    sent_count = 0
    now = datetime.now(timezone.utc)

    for rental_id, charges in rental_map.items():
        rental = session.get(Rental, rental_id)
        if not rental:
            continue

        customer = rental.customer
        book = rental.copy.book if rental.copy else None
        book_title = book.title if book else "Borrowed Book"
        local_due = rental.due_date.astimezone(tz)
        total_days = len(rental.overdue_charges)
        total_fee = sum((c.amount for c in rental.overdue_charges), Decimal("0.00"))

        cust_lang = getattr(customer, "language", None) or DEFAULT_LANGUAGE
        cust_msg = t(
            "notify_overdue_detected_cust",
            cust_lang,
            rental_id=rental.id,
            book_title=book_title,
            days=total_days,
            fee=str(total_fee),
        )

        try:
            if customer and customer.telegram_id:
                _dispatch_coroutine_safe(
                    bot.send_message(
                        chat_id=customer.telegram_id,
                        text=cust_msg,
                        parse_mode="HTML",
                    )
                )

            if owner_ids:
                for owner_id in owner_ids:
                    try:
                        owner_lang = DEFAULT_LANGUAGE
                        try:
                            from app.services.customer import get_customer_language
                            owner_lang = get_customer_language(session, owner_id) or DEFAULT_LANGUAGE
                        except Exception:
                            pass
                        owner_msg = t(
                            "notify_overdue_detected_admin",
                            owner_lang,
                            rental_id=rental.id,
                            customer_name=f"{customer.first_name} {customer.last_name or ''}".strip(),
                            days=total_days,
                            fee=str(total_fee),
                            book_title=book_title,
                        )
                        _dispatch_coroutine_safe(
                            bot.send_message(
                                chat_id=owner_id,
                                text=owner_msg,
                                parse_mode="HTML",
                            )
                        )
                    except Exception as own_err:
                        logger.warning("Failed to notify owner %s of overdue rental: %s", owner_id, own_err)


            for c in charges:
                c.notification_sent = True
                c.notification_sent_at = now

            session.flush()
            sent_count += 1
        except Exception as exc:
            logger.error("Failed to send overdue notification for Rental #%s: %s", rental_id, exc)

    return sent_count
