"""Add quote due date

Revision ID: 1c1b6c8a7d2e
Revises: 6b2f2f6c1a4f
Create Date: 2026-01-12 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1c1b6c8a7d2e'
down_revision = '6b2f2f6c1a4f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('quote', schema=None) as batch_op:
        batch_op.add_column(sa.Column('due_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('quote', schema=None) as batch_op:
        batch_op.drop_column('due_date')
