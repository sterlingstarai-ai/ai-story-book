"""Add independent account recovery credentials without rewriting ownership.

Revision ID: c4d5e6f7a8b9
Revises: b1c2d3e4f5a6
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_identities",
        sa.Column("user_key", sa.String(80), primary_key=True),
        sa.Column("device_key_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("recovery_code_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("previous_recovery_code_hash", sa.String(64), nullable=True),
        sa.Column("recovery_code_created_at", sa.DateTime(), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_account_identities_previous_recovery_code_hash",
        "account_identities",
        ["previous_recovery_code_hash"],
    )


def downgrade() -> None:
    # Removing this table re-enables old bearer credentials. Never allow an
    # automated rollback to remove revocation state after enrollment.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM account_identities")).scalar()
    if count:
        raise RuntimeError("Cannot remove account revocation state after enrollment")
    op.drop_table("account_identities")
