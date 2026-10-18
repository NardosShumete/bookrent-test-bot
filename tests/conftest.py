"""Pytest fixtures and test environment configuration."""

import os
from typing import Generator
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.database.base import Base
from app.database.session import reset_db_state


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests run in an isolated environment without relying on external .env."""
    orig_env_file = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    # Clear the lru_cache for get_settings before and after each test
    get_settings.cache_clear()
    reset_db_state()
    yield
    Settings.model_config["env_file"] = orig_env_file
    get_settings.cache_clear()
    reset_db_state()


@pytest.fixture
def valid_env_vars(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Set standard valid environment variables for testing."""
    env = {
        "TELEGRAM_BOT_TOKEN": "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_123456",
        "DATABASE_URL": "sqlite:///:memory:",
        "APP_ENV": "testing",
        "LOG_LEVEL": "DEBUG",
        "ADMIN_USER_IDS": "12345,67890",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def sqlite_engine():
    """Create an in-memory SQLite engine for fast, isolated database testing."""
    import app.database.session as session_mod
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session_mod._engine = engine
    session_mod._session_factory = factory

    yield engine

    engine.dispose()
    session_mod.reset_db_state()


@pytest.fixture
def sqlite_session_factory(sqlite_engine):
    """Create a sessionmaker bound to the in-memory SQLite engine."""
    import app.database.session as session_mod
    return session_mod.get_session_factory()


@pytest.fixture
def db_session(sqlite_engine, sqlite_session_factory) -> Generator[Session, None, None]:
    """Yield an active transactional database session for model and service tests."""
    session: Session = sqlite_session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

