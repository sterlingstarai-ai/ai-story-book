"""credit_transactions refund/purchase 멱등 부분 유니크 + reference_id 인덱스 (M16)

멀티 레플리카 동시 스캔/재전송에서의 이중 환불·N중 지급을 DB로 강제 차단한다.
부분 유니크 생성 전, 기존 중복(같은 키의 refund/purchase 2행 이상)을 최소 id만 남기고
삭제한다(아니면 인덱스 생성 실패). reference_id가 NULL인 행은 유니크 대상이 아니므로 제외.

Revision ID: f6a1b2c3d4e5
Revises: e5f6a7b8c9d0
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REFUND_INDEX = "uq_credit_transactions_refund"
PURCHASE_INDEX = "uq_credit_transactions_purchase"
REF_TYPE_INDEX = "ix_credit_transactions_reference_type"


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 기존 중복 정리(최소 id만 유지). NULL reference_id는 유니크 대상 아님 → 제외.
    bind.execute(
        sa.text(
            """
            DELETE FROM credit_transactions
            WHERE transaction_type = 'refund'
              AND reference_id IS NOT NULL
              AND id NOT IN (
                  SELECT keep_id FROM (
                      SELECT MIN(id) AS keep_id
                      FROM credit_transactions
                      WHERE transaction_type = 'refund' AND reference_id IS NOT NULL
                      GROUP BY reference_id
                  ) AS keepers
              )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM credit_transactions
            WHERE transaction_type = 'purchase'
              AND reference_id IS NOT NULL
              AND id NOT IN (
                  SELECT keep_id FROM (
                      SELECT MIN(id) AS keep_id
                      FROM credit_transactions
                      WHERE transaction_type = 'purchase' AND reference_id IS NOT NULL
                      GROUP BY user_key, reference_id
                  ) AS keepers
              )
            """
        )
    )

    dialect = bind.dialect.name

    def _create_partial(index_name: str, cols: list[str], where_sql: str) -> None:
        if _index_exists("credit_transactions", index_name):
            return
        where = sa.text(where_sql)
        if dialect == "postgresql":
            op.create_index(
                index_name, "credit_transactions", cols, unique=True,
                postgresql_where=where,
            )
        elif dialect == "sqlite":
            op.create_index(
                index_name, "credit_transactions", cols, unique=True,
                sqlite_where=where,
            )
        else:
            op.create_index(index_name, "credit_transactions", cols, unique=True)

    _create_partial(REFUND_INDEX, ["reference_id"], "transaction_type = 'refund'")
    _create_partial(
        PURCHASE_INDEX, ["user_key", "reference_id"], "transaction_type = 'purchase'"
    )
    if not _index_exists("credit_transactions", REF_TYPE_INDEX):
        op.create_index(
            REF_TYPE_INDEX, "credit_transactions", ["reference_id", "transaction_type"]
        )


def downgrade() -> None:
    for index_name in (REF_TYPE_INDEX, PURCHASE_INDEX, REFUND_INDEX):
        if _index_exists("credit_transactions", index_name):
            op.drop_index(index_name, table_name="credit_transactions")
