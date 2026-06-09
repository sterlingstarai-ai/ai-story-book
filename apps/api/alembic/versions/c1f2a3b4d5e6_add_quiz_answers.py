"""add_quiz_answers

Revision ID: c1f2a3b4d5e6
Revises: b8a6c1d2e3f4
Create Date: 2026-06-08

학습 성장 측정을 위한 quiz_answers 테이블 추가.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "c1f2a3b4d5e6"
down_revision: Union[str, None] = "b8a6c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("quiz_answers"):
        return
    op.create_table(
        "quiz_answers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_key", sa.String(length=80), nullable=False),
        sa.Column("profile_id", sa.String(length=60), nullable=True),
        sa.Column("book_id", sa.String(length=60), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("quiz_type", sa.String(length=20), nullable=False),
        sa.Column("question_index", sa.Integer(), nullable=True),
        sa.Column("term", sa.String(length=120), nullable=True),
        sa.Column("user_answer", sa.Text(), nullable=True),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quiz_answers_profile_id", "quiz_answers", ["profile_id"], unique=False
    )
    op.create_index(
        "ix_quiz_answers_user_created",
        "quiz_answers",
        ["user_key", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_quiz_answers_user_book",
        "quiz_answers",
        ["user_key", "book_id"],
        unique=False,
    )


def downgrade() -> None:
    if not _table_exists("quiz_answers"):
        return
    op.drop_index("ix_quiz_answers_user_book", table_name="quiz_answers")
    op.drop_index("ix_quiz_answers_user_created", table_name="quiz_answers")
    op.drop_index("ix_quiz_answers_profile_id", table_name="quiz_answers")
    op.drop_table("quiz_answers")
