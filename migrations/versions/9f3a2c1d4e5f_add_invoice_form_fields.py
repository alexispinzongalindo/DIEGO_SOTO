"""Add invoice form fields

Revision ID: 9f3a2c1d4e5f
Revises: 1c1b6c8a7d2e
Create Date: 2026-01-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f3a2c1d4e5f'
down_revision = '1c1b6c8a7d2e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fax', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('alt_phone', sa.String(length=20), nullable=True))

    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.add_column(sa.Column('customer_po', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('rep', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('ship_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('ship_via', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('fob', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('project', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('bill_to_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('bill_to_address', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('ship_to_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('ship_to_address', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('authorized_signature', sa.String(length=120), nullable=True))

    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unit', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('invoice_item', schema=None) as batch_op:
        batch_op.drop_column('unit')

    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_column('authorized_signature')
        batch_op.drop_column('ship_to_address')
        batch_op.drop_column('ship_to_name')
        batch_op.drop_column('bill_to_address')
        batch_op.drop_column('bill_to_name')
        batch_op.drop_column('project')
        batch_op.drop_column('fob')
        batch_op.drop_column('ship_via')
        batch_op.drop_column('ship_date')
        batch_op.drop_column('rep')
        batch_op.drop_column('customer_po')

    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.drop_column('alt_phone')
        batch_op.drop_column('fax')
