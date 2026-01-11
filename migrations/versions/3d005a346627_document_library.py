"""document library

Revision ID: 3d005a346627
Revises: 
Create Date: 2026-01-11 14:15:37.974752

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3d005a346627'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'project',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_project_created_at'), 'project', ['created_at'], unique=False)
    op.create_index(op.f('ix_project_name'), 'project', ['name'], unique=True)

    op.create_table(
        'library_document',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=20), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('stored_filename', sa.String(length=255), nullable=True),
        sa.Column('content_type', sa.String(length=120), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id']),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_library_document_category'), 'library_document', ['category'], unique=False)
    op.create_index(op.f('ix_library_document_created_at'), 'library_document', ['created_at'], unique=False)
    op.create_index(op.f('ix_library_document_owner_id'), 'library_document', ['owner_id'], unique=False)
    op.create_index(op.f('ix_library_document_project_id'), 'library_document', ['project_id'], unique=False)
    op.create_index(op.f('ix_library_document_stored_filename'), 'library_document', ['stored_filename'], unique=True)
    op.create_index(op.f('ix_library_document_title'), 'library_document', ['title'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_library_document_title'), table_name='library_document')
    op.drop_index(op.f('ix_library_document_stored_filename'), table_name='library_document')
    op.drop_index(op.f('ix_library_document_project_id'), table_name='library_document')
    op.drop_index(op.f('ix_library_document_owner_id'), table_name='library_document')
    op.drop_index(op.f('ix_library_document_created_at'), table_name='library_document')
    op.drop_index(op.f('ix_library_document_category'), table_name='library_document')
    op.drop_table('library_document')

    op.drop_index(op.f('ix_project_name'), table_name='project')
    op.drop_index(op.f('ix_project_created_at'), table_name='project')
    op.drop_table('project')
