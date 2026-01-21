"""
Router Tests
라우터 엔드포인트 테스트
"""

import pytest
from httpx import AsyncClient


class TestHealthEndpoint:
    """Health check endpoint tests."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient):
        """Health endpoint should return 200."""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_response_structure(self, client: AsyncClient):
        """Health response should have expected structure."""
        response = await client.get("/health")
        data = response.json()

        assert "status" in data
        assert data["status"] == "healthy"
        assert "version" in data


class TestBooksRouter:
    """Books router tests."""

    @pytest.mark.asyncio
    async def test_create_book_success(
        self, client: AsyncClient, headers: dict, valid_book_spec: dict
    ):
        """Creating a book should return job_id."""
        response = await client.post("/v1/books", json=valid_book_spec, headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert "job_id" in data
        assert "status" in data
        assert data["status"] in ["queued", "running"]

    @pytest.mark.asyncio
    async def test_create_book_idempotency(
        self, client: AsyncClient, headers: dict, valid_book_spec: dict
    ):
        """Same idempotency key should return same job."""
        idempotency_key = "test-idempotency-key-12345"
        headers_with_idempotency = {**headers, "X-Idempotency-Key": idempotency_key}

        # First request
        response1 = await client.post(
            "/v1/books", json=valid_book_spec, headers=headers_with_idempotency
        )
        assert response1.status_code == 200
        job_id1 = response1.json()["job_id"]

        # Second request with same key
        response2 = await client.post(
            "/v1/books", json=valid_book_spec, headers=headers_with_idempotency
        )
        assert response2.status_code == 200
        job_id2 = response2.json()["job_id"]

        assert job_id1 == job_id2

    @pytest.mark.asyncio
    async def test_get_book_status_not_found(self, client: AsyncClient, headers: dict):
        """Getting non-existent job should return 404."""
        response = await client.get("/v1/books/nonexistent-job-id", headers=headers)
        assert response.status_code == 404


class TestCharactersRouter:
    """Characters router tests."""

    @pytest.mark.asyncio
    async def test_create_character_success(
        self, client: AsyncClient, headers: dict, valid_character: dict
    ):
        """Creating a character should succeed."""
        response = await client.post(
            "/v1/characters", json=valid_character, headers=headers
        )
        assert response.status_code == 200
        data = response.json()

        assert "character_id" in data
        assert data["name"] == valid_character["name"]

    @pytest.mark.asyncio
    async def test_list_characters_empty(self, client: AsyncClient, headers: dict):
        """Listing characters for new user should return empty list."""
        response = await client.get("/v1/characters", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert "characters" in data
        assert "total" in data
        assert isinstance(data["characters"], list)

    @pytest.mark.asyncio
    async def test_get_character_not_found(self, client: AsyncClient, headers: dict):
        """Getting non-existent character should return 404."""
        response = await client.get(
            "/v1/characters/nonexistent-char-id", headers=headers
        )
        assert response.status_code == 404


class TestLibraryRouter:
    """Library router tests."""

    @pytest.mark.asyncio
    async def test_get_library_empty(self, client: AsyncClient, headers: dict):
        """Getting library for new user should return empty list."""
        response = await client.get("/v1/library", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert "books" in data
        assert "total" in data
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_library_pagination(self, client: AsyncClient, headers: dict):
        """Library should support pagination parameters."""
        response = await client.get("/v1/library?limit=10&offset=0", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_library_pagination_bounds(self, client: AsyncClient, headers: dict):
        """Library should reject invalid pagination parameters."""
        # Limit too high
        response = await client.get("/v1/library?limit=1000", headers=headers)
        assert response.status_code == 422

        # Negative offset
        response = await client.get("/v1/library?offset=-1", headers=headers)
        assert response.status_code == 422


class TestCreditsRouter:
    """Credits router tests."""

    @pytest.mark.asyncio
    async def test_get_credits_balance(self, client: AsyncClient, headers: dict):
        """Getting credits balance should work."""
        response = await client.get("/v1/credits/balance", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert "credits" in data

    @pytest.mark.asyncio
    async def test_get_credits_status(self, client: AsyncClient, headers: dict):
        """Getting credits status should return full info."""
        response = await client.get("/v1/credits/status", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert "credits" in data
        assert "available_plans" in data

    @pytest.mark.asyncio
    async def test_check_credits(self, client: AsyncClient, headers: dict):
        """Checking credits should return availability."""
        response = await client.get("/v1/credits/check?required=1", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert "has_credits" in data
        assert "current_credits" in data
        assert "required" in data


class TestStreakRouter:
    """Streak router tests."""

    @pytest.mark.asyncio
    async def test_get_streak_info(self, client: AsyncClient, headers: dict):
        """Getting streak info should work."""
        response = await client.get("/v1/streak/info", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert "current_streak" in data
        assert "read_today" in data

    @pytest.mark.asyncio
    async def test_get_today_story(self, client: AsyncClient):
        """Getting today's story should work without auth."""
        # This endpoint doesn't require user_key
        response = await client.get("/v1/streak/today")
        assert response.status_code == 200
        data = response.json()

        assert "date" in data
        assert "theme" in data
        assert "topic" in data

    @pytest.mark.asyncio
    async def test_get_themes(self, client: AsyncClient):
        """Getting themes list should work."""
        response = await client.get("/v1/streak/themes")
        assert response.status_code == 200
        data = response.json()

        assert "themes" in data
        assert isinstance(data["themes"], list)
