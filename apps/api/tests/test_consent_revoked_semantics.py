"""L3 게이트 — 동의 철회 후 `revoked` 필드의 의미.

2026-08-09 중간 E2E: 철회 직후 `GET /v1/consent` 가 `{"granted": false, "revoked": false}`
를 돌려줬다. 활성 동의 행이 없으면 무조건 기본 응답(revoked=False)으로 떨어졌기 때문이다.
게이트 자체는 granted=False 로 정확히 막히므로 기능 영향은 없었지만, `revoked` 를 신뢰하는
클라이언트는 '철회된 적 없음'으로 오판한다.
"""

import uuid

import pytest


@pytest.mark.asyncio
async def test_never_consented_user_is_not_revoked(client, db_session):
    headers = {"X-User-Key": str(uuid.uuid4())}
    res = await client.get("/v1/consent", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["granted"] is False
    assert body["revoked"] is False, "동의한 적 없는 사용자를 '철회됨'으로 표시하면 안 된다"


@pytest.mark.asyncio
async def test_revoked_user_reports_revoked_true(client, db_session):
    headers = {"X-User-Key": str(uuid.uuid4())}
    await client.post(
        "/v1/consent",
        headers=headers,
        json={"privacy": True, "photos": True, "data_processing": True},
    )
    revoke = await client.post("/v1/consent/revoke", headers=headers)
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True, "철회 응답이 revoked=false 다"

    after = await client.get("/v1/consent", headers=headers)
    body = after.json()
    assert body["granted"] is False
    assert body["revoked"] is True, "철회 후 조회가 revoked=false 다(L3 회귀)"


# ---------------------------------------------------------------- R3-4: 동의 payload 봉인


@pytest.mark.asyncio
async def test_grant_rejects_unknown_fields(client):
    """미지 필드 동의 payload는 422로 거부된다(조용한 no-op 금지).

    R3-4b: 이전에는 `{"granted": true, "photo_consent": true}` 같은 오타 payload가 200을
    받고 **아무것도 동의하지 않은 채** 성공처럼 보였다. 실제로 리포 안의 테스트 헬퍼가
    정확히 그 형태였고, 사진 동의 테스트들이 게이트 미작동 상태로 통과하고 있었다.

    red-proof: routers/consent.py 의 `model_config = ConfigDict(extra="forbid")` 를
    지우면 이 테스트가 FAIL 한다(200 반환).
    """
    uk = {"X-User-Key": str(uuid.uuid4())}
    res = await client.post(
        "/v1/consent",
        json={"granted": True, "photo_consent": True},
        headers=uk,
    )
    assert res.status_code == 422, res.text

    # 거부됐으니 동의 상태는 그대로 '동의한 적 없음'
    got = await client.get("/v1/consent", headers=uk)
    assert got.json()["granted"] is False
    assert got.json()["photos"] is False


@pytest.mark.asyncio
async def test_from_photo_blocked_without_photo_consent(client, monkeypatch):
    """사진 동의 없이 from-photo 를 호출하면 차단된다 — 게이트가 실제로 켜져 있음을 증명.

    R3-4c: 위 false-green 헬퍼가 아무것도 grant 하지 않았는데도 사진 테스트가 통과했다는
    것은, 그 테스트들이 게이트를 전혀 통과시키지 못하는 상태였다는 뜻이다. 게이트가
    라이브임을 별도로 고정한다.
    """
    from src.core.config import settings

    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    uk = {"X-User-Key": str(uuid.uuid4())}
    res = await client.post(
        "/v1/characters/from-photo",
        files={"photo": ("p.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"name": "테스트", "style": "cartoon"},
        headers=uk,
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_from_photo_allowed_after_real_photo_consent(client, monkeypatch):
    """양성 대조: 정본 필드로 동의하면 게이트를 통과한다(403이 아님)."""
    from src.core.config import settings

    monkeypatch.setattr(settings, "require_parental_consent_in_testing", True)
    uk = {"X-User-Key": str(uuid.uuid4())}
    granted = await client.post(
        "/v1/consent",
        json={"privacy": True, "photos": True, "data_processing": True},
        headers=uk,
    )
    assert granted.status_code == 200 and granted.json()["photos"] is True

    res = await client.post(
        "/v1/characters/from-photo",
        files={"photo": ("p.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"name": "테스트", "style": "cartoon"},
        headers=uk,
    )
    assert res.status_code != 403, res.text
