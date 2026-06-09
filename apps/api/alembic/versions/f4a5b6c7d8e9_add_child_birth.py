"""add_child_birth

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-09

자녀 프로필에 생년월(birth_year/birth_month) 추가 — age_band를 부모 임의선택이 아니라
실제 나이에서 파생하기 위함(5/7세 경계중복 해소). nullable이라 기존 행 무영향.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    with op.batch_alter_table("child_profiles", schema=None) as batch_op:
        if not _column_exists("child_profiles", "birth_year"):
            batch_op.add_column(sa.Column("birth_year", sa.Integer(), nullable=True))
        if not _column_exists("child_profiles", "birth_month"):
            batch_op.add_column(sa.Column("birth_month", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("child_profiles", schema=None) as batch_op:
        if _column_exists("child_profiles", "birth_month"):
            batch_op.drop_column("birth_month")
        if _column_exists("child_profiles", "birth_year"):
            batch_op.drop_column("birth_year")
