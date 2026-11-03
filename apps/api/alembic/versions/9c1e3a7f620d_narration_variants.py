"""Separate built-in narration voice caches from legacy audio.

Revision ID: 9c1e3a7f620d
Revises: 5de7a40b6c12
"""
from alembic import op
import sqlalchemy as sa

revision = '9c1e3a7f620d'
down_revision = '5de7a40b6c12'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'narration_variants',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('page_id', sa.Integer(), sa.ForeignKey('pages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('language', sa.String(2), nullable=False),
        sa.Column('voice', sa.String(16), nullable=False),
        sa.Column('audio_url', sa.String(500), nullable=False),
        sa.UniqueConstraint('page_id', 'language', 'voice', name='uq_narration_variant'),
        sa.CheckConstraint("voice IN ('warm','deep')", name='ck_narration_variant_voice'),
    )
    op.create_index('ix_narration_variants_page_id', 'narration_variants', ['page_id'])


def downgrade():
    # A database rollback must never silently erase generated narration or
    # orphan its storage objects. Operators must first reconcile and retire
    # every variant through the normal privacy-aware deletion workflow.
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT COUNT(*) FROM narration_variants')).scalar():
        raise RuntimeError('Cannot downgrade while narration variants exist')
    op.drop_index('ix_narration_variants_page_id', table_name='narration_variants')
    op.drop_table('narration_variants')
