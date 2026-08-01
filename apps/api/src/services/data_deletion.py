"""책 삭제 시 FK로 묶인 자식 행을 일괄 정리한다.

Postgres(운영)는 FK를 강제하므로, 자식 행을 남긴 채 Book을 지우면 삭제 트랜잭션이
IntegrityError로 abort된다(→ 책 삭제 실패, 계정 삭제 시 GDPR 우완전 erasure 불가).
SQLite 테스트는 PRAGMA foreign_keys=ON 이 없으면 같은 누락을 조용히 통과시켜 버그를
가린다. 이 헬퍼로 모든 책-자식 테이블을 한곳에서 정리해 두 삭제 경로(단건/계정)가
같은 정합성을 보장하게 한다.
"""

from sqlalchemy import delete, select, update
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


async def collect_book_image_keys(db: AsyncSession, book_ids: list[str]) -> list[str]:
    """책 표지·페이지 이미지의 S3 키를 image_url에서 역산해 반환한다(N1).

    파이프라인이 이미지를 추적 불가 prefix(images/{provider}/{uuid})에 저장해도, 저장된
    공개 URL에서 실제 키를 복원하면 prefix와 무관하게 파기 대상에 포함할 수 있다.
    **행 삭제 전에 호출해야 한다**(purge 후엔 URL이 사라진다). 중복 제거.
    """
    if not book_ids:
        return []
    from src.services.storage import key_from_public_url

    urls: list[str] = []
    cover_rows = await db.execute(
        select(Book.cover_image_url).where(Book.id.in_(book_ids))
    )
    urls.extend(u for (u,) in cover_rows.all() if u)
    page_rows = await db.execute(
        select(Page.image_url).where(Page.book_id.in_(book_ids))
    )
    urls.extend(u for (u,) in page_rows.all() if u)

    keys = [key_from_public_url(u) for u in urls]
    return list(dict.fromkeys(k for k in keys if k))  # 중복 제거 + None 제외


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
