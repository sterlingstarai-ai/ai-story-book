"""Add persistent, global Gemini TTS request admissions.

Revision ID: d52b81c9a734
Revises: b3f149ac52d7
"""
from alembic import op
import sqlalchemy as sa

revision = 'd52b81c9a734'
down_revision = 'b3f149ac52d7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('gemini_tts_request_budget',
        sa.Column('bucket', sa.String(20), primary_key=True),
        sa.Column('requests', sa.Integer(), nullable=False),
        sa.CheckConstraint('requests >= 0', name='ck_gemini_tts_budget_nonnegative'))


def downgrade():
    # Losing spent-admission history could silently reopen paid requests.
    if op.get_bind().execute(sa.text('SELECT EXISTS (SELECT 1 FROM gemini_tts_request_budget LIMIT 1)')).scalar():
        raise RuntimeError('Cannot discard Gemini TTS request budget history')
    op.drop_table('gemini_tts_request_budget')
