"""Structured logging configuration with automatic secret sanitization."""

import logging
import re
import sys
from typing import Optional


class SensitiveDataFilter(logging.Filter):
    """Filter that sanitizes sensitive data such as bot tokens and passwords from logs."""

    # Matches Telegram bot tokens: e.g. 123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
    BOT_TOKEN_PATTERN = re.compile(r"(\b\d{8,11}:)[A-Za-z0-9_-]{20,}\b")

    # Matches credentials in URIs: e.g. postgresql://user:password@host:port/db
    URI_PASSWORD_PATTERN = re.compile(r"(://[^:\s]+:)([^@\s]+)(@[^/\s]+)")

    # Matches explicit phone numbers e.g. +251911223344, 0911223344, or phone='+251...'
    PHONE_PATTERN = re.compile(r"(\+?\d{1,4}[-.\s]?)?(\d{2,3})[-.\s]?(\d{3,4})[-.\s]?(\d{4})\b")

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.sanitize(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self.sanitize(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self.sanitize(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        return True

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Replace sensitive tokens, passwords, and file IDs in the string with masked values."""
        if not text:
            return text
        # Redact bot tokens
        sanitized = cls.BOT_TOKEN_PATTERN.sub(r"\1***REDACTED***", text)
        # Redact database passwords in connection URLs
        sanitized = cls.URI_PASSWORD_PATTERN.sub(r"\1***REDACTED***\3", sanitized)
        # Redact national id file_id patterns if present
        sanitized = re.sub(r"(file_id[=:]\s*['\"]?)([A-Za-z0-9_-]{8,})(['\"]?)", r"\1***REDACTED***\3", sanitized)
        return sanitized

    @classmethod
    def mask_phone(cls, phone: Optional[str]) -> str:
        """Mask a phone number leaving only the last 4 digits visible."""
        if not phone:
            return ""
        clean = re.sub(r"[^\d+]", "", phone)
        if len(clean) <= 4:
            return "****"
        return f"{clean[:4]}****{clean[-2:]}" if len(clean) >= 8 else "****"


def mask_phone(phone: Optional[str]) -> str:
    """Mask a phone number for secure display in messages and logs."""
    return SensitiveDataFilter.mask_phone(phone)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root and application logging with structured format and security filters.

    Args:
        log_level: Log severity string (e.g. 'DEBUG', 'INFO', 'WARNING', 'ERROR').
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Standard structured format
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    # Console handler
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(numeric_level)
    handler.setFormatter(formatter)
    handler.addFilter(SensitiveDataFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Adjust external libraries log levels to avoid noisy output
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
