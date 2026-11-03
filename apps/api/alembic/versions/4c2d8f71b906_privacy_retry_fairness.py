"""Add a persistent privacy publication retry cursor.

Revision ID: 4c2d8f71b906
Revises: d52b81c9a734
"""
from alembic import op
import sqlalchemy as sa

revision = '4c2d8f71b906'
down_revision = 'd52b81c9a734'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('privacy_journal_retry_cursor',
        sa.Column('name', sa.String(32), primary_key=True),
        sa.Column('cursor_created_at', sa.DateTime(), nullable=True),
        sa.Column('cursor_event_id', sa.String(32), nullable=True),
        sa.Column('upper_created_at', sa.DateTime(), nullable=True),
        sa.Column('upper_event_id', sa.String(32), nullable=True),
        sa.CheckConstraint('(cursor_created_at IS NULL) = (cursor_event_id IS NULL)',
                           name='ck_privacy_retry_cursor_pair'),
        sa.CheckConstraint('(upper_created_at IS NULL) = (upper_event_id IS NULL)',
                           name='ck_privacy_retry_upper_pair'))


def downgrade():
    # No privacy event is deleted, but resetting an active sweep could starve
    # older work after downgrade. Require the queue to be empty first.
    pending = op.get_bind().execute(sa.text(
        'SELECT EXISTS (SELECT 1 FROM privacy_journal_outbox WHERE published_at IS NULL)'
    )).scalar()
    if pending:
        raise RuntimeError('Cannot drop privacy retry cursor while publication remains pending')
    op.drop_table('privacy_journal_retry_cursor')
