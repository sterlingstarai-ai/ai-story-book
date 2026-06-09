"""add_profile_scope_columns

Revision ID: b8a6c1d2e3f4
Revises: 91b6f0c4f2a1
Create Date: 2026-03-15

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b8a6c1d2e3f4"
down_revision: Union[str, None] = "91b6f0c4f2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        if not _column_exists("jobs", "profile_id"):
            batch_op.add_column(sa.Column("profile_id", sa.String(length=60), nullable=True))
    if not _index_exists("jobs", "ix_jobs_profile_id"):
        op.create_index("ix_jobs_profile_id", "jobs", ["profile_id"], unique=False)
    if not _index_exists("jobs", "ix_jobs_user_profile_created"):
        op.create_index(
            "ix_jobs_user_profile_created",
            "jobs",
            ["user_key", "profile_id", "created_at"],
            unique=False,
        )

    with op.batch_alter_table("books", schema=None) as batch_op:
        if not _column_exists("books", "profile_id"):
            batch_op.add_column(sa.Column("profile_id", sa.String(length=60), nullable=True))
    if not _index_exists("books", "ix_books_profile_id"):
        op.create_index("ix_books_profile_id", "books", ["profile_id"], unique=False)
    if not _index_exists("books", "ix_books_user_profile_created"):
        op.create_index(
            "ix_books_user_profile_created",
            "books",
            ["user_key", "profile_id", "created_at"],
            unique=False,
        )

    with op.batch_alter_table("reading_logs", schema=None) as batch_op:
        if not _column_exists("reading_logs", "profile_id"):
            batch_op.add_column(
                sa.Column("profile_id", sa.String(length=60), nullable=True)
            )
    if not _index_exists("reading_logs", "ix_reading_logs_profile_id"):
        op.create_index(
            "ix_reading_logs_profile_id",
            "reading_logs",
            ["profile_id"],
            unique=False,
        )
    if not _index_exists("reading_logs", "ix_reading_logs_user_profile_date"):
        op.create_index(
            "ix_reading_logs_user_profile_date",
            "reading_logs",
            ["user_key", "profile_id", "read_date"],
            unique=False,
        )


def downgrade() -> None:
    if _index_exists("reading_logs", "ix_reading_logs_user_profile_date"):
        op.drop_index("ix_reading_logs_user_profile_date", table_name="reading_logs")
    if _index_exists("reading_logs", "ix_reading_logs_profile_id"):
        op.drop_index("ix_reading_logs_profile_id", table_name="reading_logs")
    with op.batch_alter_table("reading_logs", schema=None) as batch_op:
        if _column_exists("reading_logs", "profile_id"):
            batch_op.drop_column("profile_id")

    if _index_exists("books", "ix_books_user_profile_created"):
        op.drop_index("ix_books_user_profile_created", table_name="books")
    if _index_exists("books", "ix_books_profile_id"):
        op.drop_index("ix_books_profile_id", table_name="books")
    with op.batch_alter_table("books", schema=None) as batch_op:
        if _column_exists("books", "profile_id"):
            batch_op.drop_column("profile_id")

    if _index_exists("jobs", "ix_jobs_user_profile_created"):
        op.drop_index("ix_jobs_user_profile_created", table_name="jobs")
    if _index_exists("jobs", "ix_jobs_profile_id"):
        op.drop_index("ix_jobs_profile_id", table_name="jobs")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        if _column_exists("jobs", "profile_id"):
            batch_op.drop_column("profile_id")
