"""user_settings.timezone 컬럼 추가 (H2/G10)

하루/월 경계(스트릭·일일/월간 한도·리포트)를 사용자별 IANA 타임존으로 판정하기 위한 컬럼.
server_default='Asia/Seoul'로 기존 행 백필(NOT NULL 안전). read_date는 이미 naive UTC라
데이터 마이그레이션 불필요.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "user_settings"
COLUMN = "timezone"


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if not _has_column(TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.String(length=40),
                nullable=False,
                server_default="Asia/Seoul",
            ),
        )


def downgrade() -> None:
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
