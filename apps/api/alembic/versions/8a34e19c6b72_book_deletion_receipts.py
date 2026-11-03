"""Add scoped book-deletion receipts and journal metadata.

Revision ID: 8a34e19c6b72
Revises: 7e28d9a6b451
"""
from alembic import op
import sqlalchemy as sa

revision = '8a34e19c6b72'
down_revision = '7e28d9a6b451'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'book_deletion_receipts',
        sa.Column('user_key', sa.String(80), nullable=False),
        sa.Column('request_id', sa.String(32), nullable=False),
        sa.Column('book_id', sa.String(60), nullable=False),
        sa.Column('profile_id', sa.String(60), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('user_key', 'request_id'),
    )
    with op.batch_alter_table('privacy_journal_outbox') as batch:
        batch.add_column(sa.Column('deletion_receipt', sa.JSON(none_as_null=True), nullable=True))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT EXISTS (SELECT 1 FROM book_deletion_receipts LIMIT 1)')).scalar():
        raise RuntimeError('Cannot discard deletion receipt evidence')
    if connection.execute(sa.text(
        'SELECT EXISTS (SELECT 1 FROM privacy_journal_outbox WHERE deletion_receipt IS NOT NULL LIMIT 1)'
    )).scalar():
        raise RuntimeError('Cannot discard journal deletion receipt metadata')
    with op.batch_alter_table('privacy_journal_outbox') as batch:
        batch.drop_column('deletion_receipt')
    op.drop_table('book_deletion_receipts')
