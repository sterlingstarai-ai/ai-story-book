"""Persist versioned character approval and photo-derived job references.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("photo_derived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("jobs", sa.Column("character_reference_url", sa.String(500), nullable=True))
    op.add_column("jobs", sa.Column("character_reference_version", sa.Integer(), nullable=True))
    op.add_column("characters", sa.Column("avatar_status", sa.String(20), nullable=False, server_default="not_required"))
    op.add_column("characters", sa.Column("avatar_url", sa.String(500), nullable=True))
    op.add_column("characters", sa.Column("avatar_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("characters", sa.Column("avatar_attempts", sa.Integer(), nullable=False, server_default="0"))
    for name in ("avatar_requested_at", "avatar_started_at", "avatar_expires_at", "avatar_approved_at"):
        op.add_column("characters", sa.Column(name, sa.DateTime(), nullable=True))
    op.add_column("characters", sa.Column("avatar_style", sa.String(40), nullable=True))
    op.add_column("characters", sa.Column("avatar_source_kind", sa.String(10), nullable=True))
    op.add_column("characters", sa.Column("avatar_error_code", sa.String(60), nullable=True))
    op.create_index("ix_characters_avatar_expires_at", "characters", ["avatar_expires_at"])

    # Legacy photo/drawing rows have never had a parent-approved portrait.
    # Never silently grandfather those originals into an approved reference.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    table = sa.table("characters", sa.column("from_photo"), sa.column("avatar_status"),
                     sa.column("avatar_expires_at"), sa.column("avatar_style"),
                     sa.column("avatar_source_kind"), sa.column("source_image_url"))
    op.execute(table.update().where(table.c.from_photo.is_(True)).values(
        avatar_status="failed", avatar_expires_at=now + timedelta(hours=24),
        avatar_style="watercolor", avatar_source_kind=sa.case(
            (table.c.source_image_url.like("%/drawing%"), "drawing"), else_="photo",
        ),
    ))
    # The durable Job marker retains lineage even if a character is removed later.
    op.execute(sa.text("""
        UPDATE jobs SET photo_derived = true WHERE id IN (
            SELECT b.job_id FROM books b JOIN characters c ON b.character_id = c.id
            WHERE c.from_photo = true
        )
    """))
    # JSON character_ids is database-portable when interpreted in Python.
    bind = op.get_bind()
    photo_ids = set(bind.execute(sa.text("SELECT id FROM characters WHERE from_photo = true")).scalars())
    books = sa.table("books", sa.column("job_id", sa.String()), sa.column("character_ids", sa.JSON()))
    jobs = sa.table("jobs", sa.column("id", sa.String()), sa.column("photo_derived", sa.Boolean()))
    for row in bind.execute(sa.select(books.c.job_id, books.c.character_ids)):
        if isinstance(row.character_ids, list) and photo_ids.intersection(row.character_ids):
            bind.execute(jobs.update().where(jobs.c.id == row.job_id).values(photo_derived=True))


def downgrade() -> None:
    op.drop_index("ix_characters_avatar_expires_at", table_name="characters")
    for name in ("avatar_error_code", "avatar_source_kind", "avatar_style", "avatar_approved_at",
                 "avatar_expires_at", "avatar_started_at", "avatar_requested_at", "avatar_attempts",
                 "avatar_version", "avatar_url", "avatar_status"):
        op.drop_column("characters", name)
    for name in ("character_reference_version", "character_reference_url", "photo_derived"):
        op.drop_column("jobs", name)
