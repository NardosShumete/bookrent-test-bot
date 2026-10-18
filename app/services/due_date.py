"""Dedicated service for rental due-date calculations and timezone management.

Convention Documentation:
------------------------
This service implements the "10-Calendar-Day End-of-Day Return Convention":
When a customer checks out a book on calendar day D, the borrowing period extends
for N calendar days (default N = 10). The book is due on day (D + N) at the close
of the calendar day (23:59:59) in the configured application rental timezone
(e.g., Africa/Nairobi, UTC, America/New_York).

The returned datetime is converted to timezone-aware UTC for standardized
storage in the database.
"""

from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings


def get_rental_timezone() -> ZoneInfo:
    """Retrieve the configured application rental timezone.

    Returns:
        ZoneInfo instance matching Settings.rental_timezone.
    """
    tz_str = get_settings().rental_timezone
    return ZoneInfo(tz_str)


def calculate_due_date(
    checkout_time: datetime,
    calendar_days: int = 10,
    tz_name: Optional[str] = None,
    end_of_day: bool = True,
) -> datetime:
    """Calculate the due date for a physical rental checkout.

    Args:
        checkout_time: Timestamp when physical book copy is handed to customer.
        calendar_days: Number of calendar days borrowed (default: 10).
        tz_name: Optional explicit IANA timezone string. Defaults to Settings.rental_timezone.
        end_of_day: If True, sets the deadline to 23:59:59 of the target calendar day.
                    If False, preserves the checkout hour and minute.

    Returns:
        Timezone-aware UTC datetime representing the return deadline.

    Raises:
        ValueError: If calendar_days < 1.
    """
    if calendar_days < 1:
        raise ValueError(f"Rental period calendar days must be at least 1, got {calendar_days}")

    target_tz = ZoneInfo(tz_name) if tz_name else get_rental_timezone()

    # Ensure checkout_time is timezone-aware
    if checkout_time.tzinfo is None:
        checkout_utc = checkout_time.replace(tzinfo=timezone.utc)
    else:
        checkout_utc = checkout_time.astimezone(timezone.utc)

    # Shift checkout to the configured local rental timezone
    local_checkout = checkout_utc.astimezone(target_tz)

    # Calculate target calendar day
    target_date = local_checkout.date() + timedelta(days=calendar_days)

    if end_of_day:
        local_due = datetime.combine(target_date, time(23, 59, 59), tzinfo=target_tz)
    else:
        local_due = datetime.combine(target_date, local_checkout.time(), tzinfo=target_tz)

    # Convert back to UTC for standard storage
    return local_due.astimezone(timezone.utc)


def calculate_extension_due_date(
    current_due_date: datetime,
    additional_days: int = 5,
    tz_name: Optional[str] = None,
) -> datetime:
    """Calculate the revised due date for an approved rental extension.

    Convention:
        Adds `additional_days` (default 5 calendar days) to the current return deadline,
        preserving the 23:59:59 end-of-day convention in the configured application timezone.

    Args:
        current_due_date: Existing due date of the rental.
        additional_days: Number of calendar days to extend (default: 5).
        tz_name: Optional explicit IANA timezone string.

    Returns:
        Timezone-aware UTC datetime for the new return deadline.

    Raises:
        ValueError: If additional_days < 1.
    """
    if additional_days < 1:
        raise ValueError(f"Extension days must be at least 1, got {additional_days}")

    target_tz = ZoneInfo(tz_name) if tz_name else get_rental_timezone()

    if current_due_date.tzinfo is None:
        curr_utc = current_due_date.replace(tzinfo=timezone.utc)
    else:
        curr_utc = current_due_date.astimezone(timezone.utc)

    local_curr = curr_utc.astimezone(target_tz)
    new_target_date = local_curr.date() + timedelta(days=additional_days)
    local_new_due = datetime.combine(new_target_date, time(23, 59, 59), tzinfo=target_tz)
    return local_new_due.astimezone(timezone.utc)

