"""Add invoice side notes

Revision ID: 2a7c8d9e0f1b
Revises: 9f3a2c1d4e5f
Create Date: 2026-01-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2a7c8d9e0f1b'
down_revision = '9f3a2c1d4e5f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.add_column(sa.Column('side_notes', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_column('side_notes')
