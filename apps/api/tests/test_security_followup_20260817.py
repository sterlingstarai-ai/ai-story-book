"""2026-08-17 보안 감사 후속(F2/F3) — 인페인트 마스크 하드닝 + 크레딧-잡 원자성.

- F3(books.py:264): 크레딧 차감과 잡 INSERT 를 한 커밋으로 원자화. 잡 생성 실패 시
  차감이 롤백으로 되돌려지고 **중간 커밋 상태(usage/refund 트랜잭션)가 남지 않는다**.
- F2(books.py:895): 인페인트 마스크 업로드 크기/타입 검증 + 마스크 파기 배선.
"""

import pytest
from sqlalchemy import select

from src.core.exceptions import InternalServerError
from src.models.db import Book, CreditTransaction, Job, Page, UserCredits


async def _balance(db, user_key: str) -> int:
    row = await db.execute(
        select(UserCredits.credits).where(UserCredits.user_key == user_key)
    )
    return row.scalar_one()


# ───────────────────────── F3: 크레딧-잡 원자성 ─────────────────────────


@pytest.mark.asyncio
async def test_create_job_with_credit_is_atomic_on_job_failure(db_session):
    """잡 생성이 실패하면 차감이 원자적으로 롤백되고 usage/refund 트랜잭션이 남지 않는다.

    red-proof: credits.use_credit 를 commit=True 로 되돌리면(별도 커밋) 차감이 먼저
    커밋돼 usage 트랜잭션이 영속하고 옛 코드가 refund 를 남긴다 → 아래 `txns == []` FAIL.
    """
    from src.routers import books
    from src.services.credits import credits_service

    user_key = "f3-atomic-user"
    await credits_service.add_credits(
        db_session, user_key, amount=3, transaction_type="purchase", description="seed"
    )
    before = await _balance(db_session, user_key)

    # 같은 id 의 잡을 먼저 커밋 → 이후 INSERT 는 PK 위반으로 실패(실 DB 제약).
    db_session.add(Job(id="f3-dup-job", status="done", user_key=user_key))
    await db_session.commit()

    with pytest.raises(InternalServerError):
        await books._create_job_with_credit(
            db=db_session,
            user_key=user_key,
            job_id="f3-dup-job",
            current_step="queued",
            credit_description="책 생성",
        )
    await db_session.rollback()

    after = await _balance(db_session, user_key)
    assert after == before, "잡 생성 실패 시 차감이 원자적으로 롤백돼야 한다"

    txns = (
        await db_session.execute(
            select(CreditTransaction).where(
                CreditTransaction.user_key == user_key,
                CreditTransaction.reference_id == "f3-dup-job",
            )
        )
    ).scalars().all()
    assert txns == [], "중간 커밋 상태(usage/refund 트랜잭션)가 남으면 안 된다"


@pytest.mark.asyncio
async def test_create_job_with_credit_happy_path_deducts_and_creates(db_session):
    """정상 경로: 차감 1 + 잡 1행이 함께 커밋된다."""
    from src.routers import books
    from src.services.credits import credits_service

    user_key = "f3-happy-user"
    await credits_service.add_credits(
        db_session, user_key, amount=2, transaction_type="purchase", description="seed"
    )
    before = await _balance(db_session, user_key)

    await books._create_job_with_credit(
        db=db_session,
        user_key=user_key,
        job_id="f3-ok-job",
        current_step="queued",
        credit_description="책 생성",
    )

    after = await _balance(db_session, user_key)
    assert after == before - 1
    job = (
        await db_session.execute(select(Job).where(Job.id == "f3-ok-job"))
    ).scalar_one_or_none()
    assert job is not None and job.status == "queued"


# ───────────────────────── F2: 마스크 검증 + 파기 ─────────────────────────


async def _seed_done_book(db, user_key: str, job_id="f2-job", book_id="f2-book"):
    db.add(Job(id=job_id, status="done", user_key=user_key))
    await db.flush()
    db.add(
        Book(
            id=book_id,
            job_id=job_id,
            title="원본",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=user_key,
            cover_image_url="https://img/cover.png",
        )
    )
    db.add(
        Page(
            book_id=book_id,
            page_number=1,
            text="원본 1",
            image_url="https://img/p1.png",
            image_prompt="p",
        )
    )
    await db.commit()
    return job_id, book_id


@pytest.mark.asyncio
async def test_inpaint_rejects_oversized_mask(client, db_session, headers, monkeypatch):
    """10MB 초과 마스크는 예산 소비·업로드 전에 거부(업로드 DoS 표면 축소)."""
    from src.core.config import settings

    monkeypatch.setattr(settings, "image_provider", "fal")  # supports_inpaint=True
    job_id, _ = await _seed_done_book(db_session, headers["X-User-Key"])

    oversized = b"\x00" * (10 * 1024 * 1024 + 1)
    res = await client.post(
        f"/v1/books/{job_id}/pages/1/inpaint",
        files={"mask": ("mask.png", oversized, "image/png")},
        data={"region_prompt": "make the sky orange"},
        headers=headers,
    )
    assert res.status_code in (400, 413, 422), res.text


@pytest.mark.asyncio
async def test_inpaint_rejects_non_image_mask(client, db_session, headers, monkeypatch):
    """이미지가 아닌 content-type 마스크는 거부."""
    from src.core.config import settings

    monkeypatch.setattr(settings, "image_provider", "fal")
    job_id, _ = await _seed_done_book(
        db_session, headers["X-User-Key"], job_id="f2-job2", book_id="f2-book2"
    )

    res = await client.post(
        f"/v1/books/{job_id}/pages/1/inpaint",
        files={"mask": ("mask.txt", b"not an image", "text/plain")},
        data={"region_prompt": "make the sky orange"},
        headers=headers,
    )
    assert res.status_code in (400, 422), res.text


def test_mask_purge_wired_in_all_three_deletion_paths():
    """마스크 파기가 3개 삭제 경로(단건·계정·철회)에 모두 배선됐다(두 벌 규칙 드리프트 가드).

    red-proof: 셋 중 하나에서 mask_file_prefix enqueue 를 지우면 이 불변식이 FAIL.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "routers"
    for name in ("library.py", "users.py", "consent.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "mask_file_prefix(" in src, f"{name} 에 마스크 파기 배선이 없다(드리프트)"


@pytest.mark.asyncio
async def test_book_delete_enqueues_mask_prefix_purge(
    client, db_session, headers, monkeypatch
):
    """단건 책 삭제가 masks/{book_id}/ prefix 파기도 배선한다(고아 마스크 방지).

    red-proof: library 삭제의 mask_task enqueue 를 지우면 masks/ prefix 가 캡처되지 않는다.
    """
    from src.routers import library

    _, book_id = await _seed_done_book(
        db_session, headers["X-User-Key"], job_id="f2-del-job", book_id="f2-del-book"
    )

    captured: list[str] = []
    real = library.enqueue_purge_prefix

    def spy(db, *, user_key, reason, prefix):
        captured.append(prefix)
        return real(db, user_key=user_key, reason=reason, prefix=prefix)

    monkeypatch.setattr(library, "enqueue_purge_prefix", spy)

    res = await client.delete(f"/v1/library/{book_id}", headers=headers)
    assert res.status_code in (200, 204), res.text
    assert f"masks/{book_id}/" in captured, captured
