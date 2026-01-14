"""Add VendorPayment.check_pdf_filename

Revision ID: 0f2c1a9b3e7d
Revises: dff8427b9ade
Create Date: 2026-01-14 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0f2c1a9b3e7d'
down_revision = 'dff8427b9ade'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vendor_payment') as batch_op:
        batch_op.add_column(sa.Column('check_pdf_filename', sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f('ix_vendor_payment_check_pdf_filename'), ['check_pdf_filename'], unique=False)


def downgrade():
    with op.batch_alter_table('vendor_payment') as batch_op:
        batch_op.drop_index(batch_op.f('ix_vendor_payment_check_pdf_filename'))
        batch_op.drop_column('check_pdf_filename')
