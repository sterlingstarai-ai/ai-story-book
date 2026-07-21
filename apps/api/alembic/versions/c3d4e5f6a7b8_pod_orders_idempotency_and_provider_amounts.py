"""pod_orders 멱등키 + provider 금액 분리 컬럼 (H6 + H13)

- idempotency_key + (user_key, idempotency_key) 부분 유니크(H6): 더블탭 이중주문 차단.
- provider_total / provider_currency(H13/G7): Printful 실비를 원통화·정수 cents로 별도 저장
  (기존 total_price/currency는 지역 견적=사용자 표시·청구 기준으로 유지, ×1300 환산 제거).
가법적(nullable) — 기존 행 백필 불필요.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "pod_orders"
INDEX = "uq_pod_orders_user_idempotency"


def _has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))


def _has_index(table: str, index: str) -> bool:
    return any(ix["name"] == index for ix in inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    if not _has_column(TABLE, "idempotency_key"):
        op.add_column(TABLE, sa.Column("idempotency_key", sa.String(length=80), nullable=True))
    if not _has_column(TABLE, "provider_total"):
        op.add_column(TABLE, sa.Column("provider_total", sa.Integer(), nullable=True))
    if not _has_column(TABLE, "provider_currency"):
        op.add_column(TABLE, sa.Column("provider_currency", sa.String(length=10), nullable=True))

    if not _has_index(TABLE, INDEX):
        dialect = op.get_bind().dialect.name
        where = text("idempotency_key IS NOT NULL")
        if dialect == "postgresql":
            op.create_index(INDEX, TABLE, ["user_key", "idempotency_key"], unique=True, postgresql_where=where)
        elif dialect == "sqlite":
            op.create_index(INDEX, TABLE, ["user_key", "idempotency_key"], unique=True, sqlite_where=where)
        else:
            op.create_index(INDEX, TABLE, ["user_key", "idempotency_key"], unique=True)


def downgrade() -> None:
    if _has_index(TABLE, INDEX):
        op.drop_index(INDEX, table_name=TABLE)
    for col in ("provider_currency", "provider_total", "idempotency_key"):
        if _has_column(TABLE, col):
            op.drop_column(TABLE, col)
