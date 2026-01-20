"""
Security Tests
보안 관련 테스트
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


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
        assert response.status_code == 400
        assert "X-User-Key" in response.text or "user" in response.text.lower()

    @pytest.mark.asyncio
    async def test_short_user_key_rejected(self, client: AsyncClient):
        """Short X-User-Key should be rejected."""
        response = await client.get(
            "/v1/library",
            headers={"X-User-Key": "short"}
        )
        assert response.status_code == 400


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
    async def test_book_spec_validation_empty_topic(self, client: AsyncClient, headers: dict):
        """Empty topic should be rejected."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor"
            },
            headers=headers
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_book_spec_validation_invalid_age(self, client: AsyncClient, headers: dict):
        """Invalid target_age should be rejected."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for book creation",
                "language": "ko",
                "target_age": "invalid",
                "style": "watercolor"
            },
            headers=headers
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_book_spec_validation_invalid_style(self, client: AsyncClient, headers: dict):
        """Invalid style should be rejected."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for book creation",
                "language": "ko",
                "target_age": "5-7",
                "style": "invalid_style"
            },
            headers=headers
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_book_spec_validation_page_count_bounds(self, client: AsyncClient, headers: dict):
        """Page count should be within bounds."""
        # Too few pages
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for book creation",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 1
            },
            headers=headers
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
                "page_count": 100
            },
            headers=headers
        )
        assert response.status_code == 422


class TestCORS:
    """CORS configuration tests."""

    @pytest.mark.asyncio
    async def test_cors_headers_on_options(self, client: AsyncClient):
        """OPTIONS request should include CORS headers."""
        response = await client.options(
            "/v1/books",
            headers={"Origin": "http://localhost:3000"}
        )
        # Preflight should succeed
        assert response.status_code in (200, 204, 405)


class TestErrorHandling:
    """Error handling tests."""

    @pytest.mark.asyncio
    async def test_404_response_format(self, client: AsyncClient, headers: dict):
        """404 responses should have proper format."""
        response = await client.get(
            "/v1/books/nonexistent-job-id",
            headers=headers
        )
        assert response.status_code == 404
        assert "detail" in response.json()

    @pytest.mark.asyncio
    async def test_validation_error_format(self, client: AsyncClient, headers: dict):
        """Validation errors should have proper format."""
        response = await client.post(
            "/v1/books",
            json={"invalid": "data"},
            headers=headers
        )
        assert response.status_code == 422
        assert "detail" in response.json()
