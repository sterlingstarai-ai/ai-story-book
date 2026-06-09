"""add_character_source_image

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-08

얼굴 보존 이미지 생성(gemini)의 레퍼런스로 쓸 원본 사진 URL 컬럼 추가.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _column_exists("characters", "source_image_url"):
        with op.batch_alter_table("characters", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("source_image_url", sa.String(length=500), nullable=True)
            )


def downgrade() -> None:
    if _column_exists("characters", "source_image_url"):
        with op.batch_alter_table("characters", schema=None) as batch_op:
            batch_op.drop_column("source_image_url")
