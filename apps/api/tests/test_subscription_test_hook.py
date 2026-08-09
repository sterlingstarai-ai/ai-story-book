"""M4 게이트 — 비프로덕션 전용 구독 부여 훅의 fail-closed 동작.

배경: 유료 구독은 앱스토어 검증 영수증으로만 생성된다(`/credits/subscribe` 403,
`iap_verifier._local_success` 가 운영에서 fail-closed) — 보안상 올바르다. 그 결과 실키
없는 mock E2E 라운드에서는 구독 게이트 하위 표면(시리즈 2권차·PDF·프리미엄 스타일)에
도달할 방법이 없어 중간 점검에서 DB 를 직접 건드려야 했다.

이 훅은 그 공백을 메우되, **운영에서 결제 우회 경로가 되면 안 된다**:
`ENABLE_TEST_HOOKS` 없이는 404(존재 자체를 숨김), 그 위에 ADMIN_API_KEY 필수.
"""

import uuid

import pytest

ENDPOINT = "/v1/credits/admin/grant-subscription"
ADMIN_KEY = "test-admin-key"


@pytest.fixture()
def headers():
    return {"X-User-Key": str(uuid.uuid4())}


@pytest.mark.asyncio
async def test_hook_is_invisible_when_disabled(client, db_session, headers, monkeypatch):
    """기본값(비활성)에서는 admin 키가 있어도 404 — 존재를 노출하지 않는다."""
    from src.core.config import settings

    monkeypatch.setattr(settings, "enable_test_hooks", False, raising=False)
    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY, raising=False)

    res = await client.post(
        ENDPOINT, headers={**headers, "X-Admin-Key": ADMIN_KEY}, json={"plan": "premium"}
    )
    assert res.status_code == 404, (
        f"운영 구성에서 훅이 노출됐다(결제 우회 위험): {res.status_code} {res.text[:200]}"
    )


@pytest.mark.asyncio
async def test_hook_requires_admin_key_when_enabled(
    client, db_session, headers, monkeypatch
):
    from src.core.config import settings

    monkeypatch.setattr(settings, "enable_test_hooks", True, raising=False)
    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY, raising=False)

    no_key = await client.post(ENDPOINT, headers=headers, json={"plan": "premium"})
    assert no_key.status_code in (401, 403), "admin 키 없이 통과했다"

    bad_key = await client.post(
        ENDPOINT, headers={**headers, "X-Admin-Key": "wrong"}, json={"plan": "premium"}
    )
    assert bad_key.status_code in (401, 403), "잘못된 admin 키로 통과했다"


@pytest.mark.asyncio
async def test_hook_grants_subscription_and_unlocks_gates(
    client, db_session, headers, monkeypatch
):
    from src.core.config import settings

    monkeypatch.setattr(settings, "enable_test_hooks", True, raising=False)
    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY, raising=False)

    res = await client.post(
        ENDPOINT, headers={**headers, "X-Admin-Key": ADMIN_KEY}, json={"plan": "premium"}
    )
    assert res.status_code == 200, f"{res.status_code} {res.text[:300]}"
    assert res.json()["plan"] == "premium"
    assert res.json()["status"] == "active"

    status = await client.get("/v1/credits/status", headers=headers)
    assert status.json()["subscription"]["plan"] == "premium", "구독이 반영되지 않았다"


@pytest.mark.asyncio
async def test_hook_rejects_free_and_unknown_plans(
    client, db_session, headers, monkeypatch
):
    from src.core.config import settings

    monkeypatch.setattr(settings, "enable_test_hooks", True, raising=False)
    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY, raising=False)

    for plan in ("free", "platinum", ""):
        res = await client.post(
            ENDPOINT, headers={**headers, "X-Admin-Key": ADMIN_KEY}, json={"plan": plan}
        )
        assert res.status_code in (400, 422), f"plan={plan!r} 이 통과했다"
