import logging
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.database.base import Base
import app.models  # Ensure all models are registered on Base.metadata

# Alembic Config object, which provides access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# Set target metadata for 'autogenerate' support
target_metadata = Base.metadata


def get_target_url() -> str:
    """Retrieve the database URL dynamically from settings or explicit config override."""
    override = config.get_main_option("sqlalchemy.url")
    default_placeholder = "postgresql+psycopg2://user:password@localhost/bookrent_db"
    if override and override != default_placeholder:
        return override
    try:
        settings = get_settings()
        return settings.raw_database_url
    except Exception as exc:
        logger.warning(
            "Could not load database URL from settings (%s); falling back to alembic.ini value.",
            exc,
        )
        return override or default_placeholder


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation we don't even need a DBAPI to be available.
    """
    url = get_target_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a connection with the context.
    """
    url = get_target_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
