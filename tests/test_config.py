"""Tests for configuration loading, validation, and secret masking."""

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def test_valid_configuration(valid_env_vars: dict) -> None:
    """Verify that valid configuration loads successfully with correct types."""
    settings = get_settings()

    assert settings.app_env == "testing"
    assert settings.log_level == "DEBUG"
    assert settings.admin_user_ids == [12345, 67890]
    assert settings.raw_bot_token == valid_env_vars["TELEGRAM_BOT_TOKEN"]
    assert settings.raw_database_url == "sqlite:///:memory:"


def test_missing_telegram_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ValidationError when TELEGRAM_BOT_TOKEN is missing."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "TELEGRAM_BOT_TOKEN" in str(exc_info.value)


def test_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify ValidationError when DATABASE_URL is missing."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "DATABASE_URL" in str(exc_info.value)


@pytest.mark.parametrize(
    "invalid_token",
    [
        "",
        "invalid_token_without_colon",
        "abc:short",
        "123:short",
        ":ABCdefGhIJKlmNoPQRsTUVwxyZ_123456",
    ],
)
def test_invalid_telegram_token_format(monkeypatch: pytest.MonkeyPatch, invalid_token: str) -> None:
    """Verify that improperly formatted bot tokens fail validation."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", invalid_token)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    with pytest.raises(ValidationError):
        Settings()


def test_database_url_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that postgres:// URLs are converted to postgresql:// for SQLAlchemy."""
    raw_postgres_url = "postgres://user:secretpass@localhost:5432/bookrent"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.setenv("DATABASE_URL", raw_postgres_url)

    settings = Settings()
    assert settings.raw_database_url == "postgresql://user:secretpass@localhost:5432/bookrent"


def test_unsupported_database_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that invalid database schemes are rejected."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://user:pass@localhost/db")

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "Unsupported database scheme" in str(exc_info.value)


@pytest.mark.parametrize("invalid_env", ["staging", "local", "invalid_env"])
def test_invalid_app_env(monkeypatch: pytest.MonkeyPatch, invalid_env: str) -> None:
    """Verify invalid APP_ENV values are rejected."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("APP_ENV", invalid_env)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("invalid_log_level", ["VERBOSE", "TRACE", "WARN"])
def test_invalid_log_level(monkeypatch: pytest.MonkeyPatch, invalid_log_level: str) -> None:
    """Verify invalid LOG_LEVEL values are rejected."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("LOG_LEVEL", invalid_log_level)

    with pytest.raises(ValidationError):
        Settings()


def test_admin_user_ids_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify parsing of comma-separated string, empty string, and invalid items."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    # Empty string should yield empty list
    monkeypatch.setenv("ADMIN_USER_IDS", "")
    assert Settings().admin_user_ids == []

    # Comma-separated with spaces
    monkeypatch.setenv("ADMIN_USER_IDS", " 111 , 222, 333 ")
    assert Settings().admin_user_ids == [111, 222, 333]

    # Non-integer should raise error
    monkeypatch.setenv("ADMIN_USER_IDS", "111, not_a_number")
    with pytest.raises(ValidationError):
        Settings()


def test_secret_masking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that credentials and tokens are NEVER exposed in str or repr."""
    raw_token = "987654321:VerySecretBotTokenStringHere_ABCXYZ"
    raw_db_url = "postgresql+psycopg2://postgres:super_secret_db_pass@localhost:5432/bookrent"

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", raw_token)
    monkeypatch.setenv("DATABASE_URL", raw_db_url)

    settings = Settings()

    # Raw values are available via properties for internal use
    assert settings.raw_bot_token == raw_token
    assert settings.raw_database_url == raw_db_url

    # Masked properties
    assert "super_secret_db_pass" not in settings.masked_database_url
    assert "***REDACTED***" in settings.masked_database_url
    assert "VerySecretBotTokenStringHere" not in settings.masked_bot_token
    assert "987654321:***REDACTED***" == settings.masked_bot_token

    # str and repr must NOT contain secrets
    repr_str = repr(settings)
    assert "super_secret_db_pass" not in repr_str
    assert "VerySecretBotTokenStringHere" not in repr_str
    assert str(settings) == repr_str
