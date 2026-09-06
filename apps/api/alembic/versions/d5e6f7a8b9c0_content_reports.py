"""Persist in-app reports without copying story content.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""

import sqlalchemy as sa
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_reports",
        sa.Column("id", sa.String(60), primary_key=True),
        sa.Column("book_id", sa.String(60), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolution", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("book_id", "page_number", "reason", "content_fingerprint",
                            name="uq_content_report_version_reason"),
    )
    op.create_index("ix_content_reports_status_created", "content_reports", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("content_reports")
