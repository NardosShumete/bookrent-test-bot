"""Tests for the dedicated due-date calculation service and timezone handling."""

from datetime import datetime, timezone
import pytest
from zoneinfo import ZoneInfo

from app.services.due_date import calculate_due_date, get_rental_timezone


def test_get_rental_timezone(monkeypatch: pytest.MonkeyPatch, valid_env_vars: dict) -> None:
    """Verify that get_rental_timezone resolves the configured IANA timezone."""
    monkeypatch.setenv("RENTAL_TIMEZONE", "Africa/Nairobi")
    from app.config import get_settings

    get_settings.cache_clear()

    tz = get_rental_timezone()
    assert isinstance(tz, ZoneInfo)
    assert tz.key == "Africa/Nairobi"

    get_settings.cache_clear()


def test_calculate_due_date_default_end_of_day_utc() -> None:
    """Verify 10-calendar-day calculation at 23:59:59 in UTC."""
    # Checkout on Oct 10, 2026 at 10:15:30 UTC
    checkout = datetime(2026, 10, 10, 10, 15, 30, tzinfo=timezone.utc)
    due = calculate_due_date(checkout, calendar_days=10, tz_name="UTC", end_of_day=True)

    # Day 10 + 10 = Oct 20, 2026 at 23:59:59 UTC
    assert due == datetime(2026, 10, 20, 23, 59, 59, tzinfo=timezone.utc)


def test_calculate_due_date_timezone_conversion_nairobi() -> None:
    """Verify due-date calculation in Africa/Nairobi (UTC+3) correctly maps to UTC."""
    # Checkout at 2026-10-10 14:00:00 UTC (17:00 Nairobi time)
    checkout_utc = datetime(2026, 10, 10, 14, 0, 0, tzinfo=timezone.utc)
    due_utc = calculate_due_date(checkout_utc, calendar_days=10, tz_name="Africa/Nairobi", end_of_day=True)

    # In Nairobi, target date is 2026-10-20 at 23:59:59 EAT (UTC+3)
    # Converted to UTC, that is 2026-10-20 at 20:59:59 UTC
    assert due_utc == datetime(2026, 10, 20, 20, 59, 59, tzinfo=timezone.utc)


def test_calculate_due_date_timezone_conversion_new_york() -> None:
    """Verify due-date calculation in America/New_York (EDT UTC-4 in October)."""
    # Checkout at 2026-10-10 15:00:00 UTC (11:00 AM EDT)
    checkout_utc = datetime(2026, 10, 10, 15, 0, 0, tzinfo=timezone.utc)
    due_utc = calculate_due_date(checkout_utc, calendar_days=10, tz_name="America/New_York", end_of_day=True)

    # In America/New_York, target date is 2026-10-20 23:59:59 EDT (UTC-4)
    # Converted to UTC, that is 2026-10-21 03:59:59 UTC
    assert due_utc == datetime(2026, 10, 21, 3, 59, 59, tzinfo=timezone.utc)


def test_calculate_due_date_leap_year() -> None:
    """Verify due-date calculation spans February 29 in a leap year (2028)."""
    checkout = datetime(2028, 2, 25, 9, 0, 0, tzinfo=timezone.utc)
    # Feb 25 + 10 days in leap year: Feb 26, 27, 28, 29 (4 days) + Mar 1, 2, 3, 4, 5, 6 (6 days) -> Mar 6
    due = calculate_due_date(checkout, calendar_days=10, tz_name="UTC", end_of_day=True)
    assert due == datetime(2028, 3, 6, 23, 59, 59, tzinfo=timezone.utc)


def test_calculate_due_date_preserve_time_when_not_end_of_day() -> None:
    """Verify calculation when end_of_day is False preserves the checkout hour/minute."""
    checkout = datetime(2026, 10, 10, 14, 30, 45, tzinfo=timezone.utc)
    due = calculate_due_date(checkout, calendar_days=10, tz_name="UTC", end_of_day=False)
    assert due == datetime(2026, 10, 20, 14, 30, 45, tzinfo=timezone.utc)


def test_calculate_due_date_naive_datetime_handling() -> None:
    """Verify that a naive datetime is interpreted as UTC safely."""
    naive_checkout = datetime(2026, 10, 10, 12, 0, 0)
    due = calculate_due_date(naive_checkout, calendar_days=5, tz_name="UTC", end_of_day=True)
    assert due == datetime(2026, 10, 15, 23, 59, 59, tzinfo=timezone.utc)


def test_calculate_due_date_invalid_calendar_days() -> None:
    """Verify that non-positive calendar_days raises ValueError."""
    checkout = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="calendar days must be at least 1"):
        calculate_due_date(checkout, calendar_days=0)

    with pytest.raises(ValueError, match="calendar days must be at least 1"):
        calculate_due_date(checkout, calendar_days=-5)
