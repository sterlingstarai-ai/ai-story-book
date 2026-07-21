"""iap_webhook_events 테이블 추가 (H4)

verify 이전 선도착·store 식별자 웹훅을 유실 없이 적재하고 verify 시 sticky 재적용한다.
새 테이블 추가(가법적) — 기존 데이터 변형 없음.

Revision ID: a1b2c3d4e5f6
Revises: f6a1b2c3d4e5
Create Date: 2026-07-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f6a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "iap_webhook_events"


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("transaction_id", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "uq_iap_webhook_events_dedup",
        TABLE,
        ["platform", "transaction_id", "status"],
        unique=True,
    )
    op.create_index(
        "ix_iap_webhook_events_lookup",
        TABLE,
        ["platform", "transaction_id", "applied"],
    )


def downgrade() -> None:
    if _has_table(TABLE):
        op.drop_index("ix_iap_webhook_events_lookup", table_name=TABLE)
        op.drop_index("uq_iap_webhook_events_dedup", table_name=TABLE)
        op.drop_table(TABLE)
