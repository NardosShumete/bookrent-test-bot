"""Tests for database engine, session management, and health checks."""

import pytest
from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.health import check_database_connection, sanitize_db_error
from app.database.session import get_db_session, get_engine, get_session_factory, reset_db_state


class SampleModel(Base):
    __tablename__ = "test_items"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)


def test_base_metadata_is_declarative() -> None:
    """Verify Base is properly configured SQLAlchemy 2.x DeclarativeBase."""
    assert Base.metadata is not None
    assert "test_items" in Base.metadata.tables


def test_get_engine_sqlite_in_memory() -> None:
    """Verify get_engine creates a working engine with custom URL."""
    engine = get_engine("sqlite:///:memory:")
    assert engine is not None
    with engine.connect() as conn:
        res = conn.execute(text("SELECT 1")).scalar()
        assert res == 1
    engine.dispose()


def test_session_commit_success(sqlite_engine, sqlite_session_factory) -> None:
    """Verify get_db_session automatically commits changes upon normal exit."""
    # Create the test table in SQLite
    Base.metadata.create_all(bind=sqlite_engine)

    with get_db_session(sqlite_session_factory) as session:
        item = SampleModel(name="Test Item 1")
        session.add(item)

    # Read in a new session to confirm persistence
    with sqlite_session_factory() as session:
        queried = session.query(SampleModel).filter_by(name="Test Item 1").first()
        assert queried is not None
        assert queried.name == "Test Item 1"


def test_session_rollback_on_error(sqlite_engine, sqlite_session_factory) -> None:
    """Verify get_db_session rolls back uncommitted changes when an exception is raised."""
    Base.metadata.create_all(bind=sqlite_engine)

    with pytest.raises(RuntimeError):
        with get_db_session(sqlite_session_factory) as session:
            item = SampleModel(name="Should Rollback")
            session.add(item)
            raise RuntimeError("Intentional error to trigger rollback")

    # Read in a new session to confirm nothing was committed
    with sqlite_session_factory() as session:
        queried = session.query(SampleModel).filter_by(name="Should Rollback").first()
        assert queried is None


def test_check_database_connection_healthy(sqlite_engine) -> None:
    """Verify check_database_connection returns (True, None) for responsive DB."""
    is_healthy, error_msg = check_database_connection(engine=sqlite_engine)
    assert is_healthy is True
    assert error_msg is None


def test_check_database_connection_unhealthy() -> None:
    """Verify check_database_connection handles unreachable DB cleanly without uncaught crash."""
    # Non-existent server on unreachable port with quick failure
    bad_engine = create_engine(
        "postgresql+psycopg2://bad_user:secret_pwd@127.0.0.1:54329/nonexistent_db",
        connect_args={"connect_timeout": 1},
    )

    is_healthy, error_msg = check_database_connection(engine=bad_engine)
    assert is_healthy is False
    assert error_msg is not None
    # Verify password was not leaked into error message
    assert "secret_pwd" not in error_msg
    bad_engine.dispose()


def test_sanitize_db_error_redacts_credentials() -> None:
    """Verify sanitize_db_error masks sensitive connection credentials."""
    raw_error = "FATAL: password authentication failed for user 'postgres' at postgresql://user:my_secret_pass@127.0.0.1:5432/db"
    sanitized = sanitize_db_error(raw_error)
    assert "my_secret_pass" not in sanitized
    assert "***REDACTED***" in sanitized
