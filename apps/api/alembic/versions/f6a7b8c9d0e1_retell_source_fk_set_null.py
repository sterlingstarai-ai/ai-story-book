"""books.retelling_source_book_id self-FK (ON DELETE SET NULL) + 고아 정리 (M10)

모델은 retelling_source_book_id에 ForeignKey('books.id')를 선언하지만 실 Postgres에는
제약이 없다(c9d0e1f2a3b4가 컬럼만 add). 리텔 후 원본을 삭제하면 변형본이 존재하지 않는
book id를 가리키는 고아 포인터로 잔존하고, 이후 FK를 붙이는 순간 (a) 고아 행 때문에 생성
실패, (b) 원본 삭제가 FK 위반으로 실패하기 시작한다. 유니크/FK 생성 전 고아를 NULL로
정리한 뒤 ON DELETE SET NULL FK를 만든다(SQLite는 create_all이 모델 기준 FK를 이미 가짐).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9da
Create Date: 2026-07-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_books_retelling_source_book_id_books"


def _fk_named_exists(table: str, name: str) -> bool:
    return any(
        fk.get("name") == name for fk in inspect(op.get_bind()).get_foreign_keys(table)
    )


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 고아 포인터 선행 정리(존재하지 않는 원본을 가리키는 링크 → NULL). FK 생성 전 필수.
    bind.execute(
        sa.text(
            """
            UPDATE books SET retelling_source_book_id = NULL
            WHERE retelling_source_book_id IS NOT NULL
              AND retelling_source_book_id NOT IN (SELECT id FROM books)
            """
        )
    )

    # 2) ON DELETE SET NULL self-FK 생성. Postgres만(SQLite는 모델 create_all이 FK 보유,
    #    ALTER ADD CONSTRAINT 미지원). 멱등: 이미 있으면 스킵.
    if bind.dialect.name == "postgresql" and not _fk_named_exists("books", FK_NAME):
        op.create_foreign_key(
            FK_NAME,
            "books",
            "books",
            ["retelling_source_book_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and _fk_named_exists("books", FK_NAME):
        op.drop_constraint(FK_NAME, "books", type_="foreignkey")
