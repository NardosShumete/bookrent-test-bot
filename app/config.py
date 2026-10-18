"""Application configuration management and validation using Pydantic Settings."""

import re
from decimal import Decimal
from functools import lru_cache
from typing import Any, List, Optional
from zoneinfo import ZoneInfo
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram Bot Token (required)
    telegram_bot_token: SecretStr = Field(
        ...,
        validation_alias="TELEGRAM_BOT_TOKEN",
        description="Telegram bot token obtained from BotFather",
    )

    # Database URL (required)
    database_url: SecretStr = Field(
        ...,
        validation_alias="DATABASE_URL",
        description="SQLAlchemy database connection URL",
    )

    # Environment & Logging
    app_env: str = Field(
        default="development",
        validation_alias="APP_ENV",
        description="Application environment: development, testing, production",
    )
    log_level: str = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
        description="Logging severity level",
    )

    # Optional Administrator User IDs (parsed from comma-separated string or list)
    admin_user_ids: Any = Field(
        default_factory=list,
        validation_alias="ADMIN_USER_IDS",
        description="List of Telegram user IDs with administrative privileges",
    )

    # Configurable Rental Timezone (e.g., 'UTC', 'Africa/Nairobi')
    rental_timezone: str = Field(
        default="UTC",
        validation_alias="RENTAL_TIMEZONE",
        description="Timezone used for rental calendar calculations and operating hours",
    )

    # Phase 5: Overdue management & extension policies
    overdue_daily_fee: Decimal = Field(
        default=Decimal("5.00"),
        validation_alias="OVERDUE_DAILY_FEE",
        description="Daily overdue penalty fee in ETB",
    )
    extension_fee: Decimal = Field(
        default=Decimal("10.00"),
        validation_alias="EXTENSION_FEE",
        description="Fixed 5-day rental extension fee in ETB",
    )
    extension_duration_days: int = Field(
        default=5,
        validation_alias="EXTENSION_DURATION_DAYS",
        description="Rental extension duration in calendar days",
    )
    scheduler_interval_hours: int = Field(
        default=24,
        validation_alias="SCHEDULER_INTERVAL_HOURS",
        description="Daily scheduler execution interval in hours",
    )

    # Phase 8: Verification policies and notification options
    announce_new_books: bool = Field(
        default=False,
        validation_alias="ANNOUNCE_NEW_BOOKS",
        description="Broadcast announcement notifications to customers when new books are catalogued",
    )
    notification_retry_attempts: int = Field(
        default=1,
        validation_alias="NOTIFICATION_RETRY_ATTEMPTS",
        description="Number of retry attempts for failed Telegram event notifications",
    )
    id_retention_days: int = Field(
        default=365,
        validation_alias="ID_RETENTION_DAYS",
        description="Policy retention period in days for National ID verification artifacts",
    )
    consent_policy_version: str = Field(
        default="1.0",
        validation_alias="CONSENT_POLICY_VERSION",
        description="Active privacy and data collection policy version",
    )

    @field_validator("telegram_bot_token", mode="after")
    @classmethod
    def validate_bot_token(cls, v: SecretStr) -> SecretStr:
        token_str = v.get_secret_value().strip()
        if not token_str:
            raise ValueError("TELEGRAM_BOT_TOKEN cannot be empty.")
        # Telegram bot tokens follow pattern: <8-11 digits>:<alphanumeric string of >=20 chars>
        # Allow placeholder during tests if necessary, but ensure minimum format
        if not re.match(r"^\d{8,11}:[A-Za-z0-9_-]{20,}$", token_str):
            raise ValueError(
                "Invalid TELEGRAM_BOT_TOKEN format. Expected format: '<bot_id>:<secret_token>' "
                "(e.g., '123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ')."
            )
        return v

    @field_validator("database_url", mode="after")
    @classmethod
    def validate_database_url(cls, v: SecretStr) -> SecretStr:
        url_str = v.get_secret_value().strip()
        if not url_str:
            raise ValueError("DATABASE_URL cannot be empty.")

        # Normalize postgres:// to postgresql:// for SQLAlchemy compatibility
        if url_str.startswith("postgres://"):
            url_str = "postgresql://" + url_str[len("postgres://") :]
            return SecretStr(url_str)

        # Ensure supported scheme
        supported_schemes = ("postgresql://", "postgresql+psycopg2://", "postgresql+asyncpg://", "sqlite://")
        if not any(url_str.startswith(scheme) for scheme in supported_schemes):
            raise ValueError(
                f"Unsupported database scheme in DATABASE_URL. Supported schemes: {supported_schemes}"
            )
        return v

    @field_validator("app_env", mode="before")
    @classmethod
    def validate_app_env(cls, v: Any) -> str:
        if isinstance(v, str):
            val = v.strip().lower()
            allowed = {"development", "testing", "production"}
            if val not in allowed:
                raise ValueError(f"APP_ENV must be one of {allowed}, got: '{v}'")
            return val
        return "development"

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: Any) -> str:
        if isinstance(v, str):
            val = v.strip().upper()
            allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
            if val not in allowed:
                raise ValueError(f"LOG_LEVEL must be one of {allowed}, got: '{v}'")
            return val
        return "INFO"

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_user_ids(cls, v: Any) -> List[int]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            parts = [part.strip() for part in v.split(",") if part.strip()]
            result = []
            for item in parts:
                try:
                    result.append(int(item))
                except ValueError:
                    raise ValueError(f"Invalid admin user ID '{item}'; must be an integer.")
            return result
        if isinstance(v, (list, tuple)):
            return [int(x) for x in v]
        raise ValueError(f"Invalid format for ADMIN_USER_IDS: {v}")

    @field_validator("rental_timezone", mode="before")
    @classmethod
    def validate_rental_timezone(cls, v: Any) -> str:
        if v is None or v == "":
            return "UTC"
        if isinstance(v, str):
            tz_str = v.strip()
            try:
                ZoneInfo(tz_str)
                return tz_str
            except Exception as exc:
                raise ValueError(
                    f"Invalid RENTAL_TIMEZONE '{v}': must be a valid IANA timezone name (e.g. 'UTC', 'Africa/Nairobi')."
                ) from exc
        raise ValueError(f"Invalid RENTAL_TIMEZONE format: {v}")

    @property
    def raw_bot_token(self) -> str:
        """Returns the unmasked bot token string for API calls."""
        return self.telegram_bot_token.get_secret_value()

    @property
    def raw_database_url(self) -> str:
        """Returns the unmasked database connection URL for SQLAlchemy."""
        return self.database_url.get_secret_value()

    @property
    def owner_telegram_ids(self) -> List[int]:
        """Returns the list of authorized owner/admin Telegram user IDs."""
        return self.admin_user_ids

    @property
    def masked_bot_token(self) -> str:
        """Returns a safely masked bot token for logging and display."""
        raw = self.raw_bot_token
        if ":" in raw:
            bot_id, secret = raw.split(":", 1)
            return f"{bot_id}:***REDACTED***"
        return "***REDACTED***"

    @property
    def masked_database_url(self) -> str:
        """Returns a safely masked database URL with passwords redacted."""
        raw = self.raw_database_url
        return re.sub(r"(://[^:\s]+:)([^@\s]+)(@[^/\s]+)", r"\1***REDACTED***\3", raw)

    def __repr__(self) -> str:
        return (
            f"Settings("
            f"telegram_bot_token='{self.masked_bot_token}', "
            f"database_url='{self.masked_database_url}', "
            f"app_env='{self.app_env}', "
            f"log_level='{self.log_level}', "
            f"admin_user_ids={self.admin_user_ids})"
        )

    def __str__(self) -> str:
        return self.__repr__()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve cached application settings instance."""
    return Settings()
