"""Tests verifying Alembic schema migration execution, upgrade, and downgrade."""

import os
import tempfile
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_migration_upgrade_and_downgrade() -> None:
    """Verify that Alembic runs 001_phase2 migration forward and backward cleanly."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        sqlite_url = f"sqlite:///{db_path}"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", sqlite_url)

        # 1. Run upgrade to head
        command.upgrade(cfg, "head")

        # 2. Inspect created tables
        engine = create_engine(sqlite_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        expected_tables = {
            "books",
            "book_copies",
            "customers",
            "rentals",
            "rental_extensions",
            "collateral_ledger",
            "audit_logs",
            "rental_requests",
            "payments",
            "overdue_charges",
            "alembic_version",
        }
        for expected in expected_tables:
            assert expected in tables, f"Expected table '{expected}' not found in migrated database"

        # Verify key columns on overdue_charges (Phase 5)
        overdue_cols = {col["name"] for col in inspector.get_columns("overdue_charges")}
        assert {"id", "rental_id", "customer_id", "overdue_date", "day_number", "amount", "notification_sent", "notification_sent_at"}.issubset(
            overdue_cols
        )

        # Verify key columns on rental_extensions (Phase 5 additions)
        ext_cols = {col["name"] for col in inspector.get_columns("rental_extensions")}
        assert {"id", "rental_id", "requested_days", "new_due_date", "fee", "payment_verified", "payment_method"}.issubset(
            ext_cols
        )

        # Verify key columns on rental_requests
        req_cols = {col["name"] for col in inspector.get_columns("rental_requests")}
        assert {"id", "customer_id", "book_id", "copy_id", "status", "rental_fee", "collateral_received"}.issubset(
            req_cols
        )

        # Verify key columns on payments (Phase 5 additions)
        pay_cols = {col["name"] for col in inspector.get_columns("payments")}
        assert {"id", "request_id", "rental_id", "extension_id", "payment_type", "payment_method", "amount", "verification_status"}.issubset(
            pay_cols
        )

        # Verify key columns on rentals
        rental_cols = {col["name"] for col in inspector.get_columns("rentals")}
        assert {"id", "copy_id", "customer_id", "checkout_time", "due_date", "return_time", "status"}.issubset(
            rental_cols
        )

        # Verify key columns on books
        book_cols = {col["name"] for col in inspector.get_columns("books")}
        assert {"id", "isbn", "title", "author", "rental_price", "page_count", "category", "description"}.issubset(
            book_cols
        )

        # Verify key columns on collateral_ledger
        ledger_cols = {col["name"] for col in inspector.get_columns("collateral_ledger")}
        assert {"id", "customer_id", "rental_id", "transaction_type", "amount", "collateral_balance_after"}.issubset(
            ledger_cols
        )

        engine.dispose()

        # 3. Run downgrade to base
        command.downgrade(cfg, "base")

        engine = create_engine(sqlite_url)
        inspector = inspect(engine)
        remaining_tables = set(inspector.get_table_names())
        engine.dispose()

        for dropped in expected_tables - {"alembic_version"}:
            assert dropped not in remaining_tables, f"Table '{dropped}' was not dropped during downgrade"

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
