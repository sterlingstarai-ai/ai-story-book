"""보호자 동의(PIPA/COPPA) 게이트 + 기록 엔드포인트 테스트."""

import pytest

from src.core.config import settings
from src.core.consent import require_photo_consent
from src.core.exceptions import AuthorizationError
from src.core.utils import utcnow
from src.models.db import UserConsent


@pytest.fixture
def consent_enforced(monkeypatch):
    """테스트 환경에서도 동의 집행을 켠다(기본은 off)."""
    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)


@pytest.mark.asyncio
async def test_gate_blocks_without_consent(db_session, consent_enforced):
    with pytest.raises(AuthorizationError):
        await require_photo_consent(db_session, "user-no-consent")


@pytest.mark.asyncio
async def test_gate_passes_after_grant(db_session, consent_enforced):
    db_session.add(
        UserConsent(
            user_key="user-consent-ok",
            privacy=True,
            photos=True,
            data_processing=True,
            granted=True,
        )
    )
    await db_session.commit()
    await require_photo_consent(db_session, "user-consent-ok")  # raise 없음


@pytest.mark.asyncio
async def test_gate_blocks_after_revoke(db_session, consent_enforced):
    db_session.add(
        UserConsent(
            user_key="user-revoked",
            privacy=True,
            photos=True,
            data_processing=True,
            granted=False,
            revoked_at=utcnow(),
        )
    )
    await db_session.commit()
    with pytest.raises(AuthorizationError):
        await require_photo_consent(db_session, "user-revoked")


@pytest.mark.asyncio
async def test_gate_bypassed_in_testing_by_default(db_session):
    # 기본 testing(플래그 off) → 동의 없이 통과(기존 테스트 무파손 보장)
    await require_photo_consent(db_session, "user-bypass")


@pytest.mark.asyncio
async def test_grant_and_get_consent(client):
    h = {"X-User-Key": "44444444-4444-4444-8444-444444444444"}
    res = await client.post(
        "/v1/consent",
        json={"privacy": True, "photos": True, "data_processing": True},
        headers=h,
    )
    assert res.status_code == 200, res.text
    assert res.json()["granted"] is True
    assert res.json()["photos"] is True

    got = (await client.get("/v1/consent", headers=h)).json()
    assert got["granted"] is True
    assert got["photos"] is True


@pytest.mark.asyncio
async def test_revoke_consent(client):
    h = {"X-User-Key": "55555555-5555-4555-8555-555555555555"}
    await client.post(
        "/v1/consent",
        json={"privacy": True, "photos": True, "data_processing": True},
        headers=h,
    )
    rev = await client.post("/v1/consent/revoke", headers=h)
    assert rev.status_code == 200
    assert rev.json()["granted"] is False
    assert (await client.get("/v1/consent", headers=h)).json()["granted"] is False


@pytest.mark.asyncio
async def test_from_photo_blocked_without_consent(client, consent_enforced):
    res = await client.post(
        "/v1/characters/from-photo",
        files={"photo": ("x.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"style": "cartoon"},
        headers={"X-User-Key": "66666666-6666-4666-8666-666666666666"},
    )
    assert res.status_code == 403, res.text


def _character(cid, uk, from_photo):
    from src.models.db import Character

    return Character(
        id=cid,
        name="아이",
        master_description="동화 주인공 설명입니다",
        appearance={"age_visual": "6", "face": "f", "hair": "h", "skin": "s", "body": "b"},
        clothing={"top": "t", "bottom": "b", "shoes": "s", "accessories": "a"},
        personality_traits=["밝음"],
        user_key=uk,
        from_photo=from_photo,
    )


@pytest.mark.asyncio
async def test_photo_character_reuse_gated_text_not(db_session, consent_enforced):
    from src.core.consent import require_consent_for_characters

    db_session.add(_character("char-photo-1", "uk-reuse", True))
    db_session.add(_character("char-text-1", "uk-reuse", False))
    await db_session.commit()

    # 텍스트 캐릭터만 → 동의 없이도 통과(오버블로킹 방지)
    await require_consent_for_characters(db_session, "uk-reuse", ["char-text-1"])
    # 사진 파생 캐릭터 재사용 → 동의 없으면 403
    with pytest.raises(AuthorizationError):
        await require_consent_for_characters(db_session, "uk-reuse", ["char-photo-1"])


@pytest.mark.asyncio
async def test_photos_consent_evaluated_independently_of_granted(
    db_session, consent_enforced
):
    # 최근 비철회 행의 photos=True 이면 granted(필수동의) 값과 무관하게 사진 게이트 통과
    db_session.add(
        UserConsent(
            user_key="uk-decouple",
            privacy=False,
            photos=True,
            data_processing=False,
            granted=False,
        )
    )
    await db_session.commit()
    await require_photo_consent(db_session, "uk-decouple")  # raise 없음


@pytest.mark.asyncio
async def test_create_book_blocked_with_photo_character(
    client, db_session, consent_enforced
):
    h = {"X-User-Key": "99999999-9999-4999-8999-999999999999"}
    db_session.add(_character("char-book-photo", h["X-User-Key"], True))
    await db_session.commit()

    res = await client.post(
        "/v1/books",
        json={
            "topic": "우주 여행",
            "target_age": "5-7",
            "style": "watercolor",
            "character_ids": ["char-book-photo"],
        },
        headers=h,
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_revoke_deletes_photo_characters(client, db_session, monkeypatch):
    from sqlalchemy import select

    from src.models.db import Character
    from src.services.storage import storage_service

    async def _noop(prefix):
        return 0

    monkeypatch.setattr(storage_service, "delete_prefix", _noop)

    h = {"X-User-Key": "a8888888-8888-4888-8888-888888888888"}
    uk = h["X-User-Key"]
    db_session.add(_character("char-rev-photo", uk, True))
    db_session.add(_character("char-rev-text", uk, False))
    await db_session.commit()

    await client.post(
        "/v1/consent",
        json={"privacy": True, "photos": True, "data_processing": True},
        headers=h,
    )
    rev = await client.post("/v1/consent/revoke", headers=h)
    assert rev.status_code == 200

    remaining = (
        await db_session.execute(select(Character).where(Character.user_key == uk))
    ).scalars().all()
    ids = {c.id for c in remaining}
    assert "char-rev-photo" not in ids  # 사진 파생 → 파기
    assert "char-rev-text" in ids  # 텍스트 → 유지


@pytest.mark.asyncio
async def test_create_book_rejects_foreign_character(client, db_session):
    # 캐릭터 소유자 A
    db_session.add(_character("char-owner-a", "owner-a-key", from_photo=False))
    await db_session.commit()
    # 다른 유저 B가 그 캐릭터로 책 생성 시도 → 403(IDOR 차단)
    res = await client.post(
        "/v1/books",
        json={
            "topic": "우주 여행",
            "target_age": "5-7",
            "style": "watercolor",
            "character_ids": ["char-owner-a"],
        },
        headers={"X-User-Key": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"},
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_revoke_closes_gate_for_photos_only_consent(
    db_session, client, consent_enforced
):
    h = {"X-User-Key": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
    uk = h["X-User-Key"]
    # photos=true·granted=false(필수동의 미충족) — 게이트는 photos 독립 평가로 통과
    await client.post(
        "/v1/consent",
        json={"privacy": False, "photos": True, "data_processing": False},
        headers=h,
    )
    await require_photo_consent(db_session, uk)  # raise 없음

    rev = await client.post("/v1/consent/revoke", headers=h)
    assert rev.status_code == 200
    # 철회 후 게이트가 실제로 닫힌다(granted=False 잔여행이 열어두지 않음)
    with pytest.raises(AuthorizationError):
        await require_photo_consent(db_session, uk)
