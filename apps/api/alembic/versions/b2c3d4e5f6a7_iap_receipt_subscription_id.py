"""iap_receipts.subscription_id 컬럼 추가 (H5)

웹훅이 '최신 구독' 임의 매칭 대신 이 영수증이 개설한 구독만 갱신하도록 연결한다.
가법적(nullable) — 기존 행 백필 불필요.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "iap_receipts"
COLUMN = "subscription_id"
INDEX = "ix_iap_receipts_subscription_id"
FK = "fk_iap_receipts_subscription_id"


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))


def _has_index(table: str, index: str) -> bool:
    return any(ix["name"] == index for ix in inspect(op.get_bind()).get_indexes(table))


def _has_fk(table: str, name: str) -> bool:
    return any(fk.get("name") == name for fk in inspect(op.get_bind()).get_foreign_keys(table))


def upgrade() -> None:
    if not _has_column(TABLE, COLUMN):
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    if not _has_index(TABLE, INDEX):
        op.create_index(INDEX, TABLE, [COLUMN])
    # 참조 무결성: PG는 ALTER ADD CONSTRAINT로 FK 생성. SQLite는 ADD CONSTRAINT 미지원이나
    # 테스트 스키마는 create_all로 FK 포함 생성되므로 미생성이어도 모델과 정합.
    if op.get_bind().dialect.name == "postgresql" and not _has_fk(TABLE, FK):
        op.create_foreign_key(FK, TABLE, "subscriptions", [COLUMN], ["id"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql" and _has_fk(TABLE, FK):
        op.drop_constraint(FK, TABLE, type_="foreignkey")
    if _has_index(TABLE, INDEX):
        op.drop_index(INDEX, table_name=TABLE)
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
