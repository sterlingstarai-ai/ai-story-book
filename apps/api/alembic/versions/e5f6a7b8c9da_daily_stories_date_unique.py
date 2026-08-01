"""daily_stories.date UNIQUE 제약 + 기존 중복 정리 (H14)

check-then-insert 레이스로 하루 2행 이상 생기면 /streak/today가 MultipleResultsFound로
전 사용자 500이 된다. 유니크 생성 전 기존 중복(같은 date)을 최소 id만 남기고 삭제한다
(아니면 유니크 생성 실패). 기존 ix_daily_stories_date(plain index)는 유니크가 겸하므로 제거.

Revision ID: e5f6a7b8c9da
Revises: d4e5f6a7b8c9
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9da"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "daily_stories"
UNIQUE = "uq_daily_stories_date"
OLD_INDEX = "ix_daily_stories_date"


def _index_exists(name: str) -> bool:
    return any(ix["name"] == name for ix in inspect(op.get_bind()).get_indexes(TABLE))


def upgrade() -> None:
    bind = op.get_bind()
    # 1) 기존 중복 정리(최소 id만 유지) — 유니크 생성 전 필수.
    bind.execute(
        sa.text(
            """
            DELETE FROM daily_stories
            WHERE id NOT IN (SELECT keep FROM (
                SELECT MIN(id) AS keep FROM daily_stories GROUP BY date
            ) AS keepers)
            """
        )
    )
    # 2) 중복 plain index 제거(있으면). DROP INDEX는 SQLite에서도 안전.
    if _index_exists(OLD_INDEX):
        op.drop_index(OLD_INDEX, table_name=TABLE)
    # 3) 유니크 제약 생성. SQLite는 ALTER ADD CONSTRAINT 미지원이므로 batch(copy-move)로.
    if not _index_exists(UNIQUE):
        with op.batch_alter_table(TABLE) as batch:
            batch.create_unique_constraint(UNIQUE, ["date"])


def downgrade() -> None:
    if _index_exists(UNIQUE):
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(UNIQUE, type_="unique")
    if not _index_exists(OLD_INDEX):
        op.create_index(OLD_INDEX, TABLE, ["date"])
