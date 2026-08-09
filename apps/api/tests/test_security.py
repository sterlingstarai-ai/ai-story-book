"""
Security Tests
보안 관련 테스트
"""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock


class TestRateLimiting:
    """Rate limiting tests."""

    @pytest.mark.asyncio
    async def test_rate_limit_headers_present(self, client: AsyncClient, headers: dict):
        """Rate limit headers should be present in response."""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_user_key_rejected(self, client: AsyncClient):
        """Requests without X-User-Key should be rejected."""
        response = await client.get("/v1/library")
        # FastAPI returns 422 for missing required headers
        assert response.status_code in (400, 422)
        assert "x-user-key" in response.text.lower() or "user" in response.text.lower()

    @pytest.mark.asyncio
    async def test_short_user_key_rejected(self, client: AsyncClient):
        """Short X-User-Key should be rejected."""
        response = await client.get("/v1/library", headers={"X-User-Key": "short"})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_429_with_headers(
        self,
        client: AsyncClient,
        headers: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Exceeded rate limit should return 429 and expose rate-limit headers."""
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
        body = response.json()
        # M2: 다른 모든 에러 코드와 같은 UPPER_SNAKE. 소문자였던 탓에 모바일이
        # RATE_LIMIT_EXCEEDED 분기에 매칭하지 못해 en/ja 에 한국어가 노출됐다.
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert body["error"]["message"] == body["detail"]
        assert body["error"]["details"]["retry_after"] == settings.rate_limit_window
        assert response.headers.get("Retry-After") == str(settings.rate_limit_window)
        assert response.headers.get("X-RateLimit-Remaining") == "0"
        assert response.headers.get("X-RateLimit-Limit") == str(settings.rate_limit_requests)

    @pytest.mark.asyncio
    async def test_rate_limit_headers_present_when_request_allowed(
        self,
        client: AsyncClient,
        headers: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Allowed requests should still include X-RateLimit headers."""
        from src.core import rate_limit
        from src.core.config import settings

        monkeypatch.setattr(settings, "rate_limit_enforce_in_testing", True)
        monkeypatch.setattr(
            rate_limit.rate_limiter,
            "is_allowed",
            AsyncMock(return_value=(True, 7)),
        )

        response = await client.get("/v1/library", headers=headers)

        assert response.status_code == 200
        assert response.headers.get("X-RateLimit-Remaining") == "7"
        assert response.headers.get("X-RateLimit-Limit") is not None


class TestSecurityHeaders:
    """Security headers tests."""

    @pytest.mark.asyncio
    async def test_security_headers_present(self, client: AsyncClient):
        """Security headers should be present in all responses."""
        response = await client.get("/health")
        assert response.status_code == 200

        # Check security headers
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "Referrer-Policy" in response.headers


class TestInputValidation:
    """Input validation tests."""

    @pytest.mark.asyncio
    async def test_book_spec_validation_empty_topic(
        self, client: AsyncClient, headers: dict
    ):
        """Empty topic should be rejected."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_book_spec_validation_invalid_age(
        self, client: AsyncClient, headers: dict
    ):
        """Invalid target_age should be rejected."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for book creation",
                "language": "ko",
                "target_age": "invalid",
                "style": "watercolor",
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_book_spec_validation_invalid_style(
        self, client: AsyncClient, headers: dict
    ):
        """Invalid style should be rejected."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for book creation",
                "language": "ko",
                "target_age": "5-7",
                "style": "invalid_style",
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_book_spec_validation_page_count_bounds(
        self, client: AsyncClient, headers: dict
    ):
        """Page count should be within bounds."""
        # Too few pages
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for book creation",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 1,
            },
            headers=headers,
        )
        assert response.status_code == 422

        # Too many pages
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for book creation",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 100,
            },
            headers=headers,
        )
        assert response.status_code == 422


class TestCORS:
    """CORS configuration tests."""

    @pytest.mark.asyncio
    async def test_cors_headers_on_options(self, client: AsyncClient):
        """OPTIONS request should include CORS headers."""
        response = await client.options(
            "/v1/books", headers={"Origin": "http://localhost:3000"}
        )
        # Preflight should succeed
        assert response.status_code in (200, 204, 405)


class TestErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_404_response_format(self, client: AsyncClient, headers: dict):
        """404 responses should have proper format."""
        response = await client.get("/v1/books/nonexistent-job-id", headers=headers)
        assert response.status_code == 404
        assert "detail" in response.json()

    @pytest.mark.asyncio
    async def test_validation_error_format(self, client: AsyncClient, headers: dict):
        """Validation errors should have proper format."""
        response = await client.post(
            "/v1/books", json={"invalid": "data"}, headers=headers
        )
        assert response.status_code == 422
        assert "detail" in response.json()


# ==================== M9: health 엔드포인트 노출 축소 ====================


class TestHealthExposureM9:
    """M9: /health/detailed 무인증 노출 + /ready missing_keys 상세 노출 차단."""

    @pytest.mark.asyncio
    async def test_detailed_health_requires_admin_key(self, client, monkeypatch):
        from src.core.config import settings

        monkeypatch.setattr(settings, "admin_api_key", "k-secret")
        # 헤더 없음 → 403
        r = await client.get("/health/detailed")
        assert r.status_code == 403, r.text
        # 잘못된 키 → 403
        r2 = await client.get("/health/detailed", headers={"X-Admin-Key": "wrong"})
        assert r2.status_code == 403
        # 올바른 키 → 200 + 메트릭 노출
        r3 = await client.get("/health/detailed", headers={"X-Admin-Key": "k-secret"})
        assert r3.status_code == 200, r3.text

    @pytest.mark.asyncio
    async def test_ready_health_hides_missing_keys_detail(self, client, monkeypatch):
        from src.core.config import settings

        monkeypatch.setattr(settings, "testing", False)
        monkeypatch.setattr(settings, "iap_verification_mode", "local")
        monkeypatch.setattr(settings, "apple_iap_shared_secret", None)
        monkeypatch.setattr(settings, "iap_webhook_secret", "")

        r = await client.get("/health/ready")
        assert r.status_code == 503  # 미설정 → not-ready
        body = r.text
        # 공개 응답에 상세 사유 문자열 미노출(provider_keys boolean만).
        assert "iap_webhook_secret_missing" not in body
        assert "missing_keys" not in r.json()
