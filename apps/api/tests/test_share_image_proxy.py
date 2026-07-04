"""공유 이미지 토큰 프록시 (N3) — 철회/만료가 이미지에도 적용되는지.

이전: 공개 페이지가 영구 공개 버킷 URL을 직접 임베드 → 철회해도 이미지는 영구 접근 가능,
book_id 추측으로 원본 URL 취득 가능. 이제 /share/{token}/img/... 프록시로만 서빙한다.
"""

import pytest

from src.core.config import settings
from src.models.db import Book, Job, Page
from src.routers import shares as shares_module

H = {"X-User-Key": "77777777-7777-4777-8777-777777777777"}
PUBLIC_BASE = "https://cdn.example.com/bucket"


async def _seed_book(db, book_id):
    db.add(Job(id=f"job-{book_id}", status="done", user_key=H["X-User-Key"]))
    await db.flush()
    db.add(
        Book(
            id=book_id,
            job_id=f"job-{book_id}",
            title="토끼 모험",
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=H["X-User-Key"],
            cover_image_url=f"{PUBLIC_BASE}/books/{book_id}/cover.png",
        )
    )
    db.add(
        Page(
            book_id=book_id,
            page_number=1,
            text="첫 페이지",
            image_url=f"{PUBLIC_BASE}/books/{book_id}/p1.png",
            image_prompt="p",
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_share_html_embeds_proxy_not_raw_bucket_url(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "s3_public_url", PUBLIC_BASE)
    await _seed_book(db_session, "shimg1")
    token = (await client.post("/v1/books/shimg1/share", json={}, headers=H)).json()["token"]

    pub = await client.get(f"/share/{token}")
    assert pub.status_code == 200
    # 원본 공개 버킷 URL은 페이지에 절대 노출되지 않는다.
    assert PUBLIC_BASE not in pub.text
    # 대신 토큰 프록시 경로를 임베드.
    assert f"/share/{token}/img/cover" in pub.text
    assert f"/share/{token}/img/page/1" in pub.text


@pytest.mark.asyncio
async def test_share_image_served_then_blocked_after_revoke(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "s3_public_url", PUBLIC_BASE)

    async def fake_get_object_bytes(key):
        return b"\x89PNG-bytes", "image/png"

    monkeypatch.setattr(shares_module, "get_object_bytes", fake_get_object_bytes)
    await _seed_book(db_session, "shimg2")
    token = (await client.post("/v1/books/shimg2/share", json={}, headers=H)).json()["token"]

    # 활성 공유: 이미지 200 + no-store(철회 즉시 반영)
    img = await client.get(f"/share/{token}/img/cover")
    assert img.status_code == 200
    assert img.content == b"\x89PNG-bytes"
    assert img.headers.get("content-type") == "image/png"
    assert "no-store" in img.headers.get("cache-control", "")

    page_img = await client.get(f"/share/{token}/img/page/1")
    assert page_img.status_code == 200

    # 철회 후: 이미지도 404(이전엔 영구 접근 가능했음)
    await client.post("/v1/books/shimg2/share/revoke", headers=H)
    blocked = await client.get(f"/share/{token}/img/cover")
    assert blocked.status_code == 404


@pytest.mark.asyncio
async def test_share_image_404_for_unknown_token(client):
    r = await client.get("/share/deadbeefdeadbeef/img/cover")
    assert r.status_code == 404
