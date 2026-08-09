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
