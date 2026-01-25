"""
Fuzzing Tests
비정상 입력으로 API/worker 흐름 테스트
"""

import pytest
from httpx import AsyncClient
import random
import string


def random_string(length: int = 10) -> str:
    """Generate random string."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def random_unicode_string(length: int = 10) -> str:
    """Generate random unicode string."""
    chars = "Hello世界مرحباこんにちは🎉🚀💡"
    return "".join(random.choices(chars, k=length))


class TestBookSpecFuzzing:
    """Fuzz testing for book specification."""

    @pytest.mark.asyncio
    async def test_extremely_long_topic(self, client: AsyncClient, headers: dict):
        """Test with extremely long topic."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "A" * 10000,  # Way over limit
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_unicode_topic(self, client: AsyncClient, headers: dict):
        """Test with various unicode characters."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "한글 테스트 🎉 日本語 العربية",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )
        # Should accept unicode
        assert response.status_code in (200, 422)

    @pytest.mark.asyncio
    async def test_sql_injection_attempt(self, client: AsyncClient, headers: dict):
        """Test SQL injection in topic."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "'; DROP TABLE jobs; --",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )
        # Should handle gracefully (either accept or reject, but not crash)
        assert response.status_code in (200, 422)

    @pytest.mark.asyncio
    async def test_xss_attempt(self, client: AsyncClient, headers: dict):
        """Test XSS in topic."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "<script>alert('xss')</script> normal text here",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )
        # Should handle gracefully
        assert response.status_code in (200, 422)

    @pytest.mark.asyncio
    async def test_null_bytes_in_topic(self, client: AsyncClient, headers: dict):
        """Test null bytes in input."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test\x00with\x00null\x00bytes",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )
        # Should reject or sanitize
        assert response.status_code in (200, 400, 422)

    @pytest.mark.asyncio
    async def test_empty_object(self, client: AsyncClient, headers: dict):
        """Test empty JSON object."""
        response = await client.post("/v1/books", json={}, headers=headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_wrong_types(self, client: AsyncClient, headers: dict):
        """Test wrong types for fields."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": 12345,  # Should be string
                "language": ["ko"],  # Should be string
                "target_age": {"age": "5-7"},  # Should be string
                "style": True,  # Should be string
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_page_count(self, client: AsyncClient, headers: dict):
        """Test negative page count."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for fuzzing",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": -1,
            },
            headers=headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_float_page_count(self, client: AsyncClient, headers: dict):
        """Test float page count."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for fuzzing",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 8.5,
            },
            headers=headers,
        )
        # Pydantic may coerce or reject
        assert response.status_code in (200, 422)


class TestCharacterFuzzing:
    """Fuzz testing for character endpoints."""

    @pytest.mark.asyncio
    async def test_character_name_special_chars(
        self, client: AsyncClient, headers: dict
    ):
        """Test character name with special characters."""
        response = await client.post(
            "/v1/characters",
            json={
                "name": "Test<>Name&\"'",
                "master_description": "A test character description for fuzzing",
                "appearance": {
                    "age_visual": "5-6세",
                    "face": "round face",
                    "hair": "brown",
                    "skin": "light",
                    "body": "small",
                },
                "clothing": {
                    "top": "shirt",
                    "bottom": "pants",
                    "shoes": "shoes",
                    "accessories": "none",
                },
                "personality_traits": ["friendly"],
                "visual_style_notes": "watercolor",
            },
            headers=headers,
        )
        # Should accept or reject gracefully
        assert response.status_code in (200, 422)

    @pytest.mark.asyncio
    async def test_empty_personality_traits(self, client: AsyncClient, headers: dict):
        """Test empty personality traits list."""
        response = await client.post(
            "/v1/characters",
            json={
                "name": "TestName",
                "master_description": "A test character description for fuzzing",
                "appearance": {
                    "age_visual": "5-6세",
                    "face": "round face",
                    "hair": "brown",
                    "skin": "light",
                    "body": "small",
                },
                "clothing": {
                    "top": "shirt",
                    "bottom": "pants",
                    "shoes": "shoes",
                    "accessories": "none",
                },
                "personality_traits": [],  # Empty list
                "visual_style_notes": "watercolor",
            },
            headers=headers,
        )
        assert response.status_code == 422  # Should reject empty list


class TestHeaderFuzzing:
    """Fuzz testing for headers."""

    @pytest.mark.asyncio
    async def test_very_long_user_key(self, client: AsyncClient):
        """Test extremely long user key."""
        response = await client.get("/v1/library", headers={"X-User-Key": "A" * 10000})
        # Should reject or truncate
        assert response.status_code in (200, 400, 413)

    @pytest.mark.asyncio
    async def test_unicode_user_key(self, client: AsyncClient):
        """Test unicode in user key - httpx requires ASCII headers."""
        # httpx library cannot send non-ASCII header values (raises UnicodeEncodeError)
        # So we test with ASCII-safe characters only
        response = await client.get(
            "/v1/library", headers={"X-User-Key": "test-key-with-ascii-12345678"}
        )
        # Should accept valid ASCII user key
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_special_chars_idempotency_key(
        self, client: AsyncClient, headers: dict
    ):
        """Test special characters in idempotency key."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "Test topic for fuzzing",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers={**headers, "X-Idempotency-Key": 'key<>with&special"chars'},
        )
        # Should handle gracefully
        assert response.status_code in (200, 400)


class TestPathFuzzing:
    """Fuzz testing for URL paths."""

    @pytest.mark.asyncio
    async def test_path_traversal_attempt(self, client: AsyncClient, headers: dict):
        """Test path traversal in job_id."""
        response = await client.get("/v1/books/../../../etc/passwd", headers=headers)
        assert response.status_code in (400, 404, 422)

    @pytest.mark.asyncio
    async def test_url_encoded_path(self, client: AsyncClient, headers: dict):
        """Test URL encoded characters in path."""
        response = await client.get("/v1/books/%2e%2e%2f%2e%2e%2f", headers=headers)
        assert response.status_code in (400, 404, 422)

    @pytest.mark.asyncio
    async def test_null_byte_in_path(self, client: AsyncClient, headers: dict):
        """Test null byte in path."""
        response = await client.get("/v1/books/job%00id", headers=headers)
        assert response.status_code in (400, 404, 422)


class TestQueryParamFuzzing:
    """Fuzz testing for query parameters."""

    @pytest.mark.asyncio
    async def test_negative_limit(self, client: AsyncClient, headers: dict):
        """Test negative limit parameter."""
        response = await client.get("/v1/library?limit=-1", headers=headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_string_limit(self, client: AsyncClient, headers: dict):
        """Test string as limit parameter."""
        response = await client.get("/v1/library?limit=abc", headers=headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_very_large_offset(self, client: AsyncClient, headers: dict):
        """Test very large offset parameter."""
        response = await client.get("/v1/library?offset=999999999999", headers=headers)
        # Should handle gracefully (return empty or error)
        assert response.status_code in (200, 422)


class TestJSONFuzzing:
    """Fuzz testing for JSON payloads."""

    @pytest.mark.asyncio
    async def test_deeply_nested_json(self, client: AsyncClient, headers: dict):
        """Test deeply nested JSON."""
        nested = {"a": "value"}
        for _ in range(100):
            nested = {"nested": nested}

        response = await client.post("/v1/books", json=nested, headers=headers)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_array_instead_of_object(self, client: AsyncClient, headers: dict):
        """Test array instead of object."""
        response = await client.post(
            "/v1/books", json=["topic", "ko", "5-7", "watercolor"], headers=headers
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_null_json(self, client: AsyncClient, headers: dict):
        """Test null JSON."""
        response = await client.post(
            "/v1/books",
            content="null",
            headers={**headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_malformed_json(self, client: AsyncClient, headers: dict):
        """Test malformed JSON."""
        response = await client.post(
            "/v1/books",
            content="{invalid json",
            headers={**headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422
