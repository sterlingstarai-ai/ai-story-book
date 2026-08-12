"""R3-1/R3-2: 타 유저 리소스 **읽기** 경로 IDOR + 공유 이미지 프록시 confinement.

왜 새로 필요한가(플랫폼 E2E 2026-08-11 반송분):
기존 소유권 테스트는 대부분 *쓰기* 경로였거나 **존재하지 않는 id**("p-nonexistent-999")로
접근했다. 존재하지 않는 id는 `user_key` 술어를 지워도 여전히 0건이라 통과하므로,
IDOR 보호를 전혀 검증하지 못한다(가짜 green).

여기서는 전부 **유저 A가 실제로 소유한 id**를 유저 B가 읽는다. 따라서
  - books.py 의 `if book.user_key != user_key: raise AuthorizationError()`
  - profiles.py 의 `.where(ChildProfile.user_key == user_key)`
  - dependencies.py 의 `ChildProfile.user_key == user_key`
중 어느 하나라도 지우면 해당 테스트가 FAIL 한다(red-proof 근거).
"""

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import Book, ChildProfile, Job, Page

OWNER = {"X-User-Key": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"}
ATTACKER = {"X-User-Key": "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"}

BOOK_ID = "book-owned-by-a"
JOB_ID = "job-owned-by-a"
PROFILE_ID = "profile-owned-by-a"
SECRET_TITLE = "A의 비밀 동화 제목"


async def _seed_owner_resources(db_session: AsyncSession) -> None:
    db_session.add(Job(id=JOB_ID, status="done", user_key=OWNER["X-User-Key"]))
    await db_session.flush()
    db_session.add(
        ChildProfile(
            id=PROFILE_ID,
            user_key=OWNER["X-User-Key"],
            name="민지",
            age_band="5-7",
            birth_year=2020,
            birth_month=5,
            is_default=True,
        )
    )
    db_session.add(
        Book(
            id=BOOK_ID,
            job_id=JOB_ID,
            title=SECRET_TITLE,
            language="ko",
            target_age="5-7",
            style="watercolor",
            user_key=OWNER["X-User-Key"],
            cover_image_url="http://localhost:9000/storybook/images/mock/cover.png",
        )
    )
    db_session.add(
        Page(
            book_id=BOOK_ID,
            page_number=1,
            text="A의 비밀 본문",
            image_url="http://localhost:9000/storybook/images/mock/p1.png",
            image_prompt="p",
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_book_detail_read_blocked_for_other_user(
    client: AsyncClient, db_session: AsyncSession
):
    """타인이 소유한 책 상세를 읽을 수 없다(제목·본문 누출 0)."""
    await _seed_owner_resources(db_session)

    owner_res = await client.get(f"/v1/books/{BOOK_ID}/detail", headers=OWNER)
    assert owner_res.status_code == 200, owner_res.text
    assert SECRET_TITLE in owner_res.text  # 양성 대조: 소유자는 읽힌다

    res = await client.get(f"/v1/books/{BOOK_ID}/detail", headers=ATTACKER)
    assert res.status_code in (403, 404), res.text
    assert SECRET_TITLE not in res.text, "권한 거부 응답에 책 제목이 새어나갔다"
    assert "A의 비밀 본문" not in res.text


@pytest.mark.asyncio
async def test_book_pdf_export_blocked_for_other_user(
    client: AsyncClient, db_session: AsyncSession
):
    """타인이 소유한 책의 PDF를 내보낼 수 없다."""
    await _seed_owner_resources(db_session)

    res = await client.get(f"/v1/books/{BOOK_ID}/pdf", headers=ATTACKER)
    assert res.status_code in (403, 404), res.text
    assert SECRET_TITLE not in res.text


@pytest.mark.asyncio
async def test_child_profile_list_does_not_leak_other_users_children(
    client: AsyncClient, db_session: AsyncSession
):
    """프로필 목록은 계정 스코프 — 타인의 자녀 PII가 섞이면 안 된다."""
    await _seed_owner_resources(db_session)

    owner_res = await client.get("/v1/profiles", headers=OWNER)
    assert owner_res.status_code == 200
    assert [p["id"] for p in owner_res.json()["profiles"]] == [PROFILE_ID]

    res = await client.get("/v1/profiles", headers=ATTACKER)
    assert res.status_code == 200
    assert res.json()["profiles"] == [], "타 유저의 자녀 프로필이 노출됐다"
    assert "민지" not in res.text


@pytest.mark.asyncio
async def test_growth_report_rejects_other_users_real_profile_id(
    client: AsyncClient, db_session: AsyncSession
):
    """**실재하지만 타인 소유**인 profile_id로 성장 리포트를 조회할 수 없다.

    기존 테스트는 존재하지 않는 id를 썼는데, 그건 `user_key` 술어를 지워도 통과한다.
    """
    await _seed_owner_resources(db_session)

    owner_res = await client.get(
        "/v1/growth", headers={**OWNER, "X-Profile-Id": PROFILE_ID}
    )
    assert owner_res.status_code == 200, owner_res.text  # 양성 대조

    res = await client.get(
        "/v1/growth", headers={**ATTACKER, "X-Profile-Id": PROFILE_ID}
    )
    assert res.status_code == 400, res.text
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_growth_answers_rejects_other_users_real_profile_id(
    client: AsyncClient, db_session: AsyncSession
):
    """타인 소유 profile_id로 퀴즈 응답을 기록할 수 없다(dangling 쓰기 차단)."""
    await _seed_owner_resources(db_session)

    res = await client.post(
        "/v1/growth/answers",
        json={"book_id": BOOK_ID, "quiz_type": "vocab", "correct": True},
        headers={**ATTACKER, "X-Profile-Id": PROFILE_ID},
    )
    assert res.status_code == 400, res.text

    from sqlalchemy import select

    from src.models.db import QuizAnswer

    saved = (await db_session.execute(select(QuizAnswer))).scalars().all()
    assert saved == [], "거부됐는데 QuizAnswer가 저장됐다"


# ---------------------------------------------------------------- R3-2 프록시 confinement


@pytest.mark.asyncio
async def test_share_image_proxy_refuses_url_outside_our_bucket(
    client: AsyncClient, db_session: AsyncSession
):
    """저장 URL이 외부 도메인이면 공유 프록시가 **대리 fetch 하지 않는다**(404).

    R2 이후 신규 행은 전부 자체 스토리지 URL이지만, mock이 picsum을 저장하던 시절의
    **레거시 행**이 남아 있다. 방어는 쓰기 시점이 아니라 **서빙 시점**이 load-bearing이다.

    red-proof: shares.py `_stream_share_image`의
    `key = key_from_public_url(stored_url); if not key: return 404` 를 지우고
    stored_url을 그대로 fetch 하게 만들면 이 테스트가 FAIL 한다.

    핵심: 스토리지 fetch를 **아무 키에나 바이트를 돌려주는** 페이크로 바꾼다. 그렇지
    않으면 confinement를 제거해도 fetch가 자체 실패해 404가 나오므로, 테스트가
    '올바른 이유'가 아니라 우연히 통과한다(가짜 green).
    """
    await _seed_owner_resources(db_session)

    # 레거시 외부 URL 행을 재현
    book = await db_session.get(Book, BOOK_ID)
    book.cover_image_url = "https://picsum.photos/seed/1/768/1024"
    await db_session.commit()

    created = await client.post(f"/v1/books/{BOOK_ID}/share", json={}, headers=OWNER)
    assert created.status_code == 200, created.text
    token = created.json()["token"]

    fetched = []

    async def _fetch_anything(key):
        fetched.append(key)
        return b"\x89PNG-bytes", "image/png"

    with patch("src.routers.shares.get_object_bytes", new=_fetch_anything):
        res = await client.get(f"/share/{token}/img/cover")

    assert fetched == [], (
        f"외부 도메인 URL로 스토리지 fetch를 시도했다 — 임의 URL 프록시(SSRF 표면). tried={fetched}"
    )
    assert res.status_code == 404
    assert res.content == b""


@pytest.mark.asyncio
async def test_share_image_proxy_serves_our_own_bucket_url(
    client: AsyncClient, db_session: AsyncSession
):
    """양성 대조: 자체 스토리지 URL이면 정상 서빙된다.

    이게 없으면 위 테스트는 '프록시가 항상 404'여도 통과한다.
    """
    await _seed_owner_resources(db_session)

    created = await client.post(f"/v1/books/{BOOK_ID}/share", json={}, headers=OWNER)
    token = created.json()["token"]

    fetched = []

    async def _fetch_anything(key):
        fetched.append(key)
        return b"\x89PNG-bytes", "image/png"

    with patch("src.routers.shares.get_object_bytes", new=_fetch_anything):
        res = await client.get(f"/share/{token}/img/cover")

    assert res.status_code == 200, res.text
    assert res.content == b"\x89PNG-bytes"
    assert fetched == ["images/mock/cover.png"], fetched


@pytest.mark.asyncio
async def test_share_image_proxy_404_for_unknown_token(client: AsyncClient):
    res = await client.get(f"/share/{uuid.uuid4().hex}/img/cover")
    assert res.status_code == 404
