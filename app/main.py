"""Application entry point for BookRent Bot."""

import argparse
import logging
import sys
from pydantic import ValidationError

from app.bot.bot import create_bot_application
from app.config import get_settings
from app.database.health import startup_database_check
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)


def run_preflight_checks() -> bool:
    """Execute pre-flight checks: configuration validation and database connectivity.

    Returns:
        True if all pre-flight checks pass, False otherwise.
    """
    logger.info("Executing pre-flight checks...")
    try:
        settings = get_settings()
        logger.info("Configuration validated successfully.")
        logger.info("Environment: %s | Log Level: %s", settings.app_env, settings.log_level)
        logger.info("Database Target: %s", settings.masked_database_url)
        logger.info("Bot Token Target: %s", settings.masked_bot_token)
    except ValidationError as err:
        logger.critical("Configuration validation failed:\n%s", err)
        return False
    except Exception as exc:
        logger.critical("Unexpected error loading configuration: %s", exc)
        return False

    # Check database connectivity
    db_ok = startup_database_check()
    if not db_ok:
        logger.critical("Pre-flight database check failed. Startup aborted.")
        return False

    logger.info("All pre-flight checks passed successfully.")
    return True


def main() -> None:
    """Initialize logging, execute pre-flight checks, and start the Telegram Bot."""
    parser = argparse.ArgumentParser(description="BookRent Bot - Telegram Book Rental Management")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run pre-flight configuration and database health checks and exit.",
    )
    args = parser.parse_args()

    # Initial temporary logging setup
    setup_logging(log_level="INFO")

    try:
        settings = get_settings()
        # Re-configure logging with validated log level from environment
        setup_logging(log_level=settings.log_level)
    except Exception as exc:
        logger.critical(
            "Failed to load application settings. Ensure your .env file or environment variables "
            "are properly set up. Details: %s",
            exc,
        )
        sys.exit(1)

    logger.info("==================================================")
    logger.info("Starting BookRent Bot — Phase 1: Project Foundation")
    logger.info("==================================================")

    if not run_preflight_checks():
        logger.critical("Pre-flight checks failed. Exiting with status 1.")
        sys.exit(1)

    if args.check_only:
        logger.info("Pre-flight checks completed (--check-only flag provided). Exiting cleanly.")
        sys.exit(0)

    try:
        logger.info("Building Telegram Bot application...")
        application = create_bot_application()

        logger.info("Starting Telegram Bot polling loop. Press Ctrl+C to stop.")
        application.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Shutdown requested via KeyboardInterrupt. Stopping bot cleanly...")
    except Exception as exc:
        logger.critical("Fatal error encountered while running bot: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
