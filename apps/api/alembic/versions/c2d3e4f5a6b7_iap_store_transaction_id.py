"""add store_transaction_id to iap_receipts (replay-proof dedupe key)

리플레이 방지 키를 클라이언트 transaction_id에서 스토어 검증 식별자로 이전한다.

Revision ID: c2d3e4f5a6b7
Revises: b7c8d9e0f1a2
Create Date: 2026-06-28

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("iap_receipts") as batch:
        batch.add_column(
            sa.Column("store_transaction_id", sa.String(length=200), nullable=True)
        )
        batch.create_unique_constraint(
            "uq_iap_receipts_platform_store_transaction_id",
            ["platform", "store_transaction_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("iap_receipts") as batch:
        batch.drop_constraint(
            "uq_iap_receipts_platform_store_transaction_id", type_="unique"
        )
        batch.drop_column("store_transaction_id")
