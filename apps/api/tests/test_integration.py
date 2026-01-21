"""
Integration Tests - API endpoints with database
"""

import pytest
from httpx import AsyncClient


class TestHealthCheck:
    """Health check endpoint tests."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Health check should return healthy status."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestBookCreation:
    """Book creation endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_book_success(
        self, client: AsyncClient, headers: dict, valid_book_spec: dict
    ):
        """Create book should return job_id."""
        response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_create_book_missing_user_key(
        self, client: AsyncClient, valid_book_spec: dict
    ):
        """Create book without user key should fail."""
        response = await client.post("/v1/books", json=valid_book_spec)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_book_invalid_user_key(
        self, client: AsyncClient, valid_book_spec: dict
    ):
        """Create book with short user key should fail."""
        response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers={"X-User-Key": "short"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_book_topic_too_long(self, client: AsyncClient, headers: dict):
        """Topic exceeding max length should fail."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "x" * 300,
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 8,
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_book_invalid_age(self, client: AsyncClient, headers: dict):
        """Invalid target age should fail."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "토끼 이야기",
                "language": "ko",
                "target_age": "invalid",
                "style": "watercolor",
                "page_count": 8,
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_book_invalid_style(self, client: AsyncClient, headers: dict):
        """Invalid style should fail."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "토끼 이야기",
                "language": "ko",
                "target_age": "5-7",
                "style": "invalid_style",
                "page_count": 8,
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_book_page_count_out_of_range(
        self, client: AsyncClient, headers: dict
    ):
        """Page count out of range should fail."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "토끼 이야기",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 20,  # Max is 12
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_book_idempotency(
        self, client: AsyncClient, headers: dict, valid_book_spec: dict
    ):
        """Same idempotency key should return same job_id."""
        idempotency_key = "unique-idempotency-key-12345"
        headers_with_idempotency = {
            **headers,
            "X-Idempotency-Key": idempotency_key,
        }

        # First request
        response1 = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers_with_idempotency,
        )
        assert response1.status_code in [200, 201]
        job_id1 = response1.json()["job_id"]

        # Second request with same idempotency key
        response2 = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers_with_idempotency,
        )
        assert response2.status_code in [200, 201]
        job_id2 = response2.json()["job_id"]

        # Should return same job_id
        assert job_id1 == job_id2


class TestBookStatus:
    """Book status endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_book_status_not_found(self, client: AsyncClient, headers: dict):
        """Get non-existent job should return 404."""
        response = await client.get(
            "/v1/books/non-existent-job-id",
            headers=headers,
        )
        assert response.status_code in [404, 422]

    @pytest.mark.asyncio
    async def test_get_book_status_after_create(
        self, client: AsyncClient, headers: dict, valid_book_spec: dict
    ):
        """Get job status after creation."""
        # Create book
        create_response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        job_id = create_response.json()["job_id"]

        # Get status
        status_response = await client.get(
            f"/v1/books/{job_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["job_id"] == job_id
        assert data["status"] in ["queued", "running", "done", "failed"]
        assert "progress" in data


class TestCharacters:
    """Character CRUD endpoint tests."""

    @pytest.mark.asyncio
    async def test_create_character(
        self, client: AsyncClient, headers: dict, valid_character: dict
    ):
        """Create character should succeed."""
        response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert "character_id" in data
        assert data["name"] == valid_character["name"]

    @pytest.mark.asyncio
    async def test_list_characters_empty(self, client: AsyncClient, headers: dict):
        """List characters when empty."""
        response = await client.get("/v1/characters", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "characters" in data
        assert len(data["characters"]) == 0

    @pytest.mark.asyncio
    async def test_list_characters_after_create(
        self, client: AsyncClient, headers: dict, valid_character: dict
    ):
        """List characters after creating one."""
        # Create character
        await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )

        # List characters
        response = await client.get("/v1/characters", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["characters"]) == 1
        assert data["characters"][0]["name"] == valid_character["name"]

    @pytest.mark.asyncio
    async def test_get_character_by_id(
        self, client: AsyncClient, headers: dict, valid_character: dict
    ):
        """Get character by ID."""
        # Create character
        create_response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        character_id = create_response.json()["character_id"]

        # Get character
        response = await client.get(
            f"/v1/characters/{character_id}",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["character_id"] == character_id
        assert data["name"] == valid_character["name"]

    @pytest.mark.asyncio
    async def test_get_character_not_found(self, client: AsyncClient, headers: dict):
        """Get non-existent character should return 404."""
        response = await client.get(
            "/v1/characters/non-existent-id",
            headers=headers,
        )
        assert response.status_code in [404, 422]

    @pytest.mark.asyncio
    async def test_create_character_invalid_name(
        self, client: AsyncClient, headers: dict, valid_character: dict
    ):
        """Create character with invalid name should fail."""
        invalid_character = {**valid_character, "name": ""}
        response = await client.post(
            "/v1/characters",
            json=invalid_character,
            headers=headers,
        )
        assert response.status_code == 422


class TestLibrary:
    """Library endpoint tests."""

    @pytest.mark.asyncio
    async def test_library_empty(self, client: AsyncClient, headers: dict):
        """Library should be empty initially."""
        response = await client.get("/v1/library", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "books" in data
        assert len(data["books"]) == 0
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_library_pagination(self, client: AsyncClient, headers: dict):
        """Library pagination parameters."""
        response = await client.get(
            "/v1/library",
            params={"limit": 10, "offset": 0},
            headers=headers,
        )
        assert response.status_code == 200


class TestPageRegeneration:
    """Page regeneration endpoint tests."""

    @pytest.mark.asyncio
    async def test_regenerate_page_not_found(self, client: AsyncClient, headers: dict):
        """Regenerate page for non-existent job should fail."""
        response = await client.post(
            "/v1/books/non-existent-job/pages/1/regenerate",
            json={"regenerate_target": "text"},
            headers=headers,
        )
        assert response.status_code in [404, 422]

    @pytest.mark.asyncio
    async def test_regenerate_page_invalid_target(
        self, client: AsyncClient, headers: dict, valid_book_spec: dict
    ):
        """Regenerate with invalid target should fail."""
        # Create book first
        create_response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        job_id = create_response.json()["job_id"]

        response = await client.post(
            f"/v1/books/{job_id}/pages/1/regenerate",
            json={"regenerate_target": "invalid"},
            headers=headers,
        )
        assert response.status_code == 422


class TestSeriesBook:
    """Series book creation tests."""

    @pytest.mark.asyncio
    async def test_create_series_character_not_found(
        self, client: AsyncClient, headers: dict
    ):
        """Create series with non-existent character should fail."""
        response = await client.post(
            "/v1/books/series",
            json={
                "character_id": "non-existent-character",
                "topic": "토리의 새로운 모험",
            },
            headers=headers,
        )
        assert response.status_code in [404, 422]

    @pytest.mark.asyncio
    async def test_create_series_success(
        self, client: AsyncClient, headers: dict, valid_character: dict
    ):
        """Create series book with existing character."""
        # Create character first
        char_response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        character_id = char_response.json()["character_id"]

        # Create series book
        response = await client.post(
            "/v1/books/series",
            json={
                "character_id": character_id,
                "topic": "토리의 새로운 모험",
            },
            headers=headers,
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert "job_id" in data


class TestUserIsolation:
    """User data isolation tests."""

    @pytest.mark.asyncio
    async def test_characters_isolated_by_user(
        self, client: AsyncClient, valid_character: dict
    ):
        """Characters should be isolated by user_key."""
        user1_headers = {"X-User-Key": "user1-key-12345678901234567890"}
        user2_headers = {"X-User-Key": "user2-key-12345678901234567890"}

        # User 1 creates character
        await client.post(
            "/v1/characters",
            json=valid_character,
            headers=user1_headers,
        )

        # User 1 should see the character
        response1 = await client.get("/v1/characters", headers=user1_headers)
        assert len(response1.json()["characters"]) == 1

        # User 2 should not see the character
        response2 = await client.get("/v1/characters", headers=user2_headers)
        assert len(response2.json()["characters"]) == 0

    @pytest.mark.asyncio
    async def test_library_isolated_by_user(self, client: AsyncClient):
        """Library should be isolated by user_key."""
        user1_headers = {"X-User-Key": "user1-key-12345678901234567890"}
        user2_headers = {"X-User-Key": "user2-key-12345678901234567890"}

        # Both users' libraries should be empty
        response1 = await client.get("/v1/library", headers=user1_headers)
        response2 = await client.get("/v1/library", headers=user2_headers)

        assert response1.json()["total"] == 0
        assert response2.json()["total"] == 0
