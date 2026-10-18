"""Tests for pre-flight startup checks and bot application initialization."""

import pytest
from sqlalchemy import create_engine

from app.bot.bot import create_bot_application
from app.config import get_settings
from app.database.health import startup_database_check
from app.main import run_preflight_checks
from app.scheduler.overdue_job import setup_overdue_scheduler


def test_startup_database_check_success(sqlite_engine) -> None:
    """Verify startup_database_check logs success and returns True."""
    assert startup_database_check(engine=sqlite_engine) is True


def test_startup_database_check_failure_returns_false() -> None:
    """Verify startup_database_check returns False when database is unreachable."""
    bad_engine = create_engine(
        "postgresql+psycopg2://bad_user:secret_pwd@127.0.0.1:54329/nonexistent_db",
        connect_args={"connect_timeout": 1},
    )
    result = startup_database_check(engine=bad_engine, raise_on_failure=False)
    assert result is False
    bad_engine.dispose()


def test_startup_database_check_failure_raises() -> None:
    """Verify startup_database_check raises RuntimeError when raise_on_failure=True."""
    bad_engine = create_engine(
        "postgresql+psycopg2://bad_user:secret_pwd@127.0.0.1:54329/nonexistent_db",
        connect_args={"connect_timeout": 1},
    )
    with pytest.raises(RuntimeError) as exc_info:
        startup_database_check(engine=bad_engine, raise_on_failure=True)
    assert "Database health check failed" in str(exc_info.value)
    bad_engine.dispose()


def test_run_preflight_checks_success(valid_env_vars: dict) -> None:
    """Verify run_preflight_checks succeeds with valid env and accessible database."""
    # valid_env_vars sets DATABASE_URL to sqlite:///:memory:
    assert run_preflight_checks() is True


def test_run_preflight_checks_invalid_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify run_preflight_checks fails safely if configuration is incomplete."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()

    assert run_preflight_checks() is False


def test_create_bot_application_initialization(valid_env_vars: dict) -> None:
    """Verify create_bot_application creates a python-telegram-bot Application with registered handlers."""
    app = create_bot_application()
    assert app is not None

    # Verify handlers are registered in handler groups
    handlers = app.handlers.get(0, [])
    commands = [h.commands for h in handlers if hasattr(h, "commands")]
    flattened_commands = {cmd for cmd_set in commands for cmd in cmd_set}

    assert "start" in flattened_commands
    assert "help" in flattened_commands
    assert "ping" in flattened_commands


def test_setup_overdue_scheduler_duplicate_prevention(valid_env_vars: dict) -> None:
    """Verify that calling setup_overdue_scheduler multiple times does not register duplicate jobs."""
    app = create_bot_application()
    assert app.job_queue is not None

    jobs_initial = app.job_queue.get_jobs_by_name("daily_overdue_processor")
    assert len(jobs_initial) == 1

    # Call setup again
    result = setup_overdue_scheduler(app)
    assert result is True

    # Verify still exactly 1 job registered
    jobs_after = app.job_queue.get_jobs_by_name("daily_overdue_processor")
    assert len(jobs_after) == 1


def test_setup_overdue_scheduler_no_job_queue() -> None:
    """Verify setup_overdue_scheduler gracefully handles application without job_queue."""
    from unittest.mock import MagicMock
    mock_app = MagicMock()
    mock_app.job_queue = None
    result = setup_overdue_scheduler(mock_app)
    assert result is False

