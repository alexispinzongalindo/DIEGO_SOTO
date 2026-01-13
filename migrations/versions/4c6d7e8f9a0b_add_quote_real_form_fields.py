"""Add real quote form fields

Revision ID: 4c6d7e8f9a0b
Revises: 2a7c8d9e0f1b
Create Date: 2026-01-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4c6d7e8f9a0b'
down_revision = '2a7c8d9e0f1b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('quote', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('rep', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('customer_tel', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('customer_fax', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('printed_notes', sa.Text(), nullable=True))

    with op.batch_alter_table('quote_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unit', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('quote_item', schema=None) as batch_op:
        batch_op.drop_column('unit')

    with op.batch_alter_table('quote', schema=None) as batch_op:
        batch_op.drop_column('printed_notes')
        batch_op.drop_column('customer_fax')
        batch_op.drop_column('customer_tel')
        batch_op.drop_column('rep')
        batch_op.drop_column('project')
