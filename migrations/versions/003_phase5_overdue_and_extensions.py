"""Phase 5: Overdue charges, rental extension payments, and returns

Revision ID: 003_phase5
Revises: 002_phase4
Create Date: 2026-10-16 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_phase5'
down_revision: Union[str, None] = '002_phase4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. overdue_charges table
    op.create_table(
        'overdue_charges',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rental_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('overdue_date', sa.Date(), nullable=False),
        sa.Column('day_number', sa.Integer(), server_default='1', nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('notification_sent', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('notification_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rental_id'], ['rentals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rental_id', 'overdue_date', name='uq_overdue_charges_rental_date'),
        sa.CheckConstraint('amount >= 0', name='ck_overdue_charges_amount_non_negative'),
        sa.CheckConstraint('day_number >= 1', name='ck_overdue_charges_day_number_positive'),
    )
    op.create_index(op.f('ix_overdue_charges_rental_id'), 'overdue_charges', ['rental_id'], unique=False)
    op.create_index(op.f('ix_overdue_charges_customer_id'), 'overdue_charges', ['customer_id'], unique=False)
    op.create_index(op.f('ix_overdue_charges_overdue_date'), 'overdue_charges', ['overdue_date'], unique=False)

    # 2. Add payment verification columns to rental_extensions
    with op.batch_alter_table('rental_extensions') as batch_op:
        batch_op.add_column(
            sa.Column('payment_verified', sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column('payment_method', sa.String(length=30), nullable=True)
        )
        batch_op.add_column(
            sa.Column('payment_reference', sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column('payment_verified_at', sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column('payment_verified_by', sa.String(length=100), nullable=True)
        )

    # 3. Alter payments to support rental extensions and direct rental associations
    with op.batch_alter_table('payments') as batch_op:
        batch_op.alter_column('request_id', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(
            sa.Column('rental_id', sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('extension_id', sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_payments_rental_id', 'rentals', ['rental_id'], ['id'], ondelete='SET NULL'
        )
        batch_op.create_foreign_key(
            'fk_payments_extension_id', 'rental_extensions', ['extension_id'], ['id'], ondelete='SET NULL'
        )
        batch_op.create_index(batch_op.f('ix_payments_rental_id'), ['rental_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_payments_extension_id'), ['extension_id'], unique=False)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint('ck_payments_type_valid', 'payments', type_='check')
        op.create_check_constraint(
            'ck_payments_type_valid',
            'payments',
            "payment_type IN ('RENTAL_FEE', 'COLLATERAL_DEPOSIT', 'EXTENSION_FEE')",
        )
        op.drop_constraint('ck_payments_method_valid', 'payments', type_='check')
        op.create_check_constraint(
            'ck_payments_method_valid',
            'payments',
            "payment_method IN ('CASH', 'BANK_TRANSFER', 'NON_CASH_GUARANTEE', 'OTHER')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint('ck_payments_method_valid', 'payments', type_='check')
        op.create_check_constraint(
            'ck_payments_method_valid',
            'payments',
            "payment_method IN ('CASH', 'BANK_TRANSFER', 'NON_CASH_GUARANTEE')",
        )
        op.drop_constraint('ck_payments_type_valid', 'payments', type_='check')
        op.create_check_constraint(
            'ck_payments_type_valid',
            'payments',
            "payment_type IN ('RENTAL_FEE', 'COLLATERAL_DEPOSIT')",
        )

    # 1. Revert payments
    with op.batch_alter_table('payments') as batch_op:
        batch_op.drop_index(batch_op.f('ix_payments_extension_id'))
        batch_op.drop_index(batch_op.f('ix_payments_rental_id'))
        batch_op.drop_constraint('fk_payments_extension_id', type_='foreignkey')
        batch_op.drop_constraint('fk_payments_rental_id', type_='foreignkey')
        batch_op.drop_column('extension_id')
        batch_op.drop_column('rental_id')
        batch_op.alter_column('request_id', existing_type=sa.Integer(), nullable=False)

    # 2. Revert rental_extensions
    with op.batch_alter_table('rental_extensions') as batch_op:
        batch_op.drop_column('payment_verified_by')
        batch_op.drop_column('payment_verified_at')
        batch_op.drop_column('payment_reference')
        batch_op.drop_column('payment_method')
        batch_op.drop_column('payment_verified')

    # 3. Drop overdue_charges
    op.drop_index(op.f('ix_overdue_charges_overdue_date'), table_name='overdue_charges')
    op.drop_index(op.f('ix_overdue_charges_customer_id'), table_name='overdue_charges')
    op.drop_index(op.f('ix_overdue_charges_rental_id'), table_name='overdue_charges')
    op.drop_table('overdue_charges')
