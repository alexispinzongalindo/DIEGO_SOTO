"""Add app settings

Revision ID: 6b2f2f6c1a4f
Revises: dff8427b9ade
Create Date: 2026-01-12 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b2f2f6c1a4f'
down_revision = 'dff8427b9ade'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_setting',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=True),
        sa.Column('value', sa.String(length=200), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_app_setting_key'), 'app_setting', ['key'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_app_setting_key'), table_name='app_setting')
    op.drop_table('app_setting')
