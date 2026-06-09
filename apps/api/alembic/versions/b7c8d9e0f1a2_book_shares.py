"""book_shares 테이블 추가 — 부모가 만든 책 공개 공유 링크(만료·철회 가능)

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-06-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("book_shares"):
        return
    op.create_table(
        "book_shares",
        sa.Column("id", sa.String(length=60), primary_key=True),
        sa.Column("book_id", sa.String(length=60), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_book_shares_book", "book_shares", ["book_id"])
    op.create_index("ix_book_shares_user_key", "book_shares", ["user_key"])


def downgrade() -> None:
    if _table_exists("book_shares"):
        op.drop_table("book_shares")
