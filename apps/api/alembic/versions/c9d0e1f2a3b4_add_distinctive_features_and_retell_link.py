"""add_distinctive_features_and_retell_link

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-06-22

- characters.distinctive_features (JSON, nullable) — 캐릭터 고유 특징(안경/주근깨 등) 영속.
  같은 캐릭터를 날짜·책을 넘어 동일하게 그리기 위함(시리즈 교차 일관성).
- books.retelling_source_book_id (String(60), nullable) — 연령 리텔(grow-with-child)
  원본 책 링크. 같은 이야기의 다른 연령 변형을 묶는다.
둘 다 nullable이라 기존 행 무영향(additive).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(
        col["name"] == column_name for col in inspector.get_columns(table_name)
    )


def upgrade() -> None:
    with op.batch_alter_table("characters", schema=None) as batch_op:
        if not _column_exists("characters", "distinctive_features"):
            batch_op.add_column(
                sa.Column("distinctive_features", sa.JSON(), nullable=True)
            )
    with op.batch_alter_table("books", schema=None) as batch_op:
        if not _column_exists("books", "retelling_source_book_id"):
            batch_op.add_column(
                sa.Column(
                    "retelling_source_book_id",
                    sa.String(length=60),
                    nullable=True,
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("books", schema=None) as batch_op:
        if _column_exists("books", "retelling_source_book_id"):
            batch_op.drop_column("retelling_source_book_id")
    with op.batch_alter_table("characters", schema=None) as batch_op:
        if _column_exists("characters", "distinctive_features"):
            batch_op.drop_column("distinctive_features")
