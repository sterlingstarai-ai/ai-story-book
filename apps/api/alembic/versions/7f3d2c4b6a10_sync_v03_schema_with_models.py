"""sync_v03_schema_with_models

Revision ID: 7f3d2c4b6a10
Revises: 2dd3344558db
Create Date: 2026-02-18

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "7f3d2c4b6a10"
down_revision: Union[str, None] = "2dd3344558db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(
        uc["name"] == constraint_name for uc in inspector.get_unique_constraints(table_name)
    )


def _foreign_key_exists(
    table_name: str,
    constrained_columns: list[str],
    referred_table: str,
) -> bool:
    inspector = inspect(op.get_bind())
    constrained_columns = list(constrained_columns)
    for fk in inspector.get_foreign_keys(table_name):
        if (
            fk.get("referred_table") == referred_table
            and fk.get("constrained_columns") == constrained_columns
        ):
            return True
    return False


def _foreign_key_named_exists(table_name: str, fk_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    # series table (v0.3)
    if not _table_exists("series"):
        op.create_table(
            "series",
            sa.Column("id", sa.String(length=60), nullable=False),
            sa.Column("title", sa.String(length=100), nullable=False),
            sa.Column("language", sa.String(length=10), nullable=False),
            sa.Column("target_age", sa.String(length=10), nullable=False),
            sa.Column("style", sa.String(length=30), nullable=False),
            sa.Column("theme", sa.String(length=20), nullable=True),
            sa.Column("character_id", sa.String(length=60), nullable=True),
            sa.Column("series_bible", sa.JSON(), nullable=True),
            sa.Column("user_key", sa.String(length=80), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("series", "ix_series_user_key"):
        op.create_index("ix_series_user_key", "series", ["user_key"], unique=False)

    # jobs drift
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        if not _column_exists("jobs", "retry_count"):
            batch_op.add_column(sa.Column("retry_count", sa.Integer(), nullable=True))
        if not _column_exists("jobs", "last_retry_at"):
            batch_op.add_column(sa.Column("last_retry_at", sa.DateTime(), nullable=True))
    if not _index_exists("jobs", "ix_jobs_status_created"):
        op.create_index(
            "ix_jobs_status_created", "jobs", ["status", "created_at"], unique=False
        )

    # books drift
    with op.batch_alter_table("books", schema=None) as batch_op:
        if not _column_exists("books", "character_ids"):
            batch_op.add_column(sa.Column("character_ids", sa.JSON(), nullable=True))
        if not _column_exists("books", "series_id"):
            batch_op.add_column(sa.Column("series_id", sa.String(length=60), nullable=True))
        if not _column_exists("books", "series_index"):
            batch_op.add_column(sa.Column("series_index", sa.Integer(), nullable=True))
        if not _column_exists("books", "title_ko"):
            batch_op.add_column(sa.Column("title_ko", sa.String(length=100), nullable=True))
        if not _column_exists("books", "title_en"):
            batch_op.add_column(sa.Column("title_en", sa.String(length=100), nullable=True))
        if not _column_exists("books", "learning_assets"):
            batch_op.add_column(sa.Column("learning_assets", sa.JSON(), nullable=True))
    if _column_exists("books", "series_id") and not (
        _foreign_key_named_exists("books", "fk_books_series_id_series")
        or _foreign_key_exists("books", ["series_id"], "series")
    ):
        with op.batch_alter_table("books", schema=None) as batch_op:
            batch_op.create_foreign_key(
                "fk_books_series_id_series",
                "series",
                ["series_id"],
                ["id"],
            )
    if not _index_exists("books", "ix_books_user_created"):
        op.create_index(
            "ix_books_user_created", "books", ["user_key", "created_at"], unique=False
        )

    # pages drift
    with op.batch_alter_table("pages", schema=None) as batch_op:
        if not _column_exists("pages", "text_ko"):
            batch_op.add_column(sa.Column("text_ko", sa.Text(), nullable=True))
        if not _column_exists("pages", "text_en"):
            batch_op.add_column(sa.Column("text_en", sa.Text(), nullable=True))
        if not _column_exists("pages", "audio_url_ko"):
            batch_op.add_column(sa.Column("audio_url_ko", sa.String(length=500), nullable=True))
        if not _column_exists("pages", "audio_url_en"):
            batch_op.add_column(sa.Column("audio_url_en", sa.String(length=500), nullable=True))
        if not _column_exists("pages", "vocab"):
            batch_op.add_column(sa.Column("vocab", sa.JSON(), nullable=True))
        if not _column_exists("pages", "comprehension"):
            batch_op.add_column(sa.Column("comprehension", sa.JSON(), nullable=True))
        if not _column_exists("pages", "quiz"):
            batch_op.add_column(sa.Column("quiz", sa.JSON(), nullable=True))
    if not _index_exists("pages", "ix_pages_book_id"):
        op.create_index("ix_pages_book_id", "pages", ["book_id"], unique=False)
    if not _unique_constraint_exists("pages", "uq_page_book_number"):
        with op.batch_alter_table("pages", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_page_book_number", ["book_id", "page_number"]
            )

    # reading_logs composite index drift
    if not _index_exists("reading_logs", "ix_reading_logs_user_date"):
        op.create_index(
            "ix_reading_logs_user_date",
            "reading_logs",
            ["user_key", "read_date"],
            unique=False,
        )


def downgrade() -> None:
    if _index_exists("reading_logs", "ix_reading_logs_user_date"):
        op.drop_index("ix_reading_logs_user_date", table_name="reading_logs")

    if _unique_constraint_exists("pages", "uq_page_book_number"):
        with op.batch_alter_table("pages", schema=None) as batch_op:
            batch_op.drop_constraint("uq_page_book_number", type_="unique")
    if _index_exists("pages", "ix_pages_book_id"):
        op.drop_index("ix_pages_book_id", table_name="pages")
    with op.batch_alter_table("pages", schema=None) as batch_op:
        if _column_exists("pages", "quiz"):
            batch_op.drop_column("quiz")
        if _column_exists("pages", "comprehension"):
            batch_op.drop_column("comprehension")
        if _column_exists("pages", "vocab"):
            batch_op.drop_column("vocab")
        if _column_exists("pages", "audio_url_en"):
            batch_op.drop_column("audio_url_en")
        if _column_exists("pages", "audio_url_ko"):
            batch_op.drop_column("audio_url_ko")
        if _column_exists("pages", "text_en"):
            batch_op.drop_column("text_en")
        if _column_exists("pages", "text_ko"):
            batch_op.drop_column("text_ko")

    if _index_exists("books", "ix_books_user_created"):
        op.drop_index("ix_books_user_created", table_name="books")
    if _foreign_key_named_exists("books", "fk_books_series_id_series"):
        with op.batch_alter_table("books", schema=None) as batch_op:
            batch_op.drop_constraint("fk_books_series_id_series", type_="foreignkey")
    with op.batch_alter_table("books", schema=None) as batch_op:
        if _column_exists("books", "learning_assets"):
            batch_op.drop_column("learning_assets")
        if _column_exists("books", "title_en"):
            batch_op.drop_column("title_en")
        if _column_exists("books", "title_ko"):
            batch_op.drop_column("title_ko")
        if _column_exists("books", "series_index"):
            batch_op.drop_column("series_index")
        if _column_exists("books", "series_id"):
            batch_op.drop_column("series_id")
        if _column_exists("books", "character_ids"):
            batch_op.drop_column("character_ids")

    if _index_exists("jobs", "ix_jobs_status_created"):
        op.drop_index("ix_jobs_status_created", table_name="jobs")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        if _column_exists("jobs", "last_retry_at"):
            batch_op.drop_column("last_retry_at")
        if _column_exists("jobs", "retry_count"):
            batch_op.drop_column("retry_count")

    if _index_exists("series", "ix_series_user_key"):
        op.drop_index("ix_series_user_key", table_name="series")
    if _table_exists("series"):
        op.drop_table("series")
