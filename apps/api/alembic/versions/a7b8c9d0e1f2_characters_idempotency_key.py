"""characters 멱등키 + (user_key, idempotency_key) 부분 유니크 (H17/G19 #9)

사진·그림 기반 캐릭터 생성은 요청 안에서 vision 분석 + 시트 이미지를 동기로 수행해
최대 수분이 걸린다. 클라이언트가 타임아웃돼도 서버는 완주하므로 재시도가 중복 캐릭터를
만든다(서재 오염 + vision·이미지 비용 이중 지출). Job/PodOrder와 동일한 멱등 인프라를
캐릭터에도 부여한다.

가법적(nullable) — 기존 행 백필 불필요. 부분 유니크라 키가 NULL인 기존 캐릭터는
제약 대상이 아니므로 다건 공존이 그대로 허용된다.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "characters"
COLUMN = "idempotency_key"
INDEX = "uq_characters_user_idempotency"


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))


def _has_index(table: str, index: str) -> bool:
    return any(ix["name"] == index for ix in inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    if not _has_column(TABLE, COLUMN):
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(length=80), nullable=True))

    if not _has_index(TABLE, INDEX):
        dialect = op.get_bind().dialect.name
        where = text("idempotency_key IS NOT NULL")
        if dialect == "postgresql":
            op.create_index(
                INDEX,
                TABLE,
                ["user_key", COLUMN],
                unique=True,
                postgresql_where=where,
            )
        elif dialect == "sqlite":
            op.create_index(
                INDEX,
                TABLE,
                ["user_key", COLUMN],
                unique=True,
                sqlite_where=where,
            )
        else:
            op.create_index(INDEX, TABLE, ["user_key", COLUMN], unique=True)


def downgrade() -> None:
    if _has_index(TABLE, INDEX):
        op.drop_index(INDEX, table_name=TABLE)
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
