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
    ImagePromptsDB,
    Job,
    Page,
    PodOrder,
    PronunciationLog,
    QuizAnswer,
    ReadingLog,
    Series,
    StoryDraftDB,
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


async def collect_books_referencing_characters(
    db: AsyncSession, user_key: str, character_ids: list[str]
) -> list[str]:
    """해당 캐릭터를 참조하는 사용자 책 id 전부 (H2/R1-2).

    `Book.character_id`(스칼라 FK)만 보면 **가족 다중 캐릭터 책**(`character_ids` JSON 배열)이
    누락된다 — 그 책들의 표지·페이지에는 아동 얼굴이 렌더되어 있으므로, 동의 철회 후에도
    likeness가 영구 잔존한다. JSON 배열 비교는 방언마다 문법이 달라 이식성이 없으므로
    사용자 범위(작은 집합)를 읽어 파이썬에서 교집합을 판정한다.
    """
    if not character_ids:
        return []
    wanted = set(character_ids)

    scalar_rows = await db.execute(
        select(Book.id).where(
            Book.user_key == user_key,
            Book.character_id.in_(list(wanted)),
        )
    )
    book_ids = [bid for (bid,) in scalar_rows.all()]

    json_rows = await db.execute(
        select(Book.id, Book.character_ids).where(
            Book.user_key == user_key,
            Book.character_ids.is_not(None),
        )
    )
    for book_id, raw_ids in json_rows.all():
        if not isinstance(raw_ids, list):
            continue
        if wanted.intersection(str(cid) for cid in raw_ids if cid):
            book_ids.append(book_id)

    return list(dict.fromkeys(book_ids))


async def collect_book_job_ids(db: AsyncSession, book_ids: list[str]) -> list[str]:
    """책을 만든 잡 id를 모은다 — **책 행 삭제 전에** 호출해야 한다.

    책이 사라지면 job_id 로 가는 유일한 링크가 사라져, 파생 텍스트(아동 얼굴 묘사)가
    영원히 고아로 남는다. (이 순서 실수를 SQLite 스위트는 잡지 못했고 실 PG 게이트가 잡았다.)
    """
    if not book_ids:
        return []
    job_rows = await db.execute(select(Book.job_id).where(Book.id.in_(book_ids)))
    return list(dict.fromkeys(jid for (jid,) in job_rows.all() if jid))


async def purge_job_artifacts(db: AsyncSession, job_ids: list[str]) -> None:
    """잡과 그 파생 텍스트(스토리 초안·이미지 프롬프트)를 삭제한다 (M7/R1-4).

    story_drafts.draft / image_prompts.prompts 에는 **아동 얼굴의 텍스트 묘사와 이름**이
    그대로 들어 있다. 책·이미지만 지우고 이 행들을 남기면 철회 후에도 아동 식별정보가
    DB에 잔존한다. 책 행 삭제 **후**에 호출한다(books.job_id 가 NOT NULL FK).
    """
    if not job_ids:
        return
    await db.execute(delete(StoryDraftDB).where(StoryDraftDB.job_id.in_(job_ids)))
    await db.execute(delete(ImagePromptsDB).where(ImagePromptsDB.job_id.in_(job_ids)))
    await db.execute(delete(Job).where(Job.id.in_(job_ids)))


async def collect_job_image_keys(db: AsyncSession, book_ids: list[str]) -> list[str]:
    """책을 만든 잡이 기록해 둔 이미지 키 (M12/R3-5).

    책의 현재 image_url 역산(`collect_book_image_keys`)은 **지금 참조 중인** 이미지만 덮는다.
    생성 도중 실패·교체된 중간 산출물은 잡 레코드에만 남으므로 함께 수집해야 파기가 완전하다.
    """
    if not book_ids:
        return []
    rows = await db.execute(
        select(Job.image_keys)
        .select_from(Book)
        .join(Job, Job.id == Book.job_id)
        .where(Book.id.in_(book_ids))
    )
    keys: list[str] = []
    for (raw,) in rows.all():
        if isinstance(raw, list):
            keys.extend(str(k) for k in raw if k)
    return list(dict.fromkeys(keys))


async def detach_series_from_characters(
    db: AsyncSession, character_ids: list[str]
) -> None:
    """캐릭터 삭제 전 `series.character_id` 단방향 FK를 명시 해제한다 (H1/R1-1).

    `Series.character_id → characters.id` 는 ondelete 없는 하드 FK라 ORM이 자동 nullify하지
    못한다. 해제 없이 캐릭터를 지우면 Postgres commit이 IntegrityError → **동의 철회가
    500으로 영구 차단**된다(단건 삭제 경로 characters.py 는 이미 이걸 한다 — 두 벌 규칙 드리프트).
    SQLite 테스트는 FK-off라 이 클래스를 구조적으로 못 잡는다.
    """
    if not character_ids:
        return
    await db.execute(
        update(Series)
        .where(Series.character_id.in_(character_ids))
        .values(character_id=None)
    )


async def _keys_referenced_by_other_books(
    db: AsyncSession, book_ids: list[str]
) -> set[str]:
    """삭제 대상 **밖의** 책이 아직 참조 중인 이미지 키 (H6).

    연령 리텔은 (수정 전) 원본과 같은 S3 객체를 가리켰다. 그 상태에서 한쪽만 지우면 역산
    파기가 공유 객체를 없애 **남은 책의 표지·전 페이지가 404**가 된다. 수정 후 생성분은
    자기 사본을 갖지만, **이미 만들어진 리텔들은 여전히 공유 상태**이므로 파기 시점에도
    확인해야 한다.

    공유를 만드는 유일한 경로가 리텔(`retelling_source_book_id`)이므로 후보를 그 링크로
    한정한다 — 전 테이블 스캔을 피하면서 실제 공유분은 전부 덮는다.
    """
    if not book_ids:
        return set()

    # ① 삭제 대상을 원본으로 삼는 리텔들 ② 삭제 대상의 원본들
    child_rows = await db.execute(
        select(Book.id).where(Book.retelling_source_book_id.in_(book_ids))
    )
    parent_rows = await db.execute(
        select(Book.retelling_source_book_id).where(Book.id.in_(book_ids))
    )
    candidates = {bid for (bid,) in child_rows.all() if bid}
    candidates |= {bid for (bid,) in parent_rows.all() if bid}
    candidates -= set(book_ids)  # 삭제 대상 자신은 '살아남는 책'이 아니다
    if not candidates:
        return set()

    return set(await collect_book_image_keys(db, list(candidates)))


async def collect_purgeable_image_keys(
    db: AsyncSession, book_ids: list[str]
) -> list[str]:
    """삭제 대상 책들에서 **실제로 파기해도 안전한** 이미지 키 전부.

    세 삭제 경로(계정 삭제·동의 철회·단건 삭제)의 공통 진입점이다. 한 곳에 모아 두면
    '한 경로만 고치고 나머지가 새는' 반복 결함이 생기지 않는다.

    - `collect_book_image_keys`: 현재 참조 중인 표지·페이지 URL 역산(N1)
    - `collect_job_image_keys`: 잡이 기록한 중간 산출물(M12) — 실패·교체분 포함
    - 마지막에 **다른 책이 아직 참조 중인 키를 제외**(H6)
    """
    keys = await collect_book_image_keys(db, book_ids)
    keys.extend(await collect_job_image_keys(db, book_ids))
    keys = list(dict.fromkeys(keys))
    if not keys:
        return []

    still_referenced = await _keys_referenced_by_other_books(db, book_ids)
    if not still_referenced:
        return keys
    return [k for k in keys if k not in still_referenced]
