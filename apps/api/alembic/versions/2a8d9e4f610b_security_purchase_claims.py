"""Preserve purchase grants and store funding across account lifecycle changes."""
import hashlib

from alembic import op
import sqlalchemy as sa

revision = "2a8d9e4f610b"
down_revision = "09102fac8e63"
branch_labels = None
depends_on = None


def upgrade():
    claims = op.create_table(
        "iap_purchase_claims",
        sa.Column("transaction_digest", sa.String(64), primary_key=True),
    )
    op.add_column("subscriptions", sa.Column(
        "calendar_refill_enabled", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT platform, store_transaction_id, transaction_id FROM iap_receipts"
    ))
    digests = {
        hashlib.sha256(f"{platform}\0{store_id or client_id}".encode()).hexdigest()
        for platform, store_id, client_id in rows
    }
    if digests:
        op.bulk_insert(claims, [{"transaction_digest": digest} for digest in sorted(digests)])
    # Existing funding is not provable after historical receipt detachment.
    # Preserve access periods, but require positive authorization for new
    # calendar refills. New local grants explicitly opt in via the ORM.
    # Repair foreign series associations created before ownership enforcement.
    bind.execute(sa.text(
        "UPDATE books SET series_id = NULL, series_index = NULL WHERE series_id IN "
        "(SELECT id FROM series WHERE series.user_key <> books.user_key)"
    ))


def downgrade():
    op.drop_column("subscriptions", "calendar_refill_enabled")
    op.drop_table("iap_purchase_claims")
