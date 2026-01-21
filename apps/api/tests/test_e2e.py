"""
E2E Tests - Full flow testing with mocked external services
"""

import pytest
from httpx import AsyncClient


class TestBookCreationFlow:
    """End-to-end book creation flow tests."""

    @pytest.mark.asyncio
    async def test_full_book_creation_flow(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
        mock_story_response: dict,
        mock_character_sheet: dict,
        mock_image_prompts: dict,
        mock_moderation_safe: dict,
    ):
        """Test complete book creation flow from request to completion."""
        # Step 1: Create book request
        create_response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        assert create_response.status_code in [200, 201]
        job_id = create_response.json()["job_id"]
        assert job_id is not None

        # Step 2: Check initial status
        status_response = await client.get(
            f"/v1/books/{job_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["job_id"] == job_id
        assert status_data["status"] in ["queued", "running"]

    @pytest.mark.asyncio
    async def test_book_creation_with_character(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
        valid_character: dict,
    ):
        """Test book creation with existing character."""
        # Step 1: Create character
        char_response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        assert char_response.status_code in [200, 201]
        character_id = char_response.json()["character_id"]

        # Step 2: Create book with character
        book_spec_with_char = {
            **valid_book_spec,
            "character_id": character_id,
        }
        create_response = await client.post(
            "/v1/books",
            json=book_spec_with_char,
            headers=headers,
        )
        assert create_response.status_code in [200, 201]


class TestSeriesFlow:
    """Series creation flow tests."""

    @pytest.mark.asyncio
    async def test_series_creation_flow(
        self,
        client: AsyncClient,
        headers: dict,
        valid_character: dict,
    ):
        """Test creating a series of books with the same character."""
        # Step 1: Create character
        char_response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        character_id = char_response.json()["character_id"]

        # Step 2: Create first book in series
        series_response1 = await client.post(
            "/v1/books/series",
            json={
                "character_id": character_id,
                "topic": "토리의 첫 번째 모험",
            },
            headers=headers,
        )
        assert series_response1.status_code in [200, 201]
        job_id1 = series_response1.json()["job_id"]

        # Step 3: Create second book in series
        series_response2 = await client.post(
            "/v1/books/series",
            json={
                "character_id": character_id,
                "topic": "토리의 두 번째 모험",
                "theme": "우정",
            },
            headers=headers,
        )
        assert series_response2.status_code in [200, 201]
        job_id2 = series_response2.json()["job_id"]

        # Different jobs should be created
        assert job_id1 != job_id2


class TestCharacterManagementFlow:
    """Character management flow tests."""

    @pytest.mark.asyncio
    async def test_character_crud_flow(
        self,
        client: AsyncClient,
        headers: dict,
        valid_character: dict,
    ):
        """Test complete character CRUD operations."""
        # Create
        create_response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        assert create_response.status_code in [200, 201]
        character_id = create_response.json()["character_id"]

        # Read single
        get_response = await client.get(
            f"/v1/characters/{character_id}",
            headers=headers,
        )
        assert get_response.status_code == 200
        assert get_response.json()["name"] == valid_character["name"]

        # Read list
        list_response = await client.get("/v1/characters", headers=headers)
        assert list_response.status_code == 200
        characters = list_response.json()["characters"]
        assert len(characters) == 1
        assert characters[0]["character_id"] == character_id

    @pytest.mark.asyncio
    async def test_multiple_characters(
        self,
        client: AsyncClient,
        headers: dict,
        valid_character: dict,
    ):
        """Test creating multiple characters."""
        characters_data = [
            {**valid_character, "name": "토리"},
            {**valid_character, "name": "미미"},
            {**valid_character, "name": "봄이"},
        ]

        for char_data in characters_data:
            response = await client.post(
                "/v1/characters",
                json=char_data,
                headers=headers,
            )
            assert response.status_code in [200, 201]

        # List all characters
        list_response = await client.get("/v1/characters", headers=headers)
        assert list_response.status_code == 200
        characters = list_response.json()["characters"]
        assert len(characters) == 3


class TestLibraryFlow:
    """Library management flow tests."""

    @pytest.mark.asyncio
    async def test_library_pagination_flow(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """Test library pagination."""
        # Get library with pagination
        response = await client.get(
            "/v1/library",
            params={"limit": 5, "offset": 0},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "books" in data
        assert "total" in data


class TestErrorHandling:
    """Error handling flow tests."""

    @pytest.mark.asyncio
    async def test_invalid_request_handling(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """Test handling of invalid requests."""
        # Missing required fields
        response = await client.post(
            "/v1/books",
            json={"topic": "test"},  # Missing required fields
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_not_found_handling(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """Test handling of not found resources."""
        # Non-existent job
        response = await client.get(
            "/v1/books/non-existent-job",
            headers=headers,
        )
        assert response.status_code == 404

        # Non-existent character
        response = await client.get(
            "/v1/characters/non-existent-char",
            headers=headers,
        )
        assert response.status_code == 404


class TestIdempotency:
    """Idempotency handling tests."""

    @pytest.mark.asyncio
    async def test_idempotent_book_creation(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """Test idempotent book creation with same key."""
        idempotency_key = "test-idempotency-key-unique-123"
        headers_with_key = {
            **headers,
            "X-Idempotency-Key": idempotency_key,
        }

        # First request
        response1 = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers_with_key,
        )
        assert response1.status_code in [200, 201]
        job_id1 = response1.json()["job_id"]

        # Second request (same idempotency key)
        response2 = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers_with_key,
        )
        assert response2.status_code in [200, 201]
        job_id2 = response2.json()["job_id"]

        # Should return same job
        assert job_id1 == job_id2

    @pytest.mark.asyncio
    async def test_different_idempotency_keys(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """Test that different idempotency keys create different jobs."""
        # First request
        headers1 = {**headers, "X-Idempotency-Key": "key-1-unique"}
        response1 = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers1,
        )
        job_id1 = response1.json()["job_id"]

        # Second request (different key)
        headers2 = {**headers, "X-Idempotency-Key": "key-2-unique"}
        response2 = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers2,
        )
        job_id2 = response2.json()["job_id"]

        # Should be different jobs
        assert job_id1 != job_id2


class TestAgeValidation:
    """Age-specific validation tests."""

    @pytest.mark.asyncio
    async def test_all_valid_ages(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """Test all valid age ranges."""
        valid_ages = ["3-5", "5-7", "7-9", "adult"]

        for age in valid_ages:
            response = await client.post(
                "/v1/books",
                json={
                    "topic": f"테스트 이야기 for {age}",
                    "language": "ko",
                    "target_age": age,
                    "style": "watercolor",
                    "page_count": 8,
                },
                headers=headers,
            )
            assert response.status_code in [200, 201], f"Failed for age: {age}"


class TestStyleValidation:
    """Style validation tests."""

    @pytest.mark.asyncio
    async def test_all_valid_styles(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """Test all valid styles."""
        valid_styles = [
            "watercolor",
            "cartoon",
            "3d",
            "pixel",
            "oil_painting",
            "claymation",
        ]

        for style in valid_styles:
            response = await client.post(
                "/v1/books",
                json={
                    "topic": f"테스트 이야기 with {style}",
                    "language": "ko",
                    "target_age": "5-7",
                    "style": style,
                    "page_count": 8,
                },
                headers=headers,
            )
            assert response.status_code in [200, 201], f"Failed for style: {style}"
