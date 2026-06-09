"""책 공유 — 생성/철회/공개렌더 + IDOR + 만료 + PII 비노출."""

import pytest

from src.models.db import Book, Job, Page

H = {"X-User-Key": "55555555-5555-4555-8555-555555555555"}
H2 = {"X-User-Key": "66666666-6666-4666-8666-666666666666"}


async def _seed_book(db, user_key, book_id):
    db.add(Job(id=f"job-{book_id}", status="done", user_key=user_key))
    await db.flush()
    db.add(
        Book(
            id=book_id,
            job_id=f"job-{book_id}",
            title="용감한 토끼의 모험",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=user_key,
            cover_image_url="https://cdn.example.com/cover.png",
        )
    )
    db.add(
        Page(
            book_id=book_id,
            page_number=1,
            text="옛날 옛날 작은 토끼가 살았어요.",
            image_url="https://cdn.example.com/p1.png",
            image_prompt="p",
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_create_and_public_render(client, db_session):
    await _seed_book(db_session, H["X-User-Key"], "sb1")

    r = await client.post("/v1/books/sb1/share", json={}, headers=H)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["url"].endswith(f"/share/{token}")
    assert r.json()["expires_at"] is not None  # 기본 만료 설정

    pub = await client.get(f"/share/{token}")
    assert pub.status_code == 200
    assert "용감한 토끼의 모험" in pub.text  # 제목·본문 노출
    assert "옛날 옛날" in pub.text
    # 검색 비노출
    assert "noindex" in pub.headers.get("x-robots-tag", "").lower()
    assert "noindex" in pub.text
    # PII 비노출: 소유자 키가 페이지에 없어야
    assert H["X-User-Key"] not in pub.text
    # CTA
    assert "동화 만들기" in pub.text


@pytest.mark.asyncio
async def test_share_create_idor_blocked(client, db_session):
    await _seed_book(db_session, H["X-User-Key"], "sb2")
    r = await client.post("/v1/books/sb2/share", json={}, headers=H2)
    assert r.status_code in (403, 404)


@pytest.mark.asyncio
async def test_share_create_missing_book_404(client):
    r = await client.post("/v1/books/no-such-book/share", json={}, headers=H)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_revoke_then_public_404(client, db_session):
    await _seed_book(db_session, H["X-User-Key"], "sb3")
    token = (
        await client.post("/v1/books/sb3/share", json={}, headers=H)
    ).json()["token"]
    assert (await client.get(f"/share/{token}")).status_code == 200

    rv = await client.post("/v1/books/sb3/share/revoke", headers=H)
    assert rv.status_code == 200
    assert (await client.get(f"/share/{token}")).status_code == 404


@pytest.mark.asyncio
async def test_expired_share_404(client, db_session):
    from datetime import timedelta

    from src.core.utils import utcnow
    from src.models.db import BookShare

    await _seed_book(db_session, H["X-User-Key"], "sb4")
    db_session.add(
        BookShare(
            id="expiredtoken",
            book_id="sb4",
            user_key=H["X-User-Key"],
            created_at=utcnow() - timedelta(days=40),
            expires_at=utcnow() - timedelta(days=1),
        )
    )
    await db_session.commit()
    assert (await client.get("/share/expiredtoken")).status_code == 404


@pytest.mark.asyncio
async def test_unknown_token_404(client):
    assert (await client.get("/share/nonexistenttoken123")).status_code == 404
