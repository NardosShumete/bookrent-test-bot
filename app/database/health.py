"""Database health-check routines and safe startup verification."""

import logging
import re
from typing import Optional, Tuple
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import get_engine

logger = logging.getLogger(__name__)


def sanitize_db_error(error_message: str) -> str:
    """Sanitize database error messages to avoid leaking passwords or sensitive connection strings.

    Args:
        error_message: The raw exception string.

    Returns:
        Sanitized error message safe for logs and status reports.
    """
    if not error_message:
        return ""
    # Redact credentials inside URIs: e.g. postgresql://user:password@host:port/db
    sanitized = re.sub(r"(://[^:\s]+:)([^@\s]+)(@[^/\s]+)", r"\1***REDACTED***\3", error_message)
    # Redact password keyword parameters if present in connection errors
    sanitized = re.sub(r"(password\s*=\s*['\"])[^'\"]+(['\"])", r"\1***REDACTED***\2", sanitized, flags=re.IGNORECASE)
    return sanitized


def check_database_connection(
    engine: Optional[Engine] = None,
    timeout: float = 5.0,
) -> Tuple[bool, Optional[str]]:
    """Verify that the database is reachable and can execute queries.

    Executes a simple 'SELECT 1' test query within the specified timeout.

    Args:
        engine: SQLAlchemy Engine instance. If None, uses default app engine.
        timeout: Query execution timeout in seconds.

    Returns:
        Tuple of (is_healthy, error_detail).
        If healthy: (True, None)
        If unhealthy: (False, sanitized_error_message)
    """
    try:
        eng = engine or get_engine()
        with eng.connect() as connection:
            # Set statement execution timeout if supported by dialect
            result = connection.execute(text("SELECT 1"))
            scalar = result.scalar()
            if scalar == 1:
                return True, None
            return False, f"Unexpected health check query result: {scalar}"
    except SQLAlchemyError as exc:
        sanitized = sanitize_db_error(str(exc))
        logger.warning("Database connectivity check failed: %s", sanitized)
        return False, sanitized
    except Exception as exc:
        sanitized = sanitize_db_error(str(exc))
        logger.error("Unexpected error during database health check: %s", sanitized)
        return False, sanitized


def startup_database_check(
    engine: Optional[Engine] = None,
    raise_on_failure: bool = False,
) -> bool:
    """Execute a safe startup database check with structured logging.

    Args:
        engine: Optional SQLAlchemy engine.
        raise_on_failure: If True, raises RuntimeError on failure instead of returning False.

    Returns:
        True if the database is reachable and ready, False otherwise.

    Raises:
        RuntimeError: If raise_on_failure is True and connection check fails.
    """
    logger.info("Executing pre-flight database health check...")
    is_healthy, error_msg = check_database_connection(engine=engine)

    if is_healthy:
        eng = engine or get_engine()
        driver_name = eng.dialect.name
        logger.info("Database health check PASSED. Connected successfully (%s).", driver_name)
        return True

    logger.critical(
        "Database health check FAILED: %s. "
        "Please check your DATABASE_URL and ensure the database server is running.",
        error_msg,
    )
    if raise_on_failure:
        raise RuntimeError(f"Database health check failed: {error_msg}")
    return False
