"""
Error response format tests
에러 응답 표준화 포맷 검증
"""

import pytest
from datetime import datetime
from httpx import AsyncClient
from unittest.mock import AsyncMock
from src.core.exceptions import _http_error_code, _normalize_http_detail


class TestErrorResponseFormat:
    """Standardized error envelope tests."""

    @pytest.mark.asyncio
    async def test_http_exception_has_standard_envelope(self, client: AsyncClient):
        """Plain HTTPException responses should include detail + error + request_id."""
        response = await client.get(
            "/v1/library",
            headers={"X-User-Key": "short"},
        )

        assert response.status_code == 400
        body = response.json()

        assert "detail" in body
        assert "error" in body
        assert body["error"]["code"] == "BAD_REQUEST"
        assert body["error"]["message"] == body["detail"]
        assert "request_id" in body

    @pytest.mark.asyncio
    async def test_validation_error_has_standard_envelope(
        self, client: AsyncClient, headers: dict
    ):
        """Request validation errors should provide structured details."""
        response = await client.post(
            "/v1/books",
            json={"invalid": "payload"},
            headers=headers,
        )

        assert response.status_code == 422
        body = response.json()

        assert isinstance(body.get("detail"), list)
        assert "error" in body
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"] == body["detail"]
        assert "request_id" in body

    @pytest.mark.asyncio
    async def test_api_error_includes_request_id(self, client: AsyncClient, headers: dict):
        """APIError responses should include request ID for tracing."""
        response = await client.get("/v1/books/nonexistent-job-id", headers=headers)

        assert response.status_code == 404
        body = response.json()

        assert body["error"]["code"] == "NOT_FOUND"
        assert body["detail"] == body["error"]["message"]
        assert isinstance(body.get("request_id"), str)
        assert body["request_id"]

    @pytest.mark.asyncio
    async def test_http_detail_dict_preserves_explicit_error_code(
        self,
        client: AsyncClient,
        headers: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """HTTPException detail dict with 'error' should preserve that code."""
        from src.routers import books as books_router

        monkeypatch.setattr(books_router.settings, "daily_job_limit_per_user", 0)
        # naive UTC(프로젝트 컨벤션) — 일일 한도는 KST 윈도우(utils.utcnow, naive)로 계산되므로
        # retry_after 계산이 naive-naive로 일관되게 한다(tz-aware로 두면 혼합 연산 오류).
        fixed_now = datetime(2026, 2, 18, 12, 0, 0, 500_000)
        monkeypatch.setattr(books_router, "utcnow", lambda: fixed_now)

        response = await client.post(
            "/v1/books",
            json={
                "topic": "테스트 주제",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )

        assert response.status_code == 429
        body = response.json()
        assert body["error"]["code"] == "daily_limit_exceeded"
        assert body["error"]["message"] == body["detail"]
        assert body["error"]["details"]["limit"] == 0
        # KST 자정까지 남은 시간: fixed_now=Feb18 12:00Z(=21:00 KST) → KST 자정까지 3시간.
        assert body["error"]["details"]["retry_after"] == 10_800
        assert response.headers.get("Retry-After") == "10800"

    @pytest.mark.asyncio
    async def test_http_exception_preserves_retry_after_header(
        self,
        client: AsyncClient,
        headers: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Standardized HTTPException responses should preserve response headers."""
        from src.core import rate_limit
        from src.core.config import settings

        monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
        monkeypatch.setattr(
            rate_limit.rate_limiter,
            "is_allowed",
            AsyncMock(return_value=(False, 0)),
        )

        response = await client.get("/v1/library", headers=headers)

        assert response.status_code == 429
        assert response.headers.get("Retry-After") == str(settings.rate_limit_window)

    @pytest.mark.asyncio
    async def test_system_overloaded_preserves_retry_after_header(
        self,
        client: AsyncClient,
        headers: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Overload guardrail should expose Retry-After on standardized response."""
        from src.routers import books as books_router

        monkeypatch.setattr(books_router.settings, "daily_job_limit_per_user", 999_999)
        monkeypatch.setattr(books_router.settings, "max_pending_jobs", 0)

        response = await client.post(
            "/v1/books",
            json={
                "topic": "테스트 주제",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )

        assert response.status_code == 503
        body = response.json()
        assert body["error"]["code"] == "system_overloaded"
        assert body["error"]["details"]["retry_after"] == 60
        assert response.headers.get("Retry-After") == "60"

    @pytest.mark.asyncio
    async def test_internal_server_error_uses_standard_api_error_envelope(
        self,
        client: AsyncClient,
        headers: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Handled server failures should return INTERNAL_ERROR with request ID."""
        from src.routers import credits as credits_router

        async def _raise_subscription_error(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            credits_router.credits_service,
            "create_subscription",
            _raise_subscription_error,
        )

        response = await client.post(
            "/v1/credits/subscribe",
            json={"plan": "basic"},
            headers=headers,
        )

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["detail"] == body["error"]["message"]
        assert body["detail"] == "구독 처리에 실패했습니다. 잠시 후 다시 시도해주세요."
        assert isinstance(body.get("request_id"), str)
        assert body["request_id"]

    @pytest.mark.asyncio
    async def test_character_photo_invalid_content_type_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """Invalid photo uploads should return standardized VALIDATION_ERROR."""
        response = await client.post(
            "/v1/characters/from-photo",
            files={"photo": ("not-image.txt", b"plain text", "text/plain")},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "이미지 파일만 업로드 가능합니다."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_character_photo_oversized_file_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """Oversized image uploads should return standardized VALIDATION_ERROR."""
        oversized = b"0" * (10 * 1024 * 1024 + 1)
        response = await client.post(
            "/v1/characters/from-photo",
            files={"photo": ("large.jpg", oversized, "image/jpeg")},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "파일 크기는 10MB 이하여야 합니다."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_character_drawing_invalid_content_type_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        response = await client.post(
            "/v1/characters/from-drawing",
            files={"drawing": ("not-image.txt", b"plain text", "text/plain")},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "이미지 파일만 업로드 가능합니다."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_character_drawing_oversized_file_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        oversized = b"0" * (10 * 1024 * 1024 + 1)
        response = await client.post(
            "/v1/characters/from-drawing",
            files={"drawing": ("large.png", oversized, "image/png")},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "파일 크기는 10MB 이하여야 합니다."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_voice_sample_upload_invalid_type_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        response = await client.post(
            "/v1/voice-profiles/upload-sample",
            files={"sample": ("not-audio.txt", b"text", "text/plain")},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "오디오 파일만 업로드 가능합니다."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_voice_sample_upload_oversized_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        oversized = b"1" * (15 * 1024 * 1024 + 1)
        response = await client.post(
            "/v1/voice-profiles/upload-sample",
            files={"sample": ("huge.m4a", oversized, "audio/mp4")},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "샘플 오디오는 15MB 이하여야 합니다."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_pronunciation_audio_invalid_type_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        response = await client.post(
            "/v1/pronunciation/evaluate-audio",
            files={"audio_file": ("not-audio.txt", b"text", "text/plain")},
            data={"expected_text": "토끼가 걸어가요", "language": "ko"},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "오디오 파일만 업로드 가능합니다."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_pronunciation_audio_oversized_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        oversized = b"2" * (15 * 1024 * 1024 + 1)
        response = await client.post(
            "/v1/pronunciation/evaluate-audio",
            files={"audio_file": ("large.m4a", oversized, "audio/mp4")},
            data={"expected_text": "토끼가 걸어가요", "language": "ko"},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "발음 평가 오디오는 15MB 이하여야 합니다."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_pod_order_invalid_country_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        response = await client.post(
            "/v1/pod/orders",
            json={
                "book_id": "book-any",
                "quantity": 1,
                "shipping_address": {
                    "name": "홍길동",
                    "line1": "서울시 테스트",
                    "postal_code": "12345",
                    "country": "KOR",
                },
            },
            headers=headers,
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert isinstance(body["detail"], list)
        assert body["error"]["details"] == body["detail"]

    @pytest.mark.asyncio
    async def test_profile_unset_default_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        create_profile = await client.post(
            "/v1/profiles",
            json={"name": "첫째", "age_band": "5-7"},
            headers=headers,
        )
        assert create_profile.status_code == 200
        profile_id = create_profile.json()["id"]

        response = await client.patch(
            f"/v1/profiles/{profile_id}",
            json={"is_default": False},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "기본 프로필은 직접 해제할 수 없습니다. 다른 프로필을 기본으로 지정하세요."
        assert body["error"]["message"] == body["detail"]

    @pytest.mark.asyncio
    async def test_regenerate_before_completion_uses_validation_error(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """Regeneration before completion should use standardized VALIDATION_ERROR."""
        create_response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        job_id = create_response.json()["job_id"]

        response = await client.post(
            f"/v1/books/{job_id}/pages/1/regenerate",
            # M12: text 모드는 feedback 필수(그렇지 않으면 요청 검증 422). 이 테스트의
            # 의도는 '생성 미완료 시 400'이므로 유효한 feedback을 넣어 도메인 체크에 도달시킨다.
            json={"regenerate_target": "text", "feedback": "더 밝게 써줘"},
            headers=headers,
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["detail"] == "Book generation not complete"
        assert body["error"]["message"] == body["detail"]


class TestHttpDetailNormalization:
    def test_normalize_http_detail_ignores_non_code_error_string(self):
        message, details, explicit_code = _normalize_http_detail(
            {
                "error": "internal server error",
                "message": "처리 중 오류가 발생했습니다.",
            }
        )

        assert explicit_code is None
        assert message == "처리 중 오류가 발생했습니다."
        assert details is None

    def test_normalize_http_detail_reads_nested_error_code(self):
        message, details, explicit_code = _normalize_http_detail(
            {
                "error": {"code": "system_overloaded"},
                "message": "요청이 많습니다.",
                "retry_after": 60,
            }
        )

        assert explicit_code == "system_overloaded"
        assert message == "요청이 많습니다."
        assert details == {"retry_after": 60}


class TestHttpStatusCodeMapping:
    def test_http_error_code_covers_gateway_and_service_statuses(self):
        assert _http_error_code(502) == "BAD_GATEWAY"
        assert _http_error_code(503) == "SERVICE_UNAVAILABLE"
        assert _http_error_code(504) == "GATEWAY_TIMEOUT"

    def test_http_error_code_fallback_for_unmapped_status(self):
        assert _http_error_code(418) == "HTTP_ERROR"
