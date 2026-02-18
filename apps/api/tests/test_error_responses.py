"""
Error response format tests
에러 응답 표준화 포맷 검증
"""

import pytest
from httpx import AsyncClient


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
