"""Allow secret-free voice state change markers in the privacy outbox.

Revision ID: b3f149ac52d7
Revises: 8a34e19c6b72
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3f149ac52d7'
down_revision = '8a34e19c6b72'
branch_labels = None
depends_on = None

_OLD = ("action IN ('account_delete','consent_revoke','consent_grant','photo_revoke','credential_revoke',"
        "'book_delete','character_delete','profile_delete','voice_delete','voice_revoke','share_revoke')")
_NEW = ("action IN ('account_delete','consent_revoke','consent_grant','photo_revoke','credential_revoke',"
        "'book_delete','character_delete','profile_delete','voice_delete','voice_revoke','voice_changed','share_revoke')")


def _replace_constraint(value):
    with op.batch_alter_table('privacy_journal_outbox') as batch:
        batch.drop_constraint('ck_privacy_journal_action', type_='check')
        batch.create_check_constraint('ck_privacy_journal_action', value)


def upgrade():
    _replace_constraint(_NEW)


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM privacy_journal_outbox WHERE action = 'voice_changed' LIMIT 1)"
    )).scalar():
        raise RuntimeError('Cannot discard voice history evidence')
    _replace_constraint(_OLD)
