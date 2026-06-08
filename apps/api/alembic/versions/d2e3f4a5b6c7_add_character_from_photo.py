"""add_character_from_photo

Revision ID: d2e3f4a5b6c7
Revises: c1f2a3b4d5e6
Create Date: 2026-06-08

아동 사진/그림 파생 캐릭터 식별용 from_photo 컬럼 추가(보호자 동의 게이트·철회 파기).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1f2a3b4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _column_exists("characters", "from_photo"):
        with op.batch_alter_table("characters", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "from_photo",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade() -> None:
    if _column_exists("characters", "from_photo"):
        with op.batch_alter_table("characters", schema=None) as batch_op:
            batch_op.drop_column("from_photo")
