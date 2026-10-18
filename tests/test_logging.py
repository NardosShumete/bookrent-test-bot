"""Tests for structured logging and sensitive data redaction."""

import logging
from app.logging_config import SensitiveDataFilter, setup_logging


def test_sensitive_data_filter_redacts_bot_token() -> None:
    """Verify SensitiveDataFilter redacts Telegram bot tokens in log messages."""
    data_filter = SensitiveDataFilter()
    raw_message = "Attempting to connect with token 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_00000 now."
    sanitized = data_filter.sanitize(raw_message)

    assert "ABCdefGhIJKlmNoPQRsTUVwxyZ" not in sanitized
    assert "123456789:***REDACTED***" in sanitized


def test_sensitive_data_filter_redacts_database_password() -> None:
    """Verify SensitiveDataFilter redacts database credentials in connection URLs."""
    data_filter = SensitiveDataFilter()
    raw_message = "Connecting to postgresql://postgres:my_top_secret_db_pass@127.0.0.1:5432/bookrent"
    sanitized = data_filter.sanitize(raw_message)

    assert sanitized == "Connecting to postgresql://postgres:***REDACTED***@127.0.0.1:5432/bookrent"


def test_sensitive_data_filter_on_log_record() -> None:
    """Verify filter modifies log record attributes in-flight."""
    data_filter = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Bot token %s initialized",
        args=("999999999:Secr3tTokenStringShouldBeHidden12345",),
        exc_info=None,
    )

    data_filter.filter(record)
    assert "Secr3tTokenStringShouldBeHidden" not in str(record.args)
    assert "***REDACTED***" in str(record.args)


def test_setup_logging_configures_root_logger() -> None:
    """Verify setup_logging sets root log level and attaches filter."""
    setup_logging("DEBUG")
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG
    assert len(root_logger.handlers) >= 1
    # Check that handler has SensitiveDataFilter
    filters = root_logger.handlers[0].filters
    assert any(isinstance(f, SensitiveDataFilter) for f in filters)
