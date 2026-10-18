"""Automated tests for daily overdue detection, charge generation, return cutoff, idempotency, and notifications."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from telegram.error import TelegramError

from app.models.book import Book, BookCopy
from app.models.customer import Customer
from app.models.enums import BookCopyStatus, CustomerStatus, RentalStatus
from app.models.overdue import OverdueCharge
from app.models.rental import Rental
from app.scheduler.overdue_job import run_daily_overdue_job
from app.services.overdue import (
    calculate_overdue_days_and_dates,
    get_all_overdue_rentals,
    get_rental_overdue_summary,
    process_overdue_rentals,
    send_overdue_notifications,
)

OWNER_ID = 100000001


@pytest.fixture(autouse=True)
def setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure environment variables for overdue testing."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ADMIN_USER_IDS", str(OWNER_ID))
    monkeypatch.setenv("RENTAL_TIMEZONE", "Africa/Addis_Ababa")
    monkeypatch.setenv("OVERDUE_DAILY_FEE", "5.00")
    from app.config import get_settings

    get_settings.cache_clear()
    yield


def create_test_rental(
    session: Session,
    checkout_time: datetime,
    due_date: datetime,
    status: str = RentalStatus.ACTIVE.value,
    return_time: datetime = None,
) -> Rental:
    """Helper to set up an active rental with a book and customer."""
    book = Book(
        isbn="9780132350884",
        title="Clean Code",
        author="Robert C. Martin",
        rental_price=Decimal("15.00"),
    )
    customer = Customer(
        telegram_id=987654,
        first_name="Abebe",
        status=CustomerStatus.APPROVED.value,
    )
    session.add_all([book, customer])
    session.flush()

    copy = BookCopy(
        book_id=book.id,
        copy_number=1,
        barcode="BC-CC-001",
        status=BookCopyStatus.RENTED.value,
    )
    session.add(copy)
    session.flush()

    rental = Rental(
        copy_id=copy.id,
        customer_id=customer.id,
        checkout_time=checkout_time,
        due_date=due_date,
        return_time=return_time,
        status=status,
    )
    session.add(rental)
    session.flush()
    return rental


def test_rental_not_yet_overdue_receives_no_charge(db_session: Session) -> None:
    """A rental that is not yet past its return deadline receives 0 overdue days and 0 charge."""
    # Current UTC time
    now = datetime(2026, 10, 16, 10, 0, 0, tzinfo=timezone.utc)
    due_date = now + timedelta(days=2)

    rental = create_test_rental(db_session, checkout_time=now - timedelta(days=8), due_date=due_date)

    overdue_days, overdue_dates = calculate_overdue_days_and_dates(rental, as_of=now, tz_name="Africa/Addis_Ababa")
    assert overdue_days == 0
    assert overdue_dates == []

    created_charges = process_overdue_rentals(db_session, as_of=now)
    assert len(created_charges) == 0

    summary = get_rental_overdue_summary(db_session, rental.id, as_of=now)
    assert summary["is_overdue"] is False
    assert summary["overdue_days"] == 0
    assert summary["total_overdue_fee"] == Decimal("0.00")


def test_rental_overdue_boundary_rule(db_session: Session) -> None:
    """A rental becomes overdue starting at 00:00:00 on the day after the due date in the local timezone."""
    # Suppose due date is 2026-10-15 at 23:59:59 in Africa/Addis_Ababa (+03:00), which is 20:59:59 UTC
    # 2026-10-15 23:59:59 +03:00 = 2026-10-15 20:59:59 UTC
    due_utc = datetime(2026, 10, 15, 20, 59, 59, tzinfo=timezone.utc)
    checkout = due_utc - timedelta(days=10)

    rental = create_test_rental(db_session, checkout_time=checkout, due_date=due_utc)

    # 1 second before midnight in local time (20:59:58 UTC) -> NOT overdue
    before_midnight = datetime(2026, 10, 15, 20, 59, 58, tzinfo=timezone.utc)
    days, dates = calculate_overdue_days_and_dates(rental, as_of=before_midnight, tz_name="Africa/Addis_Ababa")
    assert days == 0

    # 1 second after midnight in local time (21:00:01 UTC on Oct 15 is 00:00:01 on Oct 16 local time) -> 1 OVERDUE DAY
    after_midnight = datetime(2026, 10, 15, 21, 0, 1, tzinfo=timezone.utc)
    days, dates = calculate_overdue_days_and_dates(rental, as_of=after_midnight, tz_name="Africa/Addis_Ababa")
    assert days == 1
    assert dates == [date(2026, 10, 16)]


def test_one_overdue_day_produces_5_etb(db_session: Session) -> None:
    """Exactly one overdue calendar day generates a single charge record of 5.00 ETB."""
    due_utc = datetime(2026, 10, 15, 20, 59, 59, tzinfo=timezone.utc)
    rental = create_test_rental(db_session, checkout_time=due_utc - timedelta(days=10), due_date=due_utc)

    # as_of Oct 16 afternoon local time (Oct 16 12:00:00 UTC)
    as_of = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    created = process_overdue_rentals(db_session, as_of=as_of)
    assert len(created) == 1

    charge = created[0]
    assert charge.rental_id == rental.id
    assert charge.overdue_date == date(2026, 10, 16)
    assert charge.amount == Decimal("5.00")
    assert charge.notification_sent is False

    # Check copy transitioned to OVERDUE
    assert rental.copy.status == BookCopyStatus.OVERDUE.value


def test_multiple_overdue_days_cumulative_amount(db_session: Session) -> None:
    """Multiple overdue days produce the correct cumulative amount of 5.00 ETB per calendar day."""
    due_utc = datetime(2026, 10, 10, 20, 59, 59, tzinfo=timezone.utc)
    rental = create_test_rental(db_session, checkout_time=due_utc - timedelta(days=10), due_date=due_utc)

    # 4 days overdue: Oct 11, 12, 13, 14
    as_of = datetime(2026, 10, 14, 15, 0, 0, tzinfo=timezone.utc)
    created = process_overdue_rentals(db_session, as_of=as_of)
    assert len(created) == 4

    expected_dates = [
        date(2026, 10, 11),
        date(2026, 10, 12),
        date(2026, 10, 13),
        date(2026, 10, 14),
    ]
    assert [c.overdue_date for c in created] == expected_dates
    for c in created:
        assert c.amount == Decimal("5.00")

    summary = get_rental_overdue_summary(db_session, rental.id, as_of=as_of)
    assert summary["overdue_days"] == 4
    assert summary["total_overdue_fee"] == Decimal("20.00")


def test_repeated_scheduler_executions_idempotent(db_session: Session) -> None:
    """Repeated scheduler runs do NOT create duplicate charges for already billed days."""
    due_utc = datetime(2026, 10, 12, 20, 59, 59, tzinfo=timezone.utc)
    rental = create_test_rental(db_session, checkout_time=due_utc - timedelta(days=10), due_date=due_utc)

    as_of = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)

    # First execution: creates 3 charges (Oct 13, 14, 15)
    first_run = process_overdue_rentals(db_session, as_of=as_of)
    assert len(first_run) == 3

    # Second execution: immediately runs again with same as_of
    second_run = process_overdue_rentals(db_session, as_of=as_of)
    assert len(second_run) == 0

    # Total charges in DB is still exactly 3
    charges = db_session.query(OverdueCharge).filter_by(rental_id=rental.id).all()
    assert len(charges) == 3


def test_database_unique_constraint_blocks_concurrent_duplicate(db_session: Session) -> None:
    """Database unique constraint on (rental_id, overdue_date) prevents duplicate insertion."""
    due_utc = datetime(2026, 10, 12, 20, 59, 59, tzinfo=timezone.utc)
    rental = create_test_rental(db_session, checkout_time=due_utc - timedelta(days=10), due_date=due_utc)

    c1 = OverdueCharge(
        rental_id=rental.id,
        customer_id=rental.customer_id,
        overdue_date=date(2026, 10, 13),
        day_number=1,
        amount=Decimal("5.00"),
    )
    db_session.add(c1)
    db_session.flush()

    c2 = OverdueCharge(
        rental_id=rental.id,
        customer_id=rental.customer_id,
        overdue_date=date(2026, 10, 13),
        day_number=2,
        amount=Decimal("5.00"),
    )
    db_session.add(c2)
    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()



def test_returned_rentals_stop_accruing_charges(db_session: Session) -> None:
    """Overdue charges cease accruing on the physical return timestamp."""
    # Due on Oct 10 20:59:59 UTC
    due_utc = datetime(2026, 10, 10, 20, 59, 59, tzinfo=timezone.utc)
    # Physically returned on Oct 12 at 12:00:00 UTC (during Overdue Day 2)
    return_utc = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

    rental = create_test_rental(
        db_session,
        checkout_time=due_utc - timedelta(days=10),
        due_date=due_utc,
        status=RentalStatus.RETURNED.value,
        return_time=return_utc,
    )

    # Even if scheduler runs on Oct 20 (8 days later), only 2 days accrued (Oct 11, Oct 12)
    as_of = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
    days, dates = calculate_overdue_days_and_dates(rental, as_of=as_of, tz_name="Africa/Addis_Ababa")
    assert days == 2
    assert dates == [date(2026, 10, 11), date(2026, 10, 12)]

    summary = get_rental_overdue_summary(db_session, rental.id, as_of=as_of)
    assert summary["overdue_days"] == 2
    assert summary["total_overdue_fee"] == Decimal("10.00")


def test_scheduler_catch_up_after_restart(db_session: Session) -> None:
    """Scheduler automatically catches up on all missed days after bot downtime."""
    due_utc = datetime(2026, 10, 10, 20, 59, 59, tzinfo=timezone.utc)
    rental = create_test_rental(db_session, checkout_time=due_utc - timedelta(days=10), due_date=due_utc)

    # Day 1: scheduler ran on Oct 11, charged Oct 11
    run1 = process_overdue_rentals(db_session, as_of=datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc))
    assert len(run1) == 1
    assert run1[0].overdue_date == date(2026, 10, 11)

    # Bot goes offline for 3 days (Oct 12, 13, 14 missed)
    # Day 4: Bot restarts on Oct 15
    run2 = process_overdue_rentals(db_session, as_of=datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc))
    assert len(run2) == 4
    assert [c.overdue_date for c in run2] == [
        date(2026, 10, 12),
        date(2026, 10, 13),
        date(2026, 10, 14),
        date(2026, 10, 15),
    ]

    # Total charges is now 5 days = 25.00 ETB
    all_charges = db_session.query(OverdueCharge).filter_by(rental_id=rental.id).all()
    assert len(all_charges) == 5
    assert sum(c.amount for c in all_charges) == Decimal("25.00")


def test_notification_failure_does_not_lose_or_duplicate_charges(db_session: Session) -> None:
    """Telegram delivery errors do not affect financial records, and retries don't re-bill."""
    due_utc = datetime(2026, 10, 15, 20, 59, 59, tzinfo=timezone.utc)
    rental = create_test_rental(db_session, checkout_time=due_utc - timedelta(days=10), due_date=due_utc)

    as_of = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    created = process_overdue_rentals(db_session, as_of=as_of)
    assert len(created) == 1
    charge = created[0]
    assert charge.notification_sent is False

    # Mock bot that fails with TelegramError
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(side_effect=TelegramError("Network timeout"))

    sent_count = send_overdue_notifications(db_session, bot=mock_bot, owner_chat_ids=[OWNER_ID])
    assert sent_count == 0

    # Charge is still present in database and not lost!
    refreshed_charge = db_session.get(OverdueCharge, charge.id)
    assert refreshed_charge is not None
    assert refreshed_charge.amount == Decimal("5.00")
    assert refreshed_charge.notification_sent is False

    # Running process_overdue_rentals again does NOT re-create the charge
    re_run = process_overdue_rentals(db_session, as_of=as_of)
    assert len(re_run) == 0


def test_successful_notification_marks_notification_sent(db_session: Session) -> None:
    """When Telegram notification succeeds, notification_sent flag is persisted as True."""
    due_utc = datetime(2026, 10, 15, 20, 59, 59, tzinfo=timezone.utc)
    rental = create_test_rental(db_session, checkout_time=due_utc - timedelta(days=10), due_date=due_utc)

    as_of = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    process_overdue_rentals(db_session, as_of=as_of)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    sent_count = send_overdue_notifications(db_session, bot=mock_bot, owner_chat_ids=[OWNER_ID])
    assert sent_count >= 1

    charges = db_session.query(OverdueCharge).filter_by(rental_id=rental.id).all()
    assert all(c.notification_sent for c in charges)


def test_get_all_overdue_rentals(db_session: Session) -> None:
    """get_all_overdue_rentals correctly lists all active overdue rentals."""
    due_utc = datetime(2026, 10, 15, 20, 59, 59, tzinfo=timezone.utc)
    rental = create_test_rental(db_session, checkout_time=due_utc - timedelta(days=10), due_date=due_utc)

    as_of = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    process_overdue_rentals(db_session, as_of=as_of)

    results = get_all_overdue_rentals(db_session, as_of=as_of)
    assert len(results) == 1
    r, days, fee = results[0]
    assert r.id == rental.id
    assert days == 2
    assert fee == Decimal("10.00")
