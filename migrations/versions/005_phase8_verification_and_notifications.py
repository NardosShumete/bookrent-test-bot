"""Phase 8: Customer verification (National ID, Phone, Location) and event notifications

Revision ID: 005_phase8
Revises: 004_phase7_ux
Create Date: 2026-10-18 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_phase8'
down_revision: Union[str, None] = '004_phase7_ux'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('customers') as batch_op:
        batch_op.add_column(
            sa.Column('phone_verified', sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column('phone_source', sa.String(length=30), nullable=True)
        )
        batch_op.add_column(
            sa.Column('address', sa.String(length=500), nullable=True)
        )
        batch_op.add_column(
            sa.Column('latitude', sa.Numeric(precision=10, scale=7), nullable=True)
        )
        batch_op.add_column(
            sa.Column('longitude', sa.Numeric(precision=10, scale=7), nullable=True)
        )
        batch_op.add_column(
            sa.Column('national_id_file_id', sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column('national_id_uploaded_at', sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column('consent_given', sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column('consent_timestamp', sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column('consent_policy_version', sa.String(length=20), nullable=True)
        )
        batch_op.add_column(
            sa.Column('registration_completed_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('customers') as batch_op:
        batch_op.drop_column('registration_completed_at')
        batch_op.drop_column('consent_policy_version')
        batch_op.drop_column('consent_timestamp')
        batch_op.drop_column('consent_given')
        batch_op.drop_column('national_id_uploaded_at')
        batch_op.drop_column('national_id_file_id')
        batch_op.drop_column('longitude')
        batch_op.drop_column('latitude')
        batch_op.drop_column('address')
        batch_op.drop_column('phone_source')
        batch_op.drop_column('phone_verified')
