"""Phase 2: Inventory, rental, customer, ledger, and audit log schema

Revision ID: 001_phase2
Revises: None
Create Date: 2026-10-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_phase2'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. books
    op.create_table(
        'books',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('isbn', sa.String(length=17), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('author', sa.String(length=255), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('rental_price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint('rental_price >= 0', name='ck_books_rental_price_non_negative'),
        sa.CheckConstraint('page_count IS NULL OR page_count > 0', name='ck_books_page_count_positive'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('isbn', name='uq_books_isbn'),
    )
    op.create_index(op.f('ix_books_author'), 'books', ['author'], unique=False)
    op.create_index(op.f('ix_books_category'), 'books', ['category'], unique=False)
    op.create_index(op.f('ix_books_isbn'), 'books', ['isbn'], unique=True)
    op.create_index(op.f('ix_books_title'), 'books', ['title'], unique=False)

    # 2. book_copies
    op.create_table(
        'book_copies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('copy_number', sa.Integer(), nullable=False),
        sa.Column('barcode', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='ON_SHELF', nullable=False),
        sa.Column('condition_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("status IN ('ON_SHELF', 'RESERVED', 'RENTED', 'OVERDUE', 'DAMAGED', 'LOST')", name='ck_book_copies_status_valid'),
        sa.CheckConstraint('copy_number > 0', name='ck_book_copies_copy_number_positive'),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('barcode', name='uq_book_copies_barcode'),
        sa.UniqueConstraint('book_id', 'copy_number', name='uq_book_copies_book_id_copy_number'),
    )
    op.create_index(op.f('ix_book_copies_barcode'), 'book_copies', ['barcode'], unique=True)
    op.create_index(op.f('ix_book_copies_book_id'), 'book_copies', ['book_id'], unique=False)
    op.create_index(op.f('ix_book_copies_status'), 'book_copies', ['status'], unique=False)

    # 3. customers
    op.create_table(
        'customers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=True),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=True),
        sa.Column('phone_number', sa.String(length=30), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'SUSPENDED', 'REJECTED')", name='ck_customers_status_valid'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_id', name='uq_customers_telegram_id'),
    )
    op.create_index(op.f('ix_customers_status'), 'customers', ['status'], unique=False)
    op.create_index(op.f('ix_customers_telegram_id'), 'customers', ['telegram_id'], unique=True)
    op.create_index(op.f('ix_customers_username'), 'customers', ['username'], unique=False)

    # 4. rentals
    op.create_table(
        'rentals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('copy_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('checkout_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('return_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='ACTIVE', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'EXTENDED', 'RETURNED', 'OVERDUE', 'CANCELLED')", name='ck_rentals_status_valid'),
        sa.CheckConstraint('due_date >= checkout_time', name='ck_rentals_due_date_after_checkout'),
        sa.ForeignKeyConstraint(['copy_id'], ['book_copies.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rentals_copy_id'), 'rentals', ['copy_id'], unique=False)
    op.create_index(op.f('ix_rentals_customer_id'), 'rentals', ['customer_id'], unique=False)
    op.create_index(op.f('ix_rentals_status'), 'rentals', ['status'], unique=False)
    # Partial unique index to prevent double active rental of the same copy
    op.create_index(
        'uq_active_rental_per_copy',
        'rentals',
        ['copy_id'],
        unique=True,
        postgresql_where=sa.text("return_time IS NULL AND status != 'CANCELLED'"),
        sqlite_where=sa.text("return_time IS NULL AND status != 'CANCELLED'"),
    )

    # 5. rental_extensions
    op.create_table(
        'rental_extensions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rental_id', sa.Integer(), nullable=False),
        sa.Column('requested_days', sa.Integer(), nullable=False),
        sa.Column('previous_due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('new_due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fee', sa.Numeric(precision=10, scale=2), server_default='0.00', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='REQUESTED', nullable=False),
        sa.Column('is_applied', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', sa.String(length=100), nullable=True),
        sa.CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'REJECTED')", name='ck_rental_extensions_status_valid'),
        sa.CheckConstraint('requested_days > 0', name='ck_rental_extensions_days_positive'),
        sa.CheckConstraint('new_due_date > previous_due_date', name='ck_rental_extensions_new_due_date_later'),
        sa.CheckConstraint('fee >= 0', name='ck_rental_extensions_fee_non_negative'),
        sa.ForeignKeyConstraint(['rental_id'], ['rentals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rental_extensions_rental_id'), 'rental_extensions', ['rental_id'], unique=False)
    op.create_index(op.f('ix_rental_extensions_status'), 'rental_extensions', ['status'], unique=False)

    # 6. collateral_ledger
    op.create_table(
        'collateral_ledger',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('rental_id', sa.Integer(), nullable=True),
        sa.Column('transaction_type', sa.String(length=30), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('collateral_balance_after', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('actor', sa.String(length=100), server_default='SYSTEM', nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint(
            "transaction_type IN ('RENTAL_FEE', 'COLLATERAL_DEPOSIT', 'EXTENSION_FEE', 'OVERDUE_PENALTY', 'COLLATERAL_DEDUCTION', 'COLLATERAL_REFUND')",
            name='ck_collateral_ledger_type_valid',
        ),
        sa.CheckConstraint('amount > 0', name='ck_collateral_ledger_amount_positive'),
        sa.CheckConstraint('collateral_balance_after IS NULL OR collateral_balance_after >= 0', name='ck_collateral_ledger_balance_non_negative'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['rental_id'], ['rentals.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_collateral_ledger_created_at'), 'collateral_ledger', ['created_at'], unique=False)
    op.create_index(op.f('ix_collateral_ledger_customer_id'), 'collateral_ledger', ['customer_id'], unique=False)
    op.create_index(op.f('ix_collateral_ledger_rental_id'), 'collateral_ledger', ['rental_id'], unique=False)
    op.create_index(op.f('ix_collateral_ledger_transaction_type'), 'collateral_ledger', ['transaction_type'], unique=False)

    # 7. audit_logs
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('actor', sa.String(length=100), server_default='SYSTEM', nullable=True),
        sa.Column('old_values', sa.JSON(), nullable=True),
        sa.Column('new_values', sa.JSON(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_entity_type'), 'audit_logs', ['entity_type'], unique=False)


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_table('collateral_ledger')
    op.drop_table('rental_extensions')
    op.drop_table('rentals')
    op.drop_table('customers')
    op.drop_table('book_copies')
    op.drop_table('books')
