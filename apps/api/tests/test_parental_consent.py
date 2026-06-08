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
