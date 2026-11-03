"""Add inactive privacy journal outbox prototype.

Revision ID: 5de7a40b6c12
Revises: 2a8d9e4f610b
"""
from alembic import op
import sqlalchemy as sa

revision = '5de7a40b6c12'
down_revision = '2a8d9e4f610b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'privacy_journal_outbox',
        sa.Column('event_id', sa.String(32), primary_key=True),
        sa.Column('user_key', sa.String(80), nullable=False),
        sa.Column('revision', sa.BigInteger(), nullable=False),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('credential_state', sa.JSON(), nullable=True),
        sa.Column('resource_id', sa.String(60), nullable=True),
        sa.Column('consent_state', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_key', 'revision', name='uq_privacy_journal_user_revision'),
        sa.CheckConstraint('revision > 0', name='ck_privacy_journal_revision_positive'),
        sa.CheckConstraint("action IN ('account_delete','consent_revoke','consent_grant','photo_revoke','credential_revoke',"
                           "'book_delete','character_delete','profile_delete','voice_delete','voice_revoke','share_revoke')",
                           name='ck_privacy_journal_action'),
    )
    op.create_index('ix_privacy_journal_unpublished', 'privacy_journal_outbox', ['published_at', 'created_at'])


def downgrade():
    # Removing a nonempty outbox can erase the only DB-side evidence needed to
    # recover an interrupted privacy event. Never silently downgrade it away.
    has_events = op.get_bind().execute(sa.text(
        'SELECT EXISTS (SELECT 1 FROM privacy_journal_outbox LIMIT 1)'
    )).scalar()
    if has_events:
        raise RuntimeError('Refusing to remove a nonempty privacy journal outbox')
    op.drop_index('ix_privacy_journal_unpublished', table_name='privacy_journal_outbox')
    op.drop_table('privacy_journal_outbox')
