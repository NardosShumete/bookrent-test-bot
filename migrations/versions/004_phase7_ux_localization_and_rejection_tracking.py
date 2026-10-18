"""UX localization and customer rejection tracking

Revision ID: 004_phase7_ux
Revises: 003_phase5
Create Date: 2026-10-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_phase7_ux'
down_revision: Union[str, None] = '003_phase5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('customers') as batch_op:
        batch_op.add_column(
            sa.Column('language', sa.String(length=10), server_default='en', nullable=False)
        )
        batch_op.add_column(
            sa.Column('rejection_reason', sa.String(length=500), nullable=True)
        )
        batch_op.add_column(
            sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('customers') as batch_op:
        batch_op.drop_column('rejected_at')
        batch_op.drop_column('rejection_reason')
        batch_op.drop_column('language')
