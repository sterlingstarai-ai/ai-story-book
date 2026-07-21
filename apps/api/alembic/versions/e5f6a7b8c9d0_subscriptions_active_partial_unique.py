"""subscriptions (user_key) WHERE status='active' 부분 유니크 + 기존 다중 active dedup (M17)

사용자당 active 구독은 최대 1행이어야 한다. check-then-write 사이 DB 제약 부재로
동시 verify/restore가 active 2행을 만들면 periodic_credits가 영구 이중 지급한다.
부분 유니크 인덱스 생성 전, 기존 사용자별 다중 active를 최신 1행만 남기고 정리한다
(아니면 인덱스 생성 자체가 실패).

Revision ID: e5f6a7b8c9d0
Revises: d0e1f2a3b4c5
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_subscriptions_active_per_user"


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 기존 사용자별 다중 active 정리: 최신(max id = 최신 created) 1행만 active 유지,
    #    나머지는 cancelled. (부분 유니크 생성 전 필수 — 아니면 생성 실패)
    bind.execute(
        sa.text(
            """
            UPDATE subscriptions
            SET status = 'cancelled'
            WHERE status = 'active'
              AND id NOT IN (
                  SELECT keep_id FROM (
                      SELECT MAX(id) AS keep_id
                      FROM subscriptions
                      WHERE status = 'active'
                      GROUP BY user_key
                  ) AS keepers
              )
            """
        )
    )

    # 2) 부분 유니크 인덱스 생성 (active만 대상).
    if _index_exists("subscriptions", INDEX_NAME):
        return
    dialect = bind.dialect.name
    where = sa.text("status = 'active'")
    if dialect == "postgresql":
        op.create_index(
            INDEX_NAME,
            "subscriptions",
            ["user_key"],
            unique=True,
            postgresql_where=where,
        )
    elif dialect == "sqlite":
        op.create_index(
            INDEX_NAME,
            "subscriptions",
            ["user_key"],
            unique=True,
            sqlite_where=where,
        )
    else:
        op.create_index(INDEX_NAME, "subscriptions", ["user_key"], unique=True)


def downgrade() -> None:
    if _index_exists("subscriptions", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="subscriptions")
