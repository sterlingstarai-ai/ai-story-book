"""
Phase expansion endpoint tests.

- IAP verify/webhook
- Profiles CRUD
- Settings patch
- Reward ad daily cap
- User data deletion
"""

import pytest
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.utils import utcnow
from src.models.db import Book, ChildProfile, Job, Page, PodOrder, Subscription
from tests.factories import make_book_rows


@pytest.mark.asyncio
async def test_iap_verify_credit_pack_and_idempotency(
    client: AsyncClient,
    headers: dict,
):
    before_balance_res = await client.get("/v1/credits/balance", headers=headers)
    assert before_balance_res.status_code == 200
    before_balance = before_balance_res.json()["credits"]

    payload = {
        "platform": "google",
        "product_id": "credit_pack_5",
        "transaction_id": "test-tx-credit-5",
        "purchase_token": "test-google-purchase-token",
        "is_subscription": False,
    }

    first = await client.post("/v1/iap/verify", json=payload, headers=headers)
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["status"] == "verified"
    assert first_data["credits_added"] == 5
    assert isinstance(first_data.get("verification_source"), str)
    assert first_data["verification_source"]

    second = await client.post("/v1/iap/verify", json=payload, headers=headers)
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["status"] == "already_processed"
    assert second_data["credits_added"] == 0

    after_balance_res = await client.get("/v1/credits/balance", headers=headers)
    assert after_balance_res.status_code == 200
    after_balance = after_balance_res.json()["credits"]
    assert after_balance == before_balance + 5


@pytest.mark.asyncio
async def test_iap_verify_subscription_returns_already_subscribed_for_same_plan(
    client: AsyncClient,
    headers: dict,
):
    first_payload = {
        "platform": "apple",
        "product_id": "subscription_basic",
        "transaction_id": "test-tx-sub-basic-1",
        "receipt_data": "base64-receipt-placeholder-1",
        "is_subscription": True,
    }
    first = await client.post("/v1/iap/verify", json=first_payload, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "verified"

    second_payload = {
        "platform": "apple",
        "product_id": "subscription_basic",
        "transaction_id": "test-tx-sub-basic-2",
        "receipt_data": "base64-receipt-placeholder-2",
        "is_subscription": True,
    }
    second = await client.post("/v1/iap/verify", json=second_payload, headers=headers)
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "already_subscribed"
    assert body["credits_added"] == 0
    assert body["plan"] == "basic"


@pytest.mark.asyncio
async def test_iap_verify_resolves_subscription_from_product_id_even_with_false_flag(
    client: AsyncClient,
    headers: dict,
):
    payload = {
        "platform": "apple",
        "product_id": "subscription_basic",
        "transaction_id": "test-tx-sub-flag-false-1",
        "receipt_data": "base64-receipt-placeholder-flag-false",
        "is_subscription": False,
    }
    response = await client.post("/v1/iap/verify", json=payload, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verified"
    assert body["plan"] == "basic"


@pytest.mark.asyncio
async def test_iap_verify_strict_mode_requires_store_config(
    client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "iap_verification_mode", "strict")
    monkeypatch.setattr(settings, "google_play_package_name", None)
    monkeypatch.setattr(settings, "google_play_access_token", None)

    payload = {
        "platform": "google",
        "product_id": "credit_pack_1",
        "transaction_id": "test-tx-strict-no-config",
        "purchase_token": "test-google-purchase-token",
        "is_subscription": False,
    }
    response = await client.post("/v1/iap/verify", json=payload, headers=headers)
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "Google 스토어 검증 설정이 필요합니다." in body["detail"]


@pytest.mark.asyncio
async def test_iap_verify_strict_mode_uses_dynamic_google_token(
    client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.services.iap_verifier import iap_verifier

    monkeypatch.setattr(settings, "iap_verification_mode", "strict")
    monkeypatch.setattr(settings, "google_play_package_name", "com.example.storybook")
    monkeypatch.setattr(settings, "google_play_access_token", None)

    monkeypatch.setattr(
        iap_verifier,
        "_resolve_google_access_token",
        lambda: "dynamic-access-token",
    )

    async def _mock_fetch_google_purchase(**kwargs):
        return {
            "orderId": "strict-dynamic-order-1",
            "purchaseState": 0,
        }

    monkeypatch.setattr(
        iap_verifier,
        "_fetch_google_purchase",
        _mock_fetch_google_purchase,
    )

    payload = {
        "platform": "google",
        "product_id": "credit_pack_1",
        "transaction_id": "strict-dynamic-order-1",
        "purchase_token": "test-google-token",
        "is_subscription": False,
    }
    response = await client.post("/v1/iap/verify", json=payload, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verified"
    assert body["verification_source"] == "google_play"


@pytest.mark.asyncio
async def test_iap_verify_rejects_whitespace_identifiers(
    client: AsyncClient,
    headers: dict,
):
    response = await client.post(
        "/v1/iap/verify",
        json={
            "platform": "google",
            "product_id": "   ",
            "transaction_id": "   ",
            "purchase_token": "test-google-token",
            "is_subscription": False,
        },
        headers=headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["detail"] == "product_id는 공백일 수 없습니다."

    tx_response = await client.post(
        "/v1/iap/verify",
        json={
            "platform": "google",
            "product_id": "credit_pack_1",
            "transaction_id": "   ",
            "purchase_token": "test-google-token",
            "is_subscription": False,
        },
        headers=headers,
    )
    assert tx_response.status_code == 400
    tx_body = tx_response.json()
    assert tx_body["error"]["code"] == "VALIDATION_ERROR"
    assert tx_body["detail"] == "transaction_id는 공백일 수 없습니다."


@pytest.mark.asyncio
async def test_iap_webhook_updates_receipt_status(
    client: AsyncClient,
    headers: dict,
):
    verify_payload = {
        "platform": "apple",
        "product_id": "subscription_basic",
        "transaction_id": "test-tx-subscription-1",
        "receipt_data": "base64-receipt-placeholder",
        "is_subscription": True,
    }
    verify_response = await client.post(
        "/v1/iap/verify",
        json=verify_payload,
        headers=headers,
    )
    assert verify_response.status_code == 200

    webhook_response = await client.post(
        "/v1/iap/webhook/apple",
        json={
            "transaction_id": "test-tx-subscription-1",
            "status": "cancelled",
            "payload": {"reason": "user_cancelled"},
        },
        headers=headers,
    )
    assert webhook_response.status_code == 200
    webhook_data = webhook_response.json()
    assert webhook_data["status"] == "ok"
    assert webhook_data["receipt_status"] == "cancelled"


@pytest.mark.asyncio
async def test_profiles_crud_and_limit(
    client: AsyncClient,
    headers: dict,
):
    for idx in range(1, 4):
        create_res = await client.post(
            "/v1/profiles",
            json={
                "name": f"아이{idx}",
                "age_band": "5-7",
                "preferred_theme": "모험",
            },
            headers=headers,
        )
        assert create_res.status_code == 200

    over_limit_res = await client.post(
        "/v1/profiles",
        json={"name": "아이4", "age_band": "5-7"},
        headers=headers,
    )
    assert over_limit_res.status_code == 400

    list_res = await client.get("/v1/profiles", headers=headers)
    assert list_res.status_code == 200
    profiles = list_res.json()["profiles"]
    assert len(profiles) == 3

    target_profile_id = profiles[0]["id"]
    patch_res = await client.patch(
        f"/v1/profiles/{target_profile_id}",
        json={"name": "첫째", "is_default": True},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "첫째"
    assert patch_res.json()["is_default"] is True

    delete_res = await client.delete(
        f"/v1/profiles/{target_profile_id}",
        headers=headers,
    )
    assert delete_res.status_code == 200

    final_list_res = await client.get("/v1/profiles", headers=headers)
    assert final_list_res.status_code == 200
    assert len(final_list_res.json()["profiles"]) == 2


@pytest.mark.asyncio
async def test_profiles_default_is_always_maintained(
    client: AsyncClient,
    headers: dict,
):
    first = await client.post(
        "/v1/profiles",
        json={"name": "첫째", "age_band": "5-7"},
        headers=headers,
    )
    assert first.status_code == 200
    first_profile = first.json()
    assert first_profile["is_default"] is True

    second = await client.post(
        "/v1/profiles",
        json={"name": "둘째", "age_band": "5-7"},
        headers=headers,
    )
    assert second.status_code == 200
    second_profile = second.json()
    assert second_profile["is_default"] is False

    unset_default = await client.patch(
        f"/v1/profiles/{first_profile['id']}",
        json={"is_default": False},
        headers=headers,
    )
    assert unset_default.status_code == 400

    set_second_default = await client.patch(
        f"/v1/profiles/{second_profile['id']}",
        json={"is_default": True},
        headers=headers,
    )
    assert set_second_default.status_code == 200
    assert set_second_default.json()["is_default"] is True

    list_after_switch = await client.get("/v1/profiles", headers=headers)
    assert list_after_switch.status_code == 200
    switched_profiles = list_after_switch.json()["profiles"]
    switched_defaults = [p for p in switched_profiles if p["is_default"]]
    assert len(switched_defaults) == 1
    assert switched_defaults[0]["id"] == second_profile["id"]

    delete_default = await client.delete(
        f"/v1/profiles/{second_profile['id']}",
        headers=headers,
    )
    assert delete_default.status_code == 200

    final_list = await client.get("/v1/profiles", headers=headers)
    assert final_list.status_code == 200
    final_profiles = final_list.json()["profiles"]
    assert len(final_profiles) == 1
    assert final_profiles[0]["id"] == first_profile["id"]
    assert final_profiles[0]["is_default"] is True


@pytest.mark.asyncio
async def test_profiles_normalize_trimmed_fields_and_clear_optional_values(
    client: AsyncClient,
    headers: dict,
):
    create_res = await client.post(
        "/v1/profiles",
        json={
            "name": "  첫째  ",
            "age_band": "5-7",
            "preferred_theme": "   ",
            "avatar_url": "   ",
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    created = create_res.json()
    assert created["name"] == "첫째"
    assert created["preferred_theme"] is None
    assert created["avatar_url"] is None

    patch_res = await client.patch(
        f"/v1/profiles/{created['id']}",
        json={
            "preferred_theme": "  모험 ",
            "avatar_url": "   ",
        },
        headers=headers,
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["preferred_theme"] == "모험"
    assert patched["avatar_url"] is None


@pytest.mark.asyncio
async def test_profiles_reject_whitespace_only_name(
    client: AsyncClient,
    headers: dict,
):
    response = await client.post(
        "/v1/profiles",
        json={"name": "   ", "age_band": "5-7"},
        headers=headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["detail"] == "이름은 공백일 수 없습니다."


@pytest.mark.asyncio
async def test_settings_get_and_patch(
    client: AsyncClient,
    headers: dict,
):
    get_initial = await client.get("/v1/settings", headers=headers)
    assert get_initial.status_code == 200
    initial_data = get_initial.json()
    assert "language" in initial_data
    assert "daily_limit_minutes" in initial_data

    patch_res = await client.patch(
        "/v1/settings",
        json={
            "language": "en",
            "dark_mode": True,
            "screen_time_enabled": True,
            "daily_limit_minutes": 45,
        },
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "success"

    get_after = await client.get("/v1/settings", headers=headers)
    assert get_after.status_code == 200
    after_data = get_after.json()
    assert after_data["language"] == "en"
    assert after_data["dark_mode"] is True
    assert after_data["screen_time_enabled"] is True
    assert after_data["daily_limit_minutes"] == 45


@pytest.mark.asyncio
async def test_delete_me_removes_profiles_and_characters(
    client: AsyncClient,
    headers: dict,
    valid_character: dict,
    monkeypatch,
):
    from src.services.storage import storage_service

    deleted_prefixes: list[str] = []

    async def _spy(prefix):
        deleted_prefixes.append(prefix)
        return 0

    monkeypatch.setattr(storage_service, "delete_prefix", _spy)

    profile_res = await client.post(
        "/v1/profiles",
        json={"name": "삭제테스트", "age_band": "5-7"},
        headers=headers,
    )
    assert profile_res.status_code == 200

    character_res = await client.post(
        "/v1/characters",
        json=valid_character,
        headers=headers,
    )
    assert character_res.status_code in (200, 201)

    voice_profile_res = await client.post(
        "/v1/voice-profiles",
        json={
            "label": "엄마 목소리",
            "relationship": "mother",
            "sample_audio_url": "https://example.com/sample.m4a",
            "consented": True,
        },
        headers=headers,
    )
    assert voice_profile_res.status_code == 200

    delete_res = await client.delete("/v1/users/me", headers=headers)
    assert delete_res.status_code == 200
    assert delete_res.json()["status"] == "success"

    profiles_after = await client.get("/v1/profiles", headers=headers)
    assert profiles_after.status_code == 200
    assert profiles_after.json()["profiles"] == []

    characters_after = await client.get("/v1/characters", headers=headers)
    assert characters_after.status_code == 200
    assert characters_after.json()["characters"] == []

    voice_after = await client.get("/v1/voice-profiles", headers=headers)
    assert voice_after.status_code == 200
    assert voice_after.json()["profiles"] == []

    # 아동 사진/그림 원본(characters/{id}/) 스토리지 파기까지 수행됐는지(삭제권)
    assert any(p.startswith("characters/") for p in deleted_prefixes)


@pytest.mark.asyncio
async def test_library_patch_updates_title(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    job = Job(
        id="job-library-patch-1",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-library-patch-1",
        job_id=job.id,
        title="기존 제목",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover.png",
    )
    db_session.add(book)
    await db_session.commit()

    patch_res = await client.patch(
        f"/v1/library/{book.id}",
        json={"title": "  새 제목  "},
        headers=headers,
    )
    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["book_id"] == book.id
    assert body["title"] == "새 제목"


@pytest.mark.asyncio
async def test_free_plan_blocks_non_supported_style(
    client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)

    response = await client.post(
        "/v1/books",
        json={
            "topic": "스타일 제한 테스트",
            "language": "ko",
            "target_age": "5-7",
            "style": "3d",
            "page_count": 8,
        },
        headers=headers,
    )
    assert response.status_code == 402
    body = response.json()
    assert body["error"]["code"] == "PAYMENT_REQUIRED"
    assert "watercolor/cartoon" in body["detail"]


@pytest.mark.asyncio
async def test_free_plan_blocks_monthly_book_limit(
    client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)
    monkeypatch.setattr(settings, "free_plan_monthly_book_limit", 2)

    for idx in range(2):
        allowed = await client.post(
            "/v1/books",
            json={
                "topic": f"월간 한도 테스트 {idx}",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 8,
            },
            headers=headers,
        )
        assert allowed.status_code == 200

    blocked = await client.post(
        "/v1/books",
        json={
            "topic": "월간 한도 초과 테스트",
            "language": "ko",
            "target_age": "5-7",
            "style": "watercolor",
            "page_count": 8,
        },
        headers=headers,
    )
    assert blocked.status_code == 402
    body = blocked.json()
    assert body["error"]["code"] == "PAYMENT_REQUIRED"
    assert "월 2권" in body["detail"]


@pytest.mark.asyncio
async def test_paid_plan_bypasses_style_and_monthly_limit(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)
    monkeypatch.setattr(settings, "free_plan_monthly_book_limit", 2)

    now = utcnow()
    db_session.add(
        Subscription(
            user_key=headers["X-User-Key"],
            plan="basic",
            status="active",
            credits_per_month=10,
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
        )
    )
    db_session.add(
        Job(
            id="job-paid-limit-1",
            status="done",
            user_key=headers["X-User-Key"],
        )
    )
    db_session.add(
        Job(
            id="series_paid_limit_2",
            status="done",
            user_key=headers["X-User-Key"],
        )
    )
    await db_session.commit()

    response = await client.post(
        "/v1/books",
        json={
            "topic": "유료 플랜 스타일 허용",
            "language": "ko",
            "target_age": "5-7",
            "style": "3d",
            "page_count": 8,
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_cancelled_subscription_keeps_access_until_period_end(
    client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)
    monkeypatch.setattr(settings, "free_plan_monthly_book_limit", 2)

    subscribe_res = await client.post(
        "/v1/credits/subscribe",
        json={"plan": "basic"},
        headers=headers,
    )
    assert subscribe_res.status_code == 200

    cancel_res = await client.post("/v1/credits/cancel-subscription", headers=headers)
    assert cancel_res.status_code == 200

    status_res = await client.get("/v1/credits/status", headers=headers)
    assert status_res.status_code == 200
    subscription = status_res.json()["subscription"]
    assert subscription is not None
    assert subscription["status"] == "cancelled"
    assert subscription["plan"] == "basic"

    create_res = await client.post(
        "/v1/books",
        json={
            "topic": "취소 후 기간 내 유료 권한 유지",
            "language": "ko",
            "target_age": "5-7",
            "style": "3d",
            "page_count": 8,
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    assert create_res.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_subscription_plan_switch_prefers_latest_plan(
    client: AsyncClient,
    headers: dict,
):
    basic_res = await client.post(
        "/v1/credits/subscribe",
        json={"plan": "basic"},
        headers=headers,
    )
    assert basic_res.status_code == 200

    premium_res = await client.post(
        "/v1/credits/subscribe",
        json={"plan": "premium"},
        headers=headers,
    )
    assert premium_res.status_code == 200

    status_res = await client.get("/v1/credits/status", headers=headers)
    assert status_res.status_code == 200
    subscription = status_res.json()["subscription"]
    assert subscription is not None
    assert subscription["plan"] == "premium"
    assert subscription["status"] == "active"


@pytest.mark.asyncio
async def test_subscribe_same_plan_returns_already_subscribed_without_extra_credits(
    client: AsyncClient,
    headers: dict,
):
    before_balance = await client.get("/v1/credits/balance", headers=headers)
    assert before_balance.status_code == 200
    initial = before_balance.json()["credits"]

    first = await client.post(
        "/v1/credits/subscribe",
        json={"plan": "basic"},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "success"

    after_first_balance = await client.get("/v1/credits/balance", headers=headers)
    assert after_first_balance.status_code == 200
    after_first = after_first_balance.json()["credits"]
    assert after_first == initial + 10

    second = await client.post(
        "/v1/credits/subscribe",
        json={"plan": "basic"},
        headers=headers,
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["status"] == "already_subscribed"

    after_second_balance = await client.get("/v1/credits/balance", headers=headers)
    assert after_second_balance.status_code == 200
    assert after_second_balance.json()["credits"] == after_first


@pytest.mark.asyncio
async def test_free_plan_blocks_pdf_and_audio_features(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)

    job = Job(
        id="job-free-feature-1",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-free-feature-1",
        job_id=job.id,
        title="무료 기능 제한 테스트",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover.png",
    )
    db_session.add(book)
    await db_session.flush()

    db_session.add(
        Page(
            book_id=book.id,
            page_number=1,
            text="첫 페이지",
            image_url="https://example.com/page-1.png",
            image_prompt="prompt",
        )
    )
    await db_session.commit()

    pdf_res = await client.get(f"/v1/books/{book.id}/pdf", headers=headers)
    assert pdf_res.status_code == 402
    assert pdf_res.json()["error"]["code"] == "PAYMENT_REQUIRED"

    audio_res = await client.post(f"/v1/books/{book.id}/audio", headers=headers)
    assert audio_res.status_code == 402
    assert audio_res.json()["error"]["code"] == "PAYMENT_REQUIRED"

    page_audio_res = await client.get(
        f"/v1/books/{book.id}/pages/1/audio",
        params={"language": "ko"},
        headers=headers,
    )
    assert page_audio_res.status_code == 402
    assert page_audio_res.json()["error"]["code"] == "PAYMENT_REQUIRED"


@pytest.mark.asyncio
async def test_free_plan_allows_page_audio_for_nonreader_3_5(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    # 글 못 읽는 저연령(3-5)은 낭독이 유일한 소비 수단 → 무료 플랜도 신규 합성 허용.
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)

    async def _tts(*args, **kwargs):
        return b"audio-bytes"

    async def _upload(*args, **kwargs):
        return "https://cdn.example.com/p1-ko.mp3"

    monkeypatch.setattr("src.routers.books.tts_service.synthesize_page", _tts)
    monkeypatch.setattr("src.routers.books.storage_service.upload_bytes", _upload)

    job = Job(id="job-35-audio", status="done", user_key=headers["X-User-Key"])
    db_session.add(job)
    await db_session.flush()
    book = Book(
        id="book-35-audio", job_id=job.id, title="저연령", language="ko",
        target_age="3-5", style="watercolor", user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/c.png",
    )
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        Page(book_id=book.id, page_number=1, text="첫 페이지",
             image_url="https://example.com/p1.png", image_prompt="p")
    )
    await db_session.commit()

    res = await client.get(
        f"/v1/books/{book.id}/pages/1/audio",
        params={"language": "ko"}, headers=headers,
    )
    assert res.status_code == 200, res.text  # 5-7과 달리 402 아님
    assert res.json()["audio_url"].endswith(".mp3")


@pytest.mark.asyncio
async def test_free_plan_serves_cached_page_audio(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    # 이미 생성된 오디오는 무료 플랜(5-7)도 반환 — 결제벽으로 기존 낭독까지 막지 않는다.
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)

    job = Job(id="job-cached-audio", status="done", user_key=headers["X-User-Key"])
    db_session.add(job)
    await db_session.flush()
    book = Book(
        id="book-cached-audio", job_id=job.id, title="캐시", language="ko",
        target_age="5-7", style="watercolor", user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/c.png",
    )
    db_session.add(book)
    await db_session.flush()
    db_session.add(
        Page(book_id=book.id, page_number=1, text="첫 페이지",
             image_url="https://example.com/p1.png", image_prompt="p",
             audio_url="https://cdn.example.com/cached-ko.mp3")
    )
    await db_session.commit()

    res = await client.get(
        f"/v1/books/{book.id}/pages/1/audio",
        params={"language": "ko"}, headers=headers,
    )
    assert res.status_code == 200, res.text  # 캐시 → 차단 안 됨
    assert res.json()["audio_url"] == "https://cdn.example.com/cached-ko.mp3"


@pytest.mark.asyncio
async def test_free_plan_blocks_series_non_supported_style(
    client: AsyncClient,
    headers: dict,
    valid_character: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)

    character_res = await client.post(
        "/v1/characters",
        json=valid_character,
        headers=headers,
    )
    assert character_res.status_code in (200, 201)
    character_id = character_res.json()["character_id"]

    response = await client.post(
        "/v1/books/series",
        json={
            "character_id": character_id,
            "topic": "시리즈 스타일 제한 테스트",
            "style": "3d",
            "target_age": "5-7",
            "language": "ko",
            "page_count": 8,
        },
        headers=headers,
    )
    assert response.status_code == 402
    body = response.json()
    assert body["error"]["code"] == "PAYMENT_REQUIRED"
    assert "watercolor/cartoon" in body["detail"]


@pytest.mark.asyncio
async def test_pod_order_create_and_get(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    job = Job(
        id="job-pod-order-1",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-pod-order-1",
        job_id=job.id,
        title="인쇄 테스트 책",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover.png",
    )
    db_session.add(book)
    await db_session.commit()

    create_res = await client.post(
        "/v1/pod/orders",
        json={
            "book_id": book.id,
            "quantity": 2,
            "shipping_address": {
                "name": "홍길동",
                "line1": "서울시 강남구 테스트로 1",
                "postal_code": "12345",
                "country": "KR",
                "phone": "010-1111-2222",
            },
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    created = create_res.json()
    assert created["status"] == "created"
    assert created["provider"] == "printful"
    assert created["total_price"] == (18000 * 2) + 3000

    order_id = created["order_id"]
    get_res = await client.get(f"/v1/pod/orders/{order_id}", headers=headers)
    assert get_res.status_code == 200
    payload = get_res.json()
    assert payload["order_id"] == order_id
    assert payload["book_id"] == book.id
    assert payload["quantity"] == 2
    assert payload["status"] == "created"


@pytest.mark.asyncio
async def test_pod_order_strict_mode_requires_provider_config(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "pod_mode", "strict")
    monkeypatch.setattr(settings, "printful_api_key", None)
    monkeypatch.setattr(settings, "printful_sync_variant_id", None)

    job = Job(
        id="job-pod-strict-1",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-pod-strict-1",
        job_id=job.id,
        title="엄격 주문 테스트",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover.png",
    )
    db_session.add(book)
    await db_session.commit()

    response = await client.post(
        "/v1/pod/orders",
        json={
            "book_id": book.id,
            "quantity": 1,
            "shipping_address": {
                "name": "홍길동",
                "line1": "서울시 테스트 1",
                "postal_code": "12345",
                "country": "KR",
            },
        },
        headers=headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "POD 연동 설정이 필요합니다." in body["detail"]


@pytest.mark.asyncio
async def test_pod_order_status_sync_updates_tracking(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.routers import pod as pod_router
    from src.services.pod_provider import PodCreateResult, PodStatusResult

    async def _mock_create_order(**kwargs):
        return PodCreateResult(
            status="draft",
            provider="printful",
            provider_order_id="pf-order-100",
            tracking_number=None,
            total_price=27000,
            currency="KRW",
            sync_source="printful",
            raw={"status": "draft"},
        )

    async def _mock_sync_order_status(**kwargs):
        return PodStatusResult(
            status="shipped",
            tracking_number="TRACK-123",
            sync_source="printful",
            raw={"status": "shipped"},
        )

    monkeypatch.setattr(pod_router.pod_provider_service, "create_order", _mock_create_order)
    monkeypatch.setattr(
        pod_router.pod_provider_service,
        "sync_order_status",
        _mock_sync_order_status,
    )

    job = Job(
        id="job-pod-sync-1",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-pod-sync-1",
        job_id=job.id,
        title="주문 동기화 테스트",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover.png",
    )
    db_session.add(book)
    await db_session.commit()

    create_res = await client.post(
        "/v1/pod/orders",
        json={
            "book_id": book.id,
            "quantity": 1,
            "shipping_address": {
                "name": "홍길동",
                "line1": "서울시 테스트 2",
                "postal_code": "54321",
                "country": "KR",
            },
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    created = create_res.json()
    assert created["status"] == "draft"
    assert created["provider_order_id"] == "pf-order-100"

    get_res = await client.get(f"/v1/pod/orders/{created['order_id']}", headers=headers)
    assert get_res.status_code == 200
    detail = get_res.json()
    assert detail["status"] == "shipped"
    assert detail["tracking_number"] == "TRACK-123"
    assert detail["sync_source"] == "printful"


@pytest.mark.asyncio
async def test_pod_order_validates_and_normalizes_shipping_address(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    job = Job(
        id="job-pod-address-1",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-pod-address-1",
        job_id=job.id,
        title="주소 검증 테스트 책",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover.png",
    )
    db_session.add(book)
    await db_session.commit()

    invalid_country = await client.post(
        "/v1/pod/orders",
        json={
            "book_id": book.id,
            "quantity": 1,
            "shipping_address": {
                "name": "홍길동",
                "line1": "서울시 테스트 3",
                "postal_code": "12345",
                "country": "KOR",
            },
        },
        headers=headers,
    )
    assert invalid_country.status_code == 422

    valid = await client.post(
        "/v1/pod/orders",
        json={
            "book_id": book.id,
            "quantity": 1,
            "shipping_address": {
                "name": "  홍길동  ",
                "line1": "  서울시 테스트 3  ",
                "postal_code": " 12345 ",
                "country": "kr",
                "phone": " 010-2222-3333 ",
            },
        },
        headers=headers,
    )
    assert valid.status_code == 200
    payload = valid.json()
    order_id = payload["order_id"]

    order_result = await db_session.execute(
        select(PodOrder).where(PodOrder.id == order_id)
    )
    saved = order_result.scalar_one()
    assert saved.shipping_address["name"] == "홍길동"
    assert saved.shipping_address["line1"] == "서울시 테스트 3"
    assert saved.shipping_address["postal_code"] == "12345"
    assert saved.shipping_address["country"] == "KR"
    assert saved.shipping_address["phone"] == "010-2222-3333"


@pytest.mark.asyncio
async def test_pronunciation_evaluate_scores_by_similarity(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    db_session.add_all(make_book_rows([("book-pron-1", headers["X-User-Key"])]))
    await db_session.commit()
    expected = "토끼가 숲 속으로 천천히 걸어갔어요"

    high_res = await client.post(
        "/v1/pronunciation/evaluate",
        json={
            "book_id": "book-pron-1",
            "page_number": 1,
            "transcript": "토끼가 숲 속으로 천천히 걸어갔어요",
            "expected_text": expected,
        },
        headers=headers,
    )
    assert high_res.status_code == 200
    high_payload = high_res.json()
    assert high_payload["status"] == "success"
    assert high_payload["score"] >= 90

    low_res = await client.post(
        "/v1/pronunciation/evaluate",
        json={
            "book_id": "book-pron-1",
            "page_number": 1,
            "transcript": "자동차가 빠르게 지나갔어요",
            "expected_text": expected,
        },
        headers=headers,
    )
    assert low_res.status_code == 200
    low_payload = low_res.json()
    assert low_payload["status"] == "success"
    assert low_payload["score"] < 60


@pytest.mark.asyncio
async def test_pronunciation_evaluate_audio_uses_stt_transcript(
    client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
):
    db_session.add_all(make_book_rows([("book-pron-audio", headers["X-User-Key"])]))
    await db_session.commit()
    from src.routers import pronunciation as pronunciation_router

    async def _mock_transcribe_audio(*args, **kwargs):
        return "토끼가 숲 속으로 천천히 걸어갔어요"

    monkeypatch.setattr(
        pronunciation_router.stt_service,
        "transcribe_audio",
        _mock_transcribe_audio,
    )

    response = await client.post(
        "/v1/pronunciation/evaluate-audio",
        files={"audio_file": ("sample.m4a", b"audio-bytes", "audio/mp4")},
        data={
            "book_id": "book-pron-audio",
            "page_number": "1",
            "expected_text": "토끼가 숲 속으로 천천히 걸어갔어요",
            "language": "ko",
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["transcript"] == "토끼가 숲 속으로 천천히 걸어갔어요"
    assert payload["score"] >= 90


@pytest.mark.asyncio
async def test_branch_story_initialize_graph_and_choose(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    job = Job(
        id="job-branch-1",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-branch-1",
        job_id=job.id,
        title="분기 테스트 책",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover.png",
    )
    db_session.add(book)
    await db_session.commit()

    init_res = await client.post(
        f"/v1/branch/books/{book.id}/initialize",
        json={
            "nodes": [
                {
                    "node_key": "start",
                    "page_number": 1,
                    "text": "토끼는 갈림길 앞에 섰어요.",
                    "options": [
                        {"option_text": "왼쪽 길", "to_node_key": "left_end"},
                        {"option_text": "오른쪽 길", "to_node_key": "right_end"},
                    ],
                },
                {
                    "node_key": "left_end",
                    "page_number": 2,
                    "text": "왼쪽 길에서는 친구를 만났어요.",
                    "options": [],
                },
                {
                    "node_key": "right_end",
                    "page_number": 2,
                    "text": "오른쪽 길에서는 보물을 찾았어요.",
                    "options": [],
                },
            ],
            "overwrite": True,
        },
        headers=headers,
    )
    assert init_res.status_code == 200
    init_payload = init_res.json()
    assert init_payload["status"] == "success"
    assert init_payload["node_count"] == 3
    assert init_payload["edge_count"] == 2

    graph_res = await client.get(f"/v1/branch/books/{book.id}/graph", headers=headers)
    assert graph_res.status_code == 200
    graph_payload = graph_res.json()
    assert graph_payload["node_count"] == 3
    assert graph_payload["edge_count"] == 2

    choose_res = await client.post(
        f"/v1/branch/books/{book.id}/choose",
        json={
            "current_node_key": "start",
            "option_text": "왼쪽 길",
        },
        headers=headers,
    )
    assert choose_res.status_code == 200
    choose_payload = choose_res.json()
    assert choose_payload["status"] == "ok"
    assert choose_payload["selected_option"] == "왼쪽 길"
    assert choose_payload["next_node"]["node_key"] == "left_end"
    assert choose_payload["is_ending"] is True


@pytest.mark.asyncio
async def test_branch_story_rejects_duplicate_options_and_trims_inputs(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    job = Job(
        id="job-branch-2",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-branch-2",
        job_id=job.id,
        title="분기 테스트 책 2",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover2.png",
    )
    db_session.add(book)
    await db_session.commit()

    duplicate_option_res = await client.post(
        f"/v1/branch/books/{book.id}/initialize",
        json={
            "nodes": [
                {
                    "node_key": " start ",
                    "page_number": 1,
                    "text": "갈림길이에요",
                    "options": [
                        {"option_text": " 왼쪽 길 ", "to_node_key": " left_end "},
                        {"option_text": "왼쪽 길", "to_node_key": "left_end"},
                    ],
                },
                {
                    "node_key": " left_end ",
                    "page_number": 2,
                    "text": "끝",
                    "options": [],
                },
            ],
            "overwrite": True,
        },
        headers=headers,
    )
    assert duplicate_option_res.status_code == 400

    init_res = await client.post(
        f"/v1/branch/books/{book.id}/initialize",
        json={
            "nodes": [
                {
                    "node_key": " start ",
                    "page_number": 1,
                    "text": "갈림길이에요",
                    "options": [
                        {"option_text": " 왼쪽 길 ", "to_node_key": " left_end "},
                        {"option_text": "오른쪽 길", "to_node_key": "right_end"},
                    ],
                },
                {
                    "node_key": " left_end ",
                    "page_number": 2,
                    "text": "왼쪽 결말",
                    "options": [],
                },
                {
                    "node_key": "right_end",
                    "page_number": 2,
                    "text": "오른쪽 결말",
                    "options": [],
                },
            ],
            "overwrite": True,
        },
        headers=headers,
    )
    assert init_res.status_code == 200

    graph_res = await client.get(f"/v1/branch/books/{book.id}/graph", headers=headers)
    assert graph_res.status_code == 200
    node_keys = {node["node_key"] for node in graph_res.json()["nodes"]}
    assert "start" in node_keys
    assert "left_end" in node_keys

    choose_res = await client.post(
        f"/v1/branch/books/{book.id}/choose",
        json={
            "current_node_key": " start ",
            "option_text": " 왼쪽 길 ",
        },
        headers=headers,
    )
    assert choose_res.status_code == 200
    choose_payload = choose_res.json()
    assert choose_payload["selected_option"] == "왼쪽 길"
    assert choose_payload["next_node"]["node_key"] == "left_end"


@pytest.mark.asyncio
async def test_branch_story_choose_rejects_whitespace_option_inputs(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    job = Job(
        id="job-branch-3",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-branch-3",
        job_id=job.id,
        title="분기 테스트 책 3",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        cover_image_url="https://example.com/cover3.png",
    )
    db_session.add(book)
    await db_session.commit()

    init_res = await client.post(
        f"/v1/branch/books/{book.id}/initialize",
        json={
            "nodes": [
                {
                    "node_key": "start",
                    "page_number": 1,
                    "text": "갈림길이에요",
                    "options": [
                        {"option_text": "왼쪽 길", "to_node_key": "left_end"},
                    ],
                },
                {
                    "node_key": "left_end",
                    "page_number": 2,
                    "text": "결말",
                    "options": [],
                },
            ],
            "overwrite": True,
        },
        headers=headers,
    )
    assert init_res.status_code == 200

    whitespace_option = await client.post(
        f"/v1/branch/books/{book.id}/choose",
        json={
            "current_node_key": "start",
            "option_text": "   ",
        },
        headers=headers,
    )
    assert whitespace_option.status_code == 400
    assert whitespace_option.json()["detail"] == "option_text는 공백일 수 없습니다."

    whitespace_to_node = await client.post(
        f"/v1/branch/books/{book.id}/choose",
        json={
            "current_node_key": "start",
            "to_node_key": "   ",
        },
        headers=headers,
    )
    assert whitespace_to_node.status_code == 400
    assert whitespace_to_node.json()["detail"] == "to_node_key는 공백일 수 없습니다."


@pytest.mark.asyncio
async def test_streak_report_weekly(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    job = Job(
        id="job-streak-report-1",
        status="done",
        user_key=headers["X-User-Key"],
    )
    db_session.add(job)
    await db_session.flush()

    book = Book(
        id="book-streak-report-1",
        job_id=job.id,
        title="리포트 테스트 책",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=headers["X-User-Key"],
        theme="모험",
        cover_image_url="https://example.com/cover.png",
    )
    db_session.add(book)
    await db_session.commit()

    first_read = await client.post(
        "/v1/streak/read",
        json={
            "book_id": book.id,
            "reading_time": 600,
            "completed": True,
        },
        headers=headers,
    )
    assert first_read.status_code == 200

    report_res = await client.get(
        "/v1/streak/report",
        params={"period": "weekly"},
        headers=headers,
    )
    assert report_res.status_code == 200
    payload = report_res.json()
    assert payload["period"] == "weekly"
    assert payload["period_days"] == 7
    assert payload["total_books_read"] >= 1
    assert payload["total_sessions"] >= 1
    assert payload["total_reading_minutes"] >= 10
    assert payload["preferred_theme"] == "모험"
    assert len(payload["daily_breakdown"]) == 7


@pytest.mark.asyncio
async def test_voice_profiles_crud_and_revoke(
    client: AsyncClient,
    headers: dict,
):
    create_res = await client.post(
        "/v1/voice-profiles",
        json={
            "label": "할머니",
            "relationship": "grandmother",
            "sample_audio_url": "https://example.com/grandma.m4a",
            "provider_voice_id": "voice_abc",
            "consented": True,
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    profile = create_res.json()
    assert profile["label"] == "할머니"
    assert profile["consented"] is True
    assert profile["active"] is True

    profile_id = profile["id"]

    list_res = await client.get("/v1/voice-profiles", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()["profiles"]) == 1

    patch_res = await client.patch(
        f"/v1/voice-profiles/{profile_id}",
        json={
            "label": "할머니 목소리",
            "consented": False,
        },
        headers=headers,
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["label"] == "할머니 목소리"
    assert patched["consented"] is False
    assert patched["active"] is False
    assert patched["provider_voice_id"] is None

    revoke_res = await client.post(
        f"/v1/voice-profiles/{profile_id}/revoke-consent",
        headers=headers,
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "success"

    delete_res = await client.delete(
        f"/v1/voice-profiles/{profile_id}",
        headers=headers,
    )
    assert delete_res.status_code == 200

    final_list_res = await client.get("/v1/voice-profiles", headers=headers)
    assert final_list_res.status_code == 200
    assert final_list_res.json()["profiles"] == []


@pytest.mark.asyncio
async def test_voice_profiles_reject_whitespace_label_and_require_consent_for_activation(
    client: AsyncClient,
    headers: dict,
):
    invalid_create = await client.post(
        "/v1/voice-profiles",
        json={
            "label": "   ",
            "relationship": "mother",
            "sample_audio_url": "https://example.com/sample.m4a",
            "consented": True,
        },
        headers=headers,
    )
    assert invalid_create.status_code == 400
    invalid_body = invalid_create.json()
    assert invalid_body["error"]["code"] == "VALIDATION_ERROR"
    assert invalid_body["detail"] == "라벨은 공백일 수 없습니다."

    create_res = await client.post(
        "/v1/voice-profiles",
        json={
            "label": "엄마",
            "relationship": "mother",
            "sample_audio_url": "https://example.com/sample.m4a",
            "consented": True,
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    profile_id = create_res.json()["id"]

    revoke_res = await client.patch(
        f"/v1/voice-profiles/{profile_id}",
        json={"consented": False},
        headers=headers,
    )
    assert revoke_res.status_code == 200

    activate_without_consent = await client.patch(
        f"/v1/voice-profiles/{profile_id}",
        json={"active": True},
        headers=headers,
    )
    assert activate_without_consent.status_code == 400
    activate_body = activate_without_consent.json()
    assert activate_body["error"]["code"] == "VALIDATION_ERROR"
    assert activate_body["detail"] == "동의가 없는 음성 프로필은 활성화할 수 없습니다."


@pytest.mark.asyncio
async def test_voice_profiles_reject_invalid_sample_audio_url(
    client: AsyncClient,
    headers: dict,
):
    response = await client.post(
        "/v1/voice-profiles",
        json={
            "label": "엄마",
            "relationship": "mother",
            "sample_audio_url": "invalid-url",
            "consented": True,
        },
        headers=headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["detail"] == "유효한 샘플 오디오 URL이 필요합니다."


@pytest.mark.asyncio
async def test_voice_sample_upload_returns_url(
    client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.routers import voice_profiles as voice_profiles_router

    async def _mock_upload_bytes(*args, **kwargs):
        return "https://cdn.example.com/voice-samples/sample-1.m4a"

    monkeypatch.setattr(
        voice_profiles_router.storage_service,
        "upload_bytes",
        _mock_upload_bytes,
    )

    upload_res = await client.post(
        "/v1/voice-profiles/upload-sample",
        files={"sample": ("sample.m4a", b"audio-bytes", "audio/mp4")},
        headers=headers,
    )
    assert upload_res.status_code == 200
    payload = upload_res.json()
    assert payload["sample_audio_url"] == "https://cdn.example.com/voice-samples/sample-1.m4a"
    assert payload["content_type"] == "audio/mp4"
    assert payload["size_bytes"] == len(b"audio-bytes")


@pytest.mark.asyncio
async def test_character_from_drawing_creates_character_and_sheet(
    client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.routers import characters as characters_router

    async def _mock_create_character_from_drawing(*args, **kwargs):
        return {
            "name": kwargs.get("user_name") or "그림 친구",
            "master_description": "cute character based on child drawing",
            "appearance": {
                "hair_color": "갈색",
                "hair_style": "짧은 머리",
                "eye_color": "검은색",
                "skin_tone": "밝음",
                "distinctive_features": ["큰 미소"],
            },
            "clothing": {
                "top": "파란 티셔츠",
                "bottom": "노란 바지",
                "accessories": ["별 배지"],
            },
            "personality_traits": ["밝은", "용감한"],
            "visual_style_notes": "storybook_crayon style",
            "sheet_scene_prompts": [
                "front pose",
                "side walk pose",
                "happy jump pose",
            ],
        }

    async def _mock_upload_bytes(*args, **kwargs):
        return "https://cdn.example.com/characters/source-drawing.png"

    async def _mock_generate_image(prompt):
        return f"https://images.example.com/sheet-{prompt.page}.png"

    monkeypatch.setattr(
        characters_router.photo_character_service,
        "create_character_from_drawing",
        _mock_create_character_from_drawing,
    )
    monkeypatch.setattr(
        characters_router.storage_service,
        "upload_bytes",
        _mock_upload_bytes,
    )
    monkeypatch.setattr(characters_router, "generate_image", _mock_generate_image)

    create_res = await client.post(
        "/v1/characters/from-drawing",
        files={"drawing": ("kid-drawing.png", b"pngdata", "image/png")},
        data={
            "name": "그림이",
            "style": "storybook_crayon",
            "generate_sheet": "true",
        },
        headers=headers,
    )
    assert create_res.status_code == 200
    payload = create_res.json()
    assert payload["name"] == "그림이"
    assert payload["source_image_url"] == "https://cdn.example.com/characters/source-drawing.png"
    assert len(payload["character_sheet_urls"]) == 3
    assert payload["character_sheet_urls"][0].startswith("https://images.example.com/")

    list_res = await client.get("/v1/characters", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()["characters"]) == 1


@pytest.mark.asyncio
async def test_profile_scoped_library_and_streak(
    client: AsyncClient,
    headers: dict,
    db_session: AsyncSession,
):
    user_key = headers["X-User-Key"]
    profile_a = ChildProfile(
        id="profile_scope_a",
        user_key=user_key,
        name="첫째",
        age_band="5-7",
        is_default=True,
    )
    profile_b = ChildProfile(
        id="profile_scope_b",
        user_key=user_key,
        name="둘째",
        age_band="7-9",
        is_default=False,
    )
    db_session.add_all([profile_a, profile_b])
    await db_session.flush()

    job_a = Job(id="job-profile-a", status="done", user_key=user_key, profile_id=profile_a.id)
    job_b = Job(id="job-profile-b", status="done", user_key=user_key, profile_id=profile_b.id)
    db_session.add_all([job_a, job_b])
    await db_session.flush()

    book_a = Book(
        id="book-profile-a",
        job_id=job_a.id,
        title="첫째 책",
        language="ko",
        target_age="5-7",
        style="watercolor",
        user_key=user_key,
        profile_id=profile_a.id,
        cover_image_url="https://example.com/a.png",
    )
    book_b = Book(
        id="book-profile-b",
        job_id=job_b.id,
        title="둘째 책",
        language="ko",
        target_age="7-9",
        style="cartoon",
        user_key=user_key,
        profile_id=profile_b.id,
        cover_image_url="https://example.com/b.png",
    )
    db_session.add_all([book_a, book_b])
    await db_session.commit()

    headers_a = {**headers, "X-Profile-Id": profile_a.id}
    headers_b = {**headers, "X-Profile-Id": profile_b.id}

    lib_a = await client.get("/v1/library", headers=headers_a)
    assert lib_a.status_code == 200
    books_a = lib_a.json()["books"]
    assert len(books_a) == 1
    assert books_a[0]["book_id"] == "book-profile-a"

    lib_b = await client.get("/v1/library", headers=headers_b)
    assert lib_b.status_code == 200
    books_b = lib_b.json()["books"]
    assert len(books_b) == 1
    assert books_b[0]["book_id"] == "book-profile-b"

    read_a = await client.post(
        "/v1/streak/read",
        json={"book_id": "book-profile-a", "reading_time": 300, "completed": True},
        headers=headers_a,
    )
    assert read_a.status_code == 200

    read_b = await client.post(
        "/v1/streak/read",
        json={"book_id": "book-profile-b", "reading_time": 120, "completed": False},
        headers=headers_b,
    )
    assert read_b.status_code == 200

    history_a = await client.get("/v1/streak/history", headers=headers_a)
    assert history_a.status_code == 200
    assert len(history_a.json()["history"]) == 1
    assert history_a.json()["history"][0]["completed_count"] == 1

    history_b = await client.get("/v1/streak/history", headers=headers_b)
    assert history_b.status_code == 200
    assert len(history_b.json()["history"]) == 1
    assert history_b.json()["history"][0]["completed_count"] == 0
