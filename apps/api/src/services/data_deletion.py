"""책 삭제 시 FK로 묶인 자식 행을 일괄 정리한다.

Postgres(운영)는 FK를 강제하므로, 자식 행을 남긴 채 Book을 지우면 삭제 트랜잭션이
IntegrityError로 abort된다(→ 책 삭제 실패, 계정 삭제 시 GDPR 우완전 erasure 불가).
SQLite 테스트는 PRAGMA foreign_keys=ON 이 없으면 같은 누락을 조용히 통과시켜 버그를
가린다. 이 헬퍼로 모든 책-자식 테이블을 한곳에서 정리해 두 삭제 경로(단건/계정)가
같은 정합성을 보장하게 한다.
"""

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    Book,
    BookShare,
    BranchStoryEdge,
    BranchStoryNode,
    DailyStory,
    Page,
    PodOrder,
    PronunciationLog,
    QuizAnswer,
    ReadingLog,
)


async def purge_book_children(db: AsyncSession, book_ids: list[str]) -> None:
    """주어진 book_ids를 참조하는 모든 자식 행을 삭제(또는 참조 해제)한다.

    호출부는 이 함수 호출 '후'에 Book 행을 삭제한다. 커밋은 호출부 책임(같은 트랜잭션).
    """
    if not book_ids:
        return

    # 하드 FK(NOT NULL) 자식 — 책 삭제 전 반드시 제거해야 FK 위반이 없다.
    await db.execute(delete(BranchStoryEdge).where(BranchStoryEdge.book_id.in_(book_ids)))
    await db.execute(delete(BranchStoryNode).where(BranchStoryNode.book_id.in_(book_ids)))
    await db.execute(delete(Page).where(Page.book_id.in_(book_ids)))
    await db.execute(delete(BookShare).where(BookShare.book_id.in_(book_ids)))
    await db.execute(delete(QuizAnswer).where(QuizAnswer.book_id.in_(book_ids)))
    await db.execute(delete(ReadingLog).where(ReadingLog.book_id.in_(book_ids)))
    await db.execute(delete(PronunciationLog).where(PronunciationLog.book_id.in_(book_ids)))
    await db.execute(delete(PodOrder).where(PodOrder.book_id.in_(book_ids)))

    # 소프트 FK(nullable) — '오늘의 동화' 메타는 보존하되 책 참조만 해제.
    await db.execute(
        update(DailyStory).where(DailyStory.book_id.in_(book_ids)).values(book_id=None)
    )
    # M10: 연령 리텔 변형본의 원본 링크(self-FK) 해제 — 원본 삭제 시 고아 포인터·FK 위반 방지.
    await db.execute(
        update(Book)
        .where(Book.retelling_source_book_id.in_(book_ids))
        .values(retelling_source_book_id=None)
    )
