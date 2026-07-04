"""merge M0-05 heads and dedupe milestone reward credits

Revision ID: d0e1f2a3b4c5
Revises: c2d3e4f5a6b7, c9d0e1f2a3b4
Create Date: 2026-07-04

"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d0e1f2a3b4c5"
down_revision: tuple[str, str] = ("c2d3e4f5a6b7", "c9d0e1f2a3b4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_credit_transactions_milestone_bonus",
        "credit_transactions",
        ["user_key", "reference_id"],
        unique=True,
        sqlite_where=sa.text(
            "transaction_type = 'bonus' AND reference_id LIKE 'milestone_%'"
        ),
        postgresql_where=sa.text(
            "transaction_type = 'bonus' AND reference_id LIKE 'milestone_%'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_credit_transactions_milestone_bonus",
        table_name="credit_transactions",
    )
