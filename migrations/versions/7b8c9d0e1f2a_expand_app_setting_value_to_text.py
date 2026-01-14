"""Expand app_setting.value to Text

Revision ID: 7b8c9d0e1f2a
Revises: 4c6d7e8f9a0b
Create Date: 2026-01-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7b8c9d0e1f2a'
down_revision = '4c6d7e8f9a0b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('app_setting') as batch_op:
        batch_op.alter_column(
            'value',
            existing_type=sa.String(length=200),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table('app_setting') as batch_op:
        batch_op.alter_column(
            'value',
            existing_type=sa.Text(),
            type_=sa.String(length=200),
            existing_nullable=True,
        )
