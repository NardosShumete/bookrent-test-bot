"""Database engine configuration, connection pooling, and session management."""

import logging
from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker[Session]] = None


def get_engine(database_url: Optional[str] = None, echo: bool = False) -> Engine:
    """Create or retrieve the SQLAlchemy engine with connection pooling.
w
    Args:
        database_url: Optional explicit database URL. If omitted, uses settings.
        echo: If True, logs SQL statements (useful for debugging).

    Returns:
        Configured SQLAlchemy Engine instance.
    """
    global _engine
    if _engine is not None and database_url is None:
        return _engine

    url = database_url or get_settings().raw_database_url

    engine_kwargs = {
        "echo": echo,
        "future": True,
    }

    if url.startswith("sqlite"):
        # SQLite-specific connection parameters for thread safety in tests
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL connection pool settings for high resilience
        engine_kwargs.update(
            {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_pre_ping": True,  # Verifies connection liveness before checkout
                "pool_recycle": 1800,  # Recycle connections after 30 minutes
                "pool_timeout": 30,  # Timeout waiting for pool connection
            }
        )

    new_engine = create_engine(url, **engine_kwargs)

    if database_url is None:
        _engine = new_engine

    return new_engine


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Create or retrieve a sessionmaker bound to the given or default engine."""
    global _session_factory
    eng = engine or get_engine()
    if _session_factory is not None and engine is None:
        return _session_factory

    factory = sessionmaker(
        bind=eng,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )

    if engine is None:
        _session_factory = factory

    return factory


@contextmanager
def get_db_session(
    factory: Optional[sessionmaker[Session]] = None,
) -> Generator[Session, None, None]:
    """Context manager for transactional database sessions.

    Automatically commits on normal exit, rolls back on exception,
    and guarantees session closure.

    Yields:
        Active SQLAlchemy Session.
    """
    session_creator = factory or get_session_factory()
    session: Session = session_creator()
    try:
        yield session
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Database session transaction rolled back due to error: %s", exc)
        raise
    finally:
        session.close()


def reset_db_state() -> None:
    """Dispose active engine and clear cached engine and session factory.

    Useful for test suites when switching databases or URLs.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
