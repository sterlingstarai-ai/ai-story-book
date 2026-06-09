"""jobs (user_key, idempotency_key) 부분 유니크 인덱스 추가

동일 멱등키로 동시 중복 잡 생성을 DB 레벨에서 차단(크레딧 이중차감 방지).
idempotency_key가 NULL인 잡은 제약 대상이 아니다(부분 인덱스).

Revision ID: a6b7c8d9e0f1
Revises: f4a5b6c7d8e9
Create Date: 2026-06-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_jobs_user_idempotency"


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = inspect(op.get_bind())
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    if _index_exists("jobs", INDEX_NAME):
        return
    dialect = op.get_bind().dialect.name
    where = sa.text("idempotency_key IS NOT NULL")
    if dialect == "postgresql":
        op.create_index(
            INDEX_NAME,
            "jobs",
            ["user_key", "idempotency_key"],
            unique=True,
            postgresql_where=where,
        )
    elif dialect == "sqlite":
        op.create_index(
            INDEX_NAME,
            "jobs",
            ["user_key", "idempotency_key"],
            unique=True,
            sqlite_where=where,
        )
    else:
        op.create_index(
            INDEX_NAME, "jobs", ["user_key", "idempotency_key"], unique=True
        )


def downgrade() -> None:
    if _index_exists("jobs", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="jobs")
