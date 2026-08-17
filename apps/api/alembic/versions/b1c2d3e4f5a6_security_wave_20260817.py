"""보안 감사 2026-08-17 반송분 — 스키마 확장(expand-only)

세 가지 additive 변경만 담는다(contract 없음 — 롤백 안전):
1. `storage_purge_tasks`  : 아동 PII 파기 지시의 durable outbox (M8/R1-5).
   행 삭제 후 S3 파기가 중단되면 키를 되찾을 수 없어 영구 고아가 된다. 파기 의도를
   삭제와 같은 커밋에 남겨 스윕이 멱등 재실행할 수 있게 한다.
2. `jobs.image_keys`      : 생성 잡이 영속화한 이미지 키 (M12/R3-5).
   잡 실패 시 책 행이 없어 image_url 역산이 불가능 → 아동 얼굴 파생 일러스트가 고아.
3. `uq_credit_transactions_clawback` : clawback 부분 유니크 (M2/R2-2).
   refund/purchase에는 있으나 clawback에만 없어, 동시 중복 환불 웹훅이 크레딧을 이중
   회수한다. 인덱스 생성 전 기존 중복을 최소 id만 남기고 정리한다.

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURGE_TABLE = "storage_purge_tasks"
PURGE_STATUS_INDEX = "ix_storage_purge_tasks_status"
PURGE_USER_INDEX = "ix_storage_purge_tasks_user_key"
CLAWBACK_INDEX = "uq_credit_transactions_clawback"


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table_name))


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1) storage_purge_tasks ────────────────────────────────────────────────
    if not _table_exists(PURGE_TABLE):
        op.create_table(
            PURGE_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_key", sa.String(length=80), nullable=True),
            sa.Column("reason", sa.String(length=40), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("target", sa.Text(), nullable=False),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="pending"
            ),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.String(length=300), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    if not _index_exists(PURGE_TABLE, PURGE_STATUS_INDEX):
        op.create_index(PURGE_STATUS_INDEX, PURGE_TABLE, ["status", "id"])
    if not _index_exists(PURGE_TABLE, PURGE_USER_INDEX):
        op.create_index(PURGE_USER_INDEX, PURGE_TABLE, ["user_key"])

    # ── 2) jobs.image_keys ────────────────────────────────────────────────────
    if not _column_exists("jobs", "image_keys"):
        op.add_column("jobs", sa.Column("image_keys", sa.JSON(), nullable=True))

    # ── 3) clawback 부분 유니크 ────────────────────────────────────────────────
    # 인덱스 생성 전 기존 중복(같은 user_key+reference_id의 clawback 2행 이상) 정리.
    bind.execute(
        sa.text(
            """
            DELETE FROM credit_transactions
            WHERE transaction_type = 'clawback'
              AND reference_id IS NOT NULL
              AND id NOT IN (
                  SELECT keep_id FROM (
                      SELECT MIN(id) AS keep_id
                      FROM credit_transactions
                      WHERE transaction_type = 'clawback' AND reference_id IS NOT NULL
                      GROUP BY user_key, reference_id
                  ) AS keepers
              )
            """
        )
    )

    if not _index_exists("credit_transactions", CLAWBACK_INDEX):
        where = sa.text("transaction_type = 'clawback'")
        dialect = bind.dialect.name
        if dialect == "postgresql":
            op.create_index(
                CLAWBACK_INDEX,
                "credit_transactions",
                ["user_key", "reference_id"],
                unique=True,
                postgresql_where=where,
            )
        elif dialect == "sqlite":
            op.create_index(
                CLAWBACK_INDEX,
                "credit_transactions",
                ["user_key", "reference_id"],
                unique=True,
                sqlite_where=where,
            )
        else:
            op.create_index(
                CLAWBACK_INDEX,
                "credit_transactions",
                ["user_key", "reference_id"],
                unique=True,
            )


def downgrade() -> None:
    if _index_exists("credit_transactions", CLAWBACK_INDEX):
        op.drop_index(CLAWBACK_INDEX, table_name="credit_transactions")
    if _column_exists("jobs", "image_keys"):
        op.drop_column("jobs", "image_keys")
    if _table_exists(PURGE_TABLE):
        for index_name in (PURGE_USER_INDEX, PURGE_STATUS_INDEX):
            if _index_exists(PURGE_TABLE, index_name):
                op.drop_index(index_name, table_name=PURGE_TABLE)
        op.drop_table(PURGE_TABLE)
