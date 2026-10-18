"""Phase 4: Rental requests and payment verification schema

Revision ID: 002_phase4
Revises: 001_phase2
Create Date: 2026-10-16 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_phase4'
down_revision: Union[str, None] = '001_phase2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. rental_requests
    op.create_table(
        'rental_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('copy_id', sa.Integer(), nullable=True),
        sa.Column('rental_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='SUBMITTED', nullable=False),
        sa.Column('collateral_type', sa.String(length=20), server_default='MONETARY', nullable=False),
        sa.Column('guarantee_details', sa.Text(), nullable=True),
        sa.Column('rental_fee', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('rental_fee_paid', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('collateral_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('collateral_received', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', sa.String(length=100), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['copy_id'], ['book_copies.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['rental_id'], ['rentals.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED', 'COMPLETED')",
            name='ck_rental_requests_status_valid',
        ),
        sa.CheckConstraint(
            "collateral_type IN ('MONETARY', 'GUARANTEE')",
            name='ck_rental_requests_collateral_type_valid',
        ),
        sa.CheckConstraint('rental_fee >= 0', name='ck_rental_requests_fee_non_negative'),
        sa.CheckConstraint(
            'collateral_amount IS NULL OR collateral_amount >= 0',
            name='ck_rental_requests_collateral_non_negative',
        ),
    )
    op.create_index(op.f('ix_rental_requests_customer_id'), 'rental_requests', ['customer_id'], unique=False)
    op.create_index(op.f('ix_rental_requests_book_id'), 'rental_requests', ['book_id'], unique=False)
    op.create_index(op.f('ix_rental_requests_copy_id'), 'rental_requests', ['copy_id'], unique=False)
    op.create_index(op.f('ix_rental_requests_rental_id'), 'rental_requests', ['rental_id'], unique=False)
    op.create_index(op.f('ix_rental_requests_status'), 'rental_requests', ['status'], unique=False)

    # 2. payments
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('payment_type', sa.String(length=30), nullable=False),
        sa.Column('payment_method', sa.String(length=30), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('verification_status', sa.String(length=30), server_default='PENDING_VERIFICATION', nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_by', sa.String(length=100), nullable=True),
        sa.Column('reference', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['request_id'], ['rental_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('amount >= 0', name='ck_payments_amount_non_negative'),
        sa.CheckConstraint(
            "verification_status IN ('PENDING_VERIFICATION', 'VERIFIED', 'REJECTED')",
            name='ck_payments_verification_status_valid',
        ),
        sa.CheckConstraint(
            "payment_type IN ('RENTAL_FEE', 'COLLATERAL_DEPOSIT')",
            name='ck_payments_type_valid',
        ),
        sa.CheckConstraint(
            "payment_method IN ('CASH', 'BANK_TRANSFER', 'NON_CASH_GUARANTEE')",
            name='ck_payments_method_valid',
        ),
    )
    op.create_index(op.f('ix_payments_customer_id'), 'payments', ['customer_id'], unique=False)
    op.create_index(op.f('ix_payments_payment_method'), 'payments', ['payment_method'], unique=False)
    op.create_index(op.f('ix_payments_payment_type'), 'payments', ['payment_type'], unique=False)
    op.create_index(op.f('ix_payments_request_id'), 'payments', ['request_id'], unique=False)
    op.create_index(op.f('ix_payments_verification_status'), 'payments', ['verification_status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_payments_verification_status'), table_name='payments')
    op.drop_index(op.f('ix_payments_request_id'), table_name='payments')
    op.drop_index(op.f('ix_payments_payment_type'), table_name='payments')
    op.drop_index(op.f('ix_payments_payment_method'), table_name='payments')
    op.drop_index(op.f('ix_payments_customer_id'), table_name='payments')
    op.drop_table('payments')

    op.drop_index(op.f('ix_rental_requests_status'), table_name='rental_requests')
    op.drop_index(op.f('ix_rental_requests_rental_id'), table_name='rental_requests')
    op.drop_index(op.f('ix_rental_requests_copy_id'), table_name='rental_requests')
    op.drop_index(op.f('ix_rental_requests_book_id'), table_name='rental_requests')
    op.drop_index(op.f('ix_rental_requests_customer_id'), table_name='rental_requests')
    op.drop_table('rental_requests')
