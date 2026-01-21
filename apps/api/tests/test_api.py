"""
API Integration Tests
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from src.main import app


@pytest.fixture
def user_key():
    return "test-user-key-12345678901234567890"


@pytest.fixture
def valid_book_spec():
    return {
        "topic": "토끼가 하늘을 나는 이야기",
        "language": "ko",
        "target_age": "5-7",
        "style": "watercolor",
        "page_count": 8,
        "theme": "감정코칭",
        "forbidden_elements": ["폭력", "공포"],
    }


@pytest.mark.asyncio
async def test_health_check():
    """Health check endpoint test"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_create_book_missing_user_key(valid_book_spec):
    """Create book without user key should fail"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/books", json=valid_book_spec)
        assert response.status_code == 422  # Missing header


@pytest.mark.asyncio
async def test_create_book_invalid_user_key(valid_book_spec):
    """Create book with invalid user key should fail"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/books", json=valid_book_spec, headers={"X-User-Key": "short"}
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_book_success(client, valid_book_spec, user_key):
    """Create book with valid input"""
    with patch(
        "src.services.orchestrator.start_book_generation", new_callable=AsyncMock
    ):
        response = await client.post(
            "/v1/books", json=valid_book_spec, headers={"X-User-Key": user_key}
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert "job_id" in data


@pytest.mark.asyncio
async def test_get_book_not_found(client, user_key):
    """Get non-existent book should return 404"""
    response = await client.get(
        "/v1/books/non-existent-job", headers={"X-User-Key": user_key}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_character(client, user_key):
    """Create character endpoint test"""
    character_data = {
        "name": "토리",
        "master_description": "5~6세 느낌의 귀여운 토끼, 둥근 얼굴, 큰 눈",
        "appearance": {
            "age_visual": "5~6세",
            "face": "둥근 얼굴, 큰 눈",
            "hair": "없음 (토끼)",
            "skin": "갈색 털",
            "body": "작고 통통함",
        },
        "clothing": {
            "top": "노란 줄무늬 티셔츠",
            "bottom": "파란 멜빵바지",
            "shoes": "빨간 운동화",
            "accessories": "없음",
        },
        "personality_traits": ["호기심 많은", "용감한"],
        "visual_style_notes": "수채화 스타일",
    }

    response = await client.post(
        "/v1/characters", json=character_data, headers={"X-User-Key": user_key}
    )
    assert response.status_code in [200, 201]
    data = response.json()
    assert "character_id" in data


@pytest.mark.asyncio
async def test_list_characters(client, user_key):
    """List characters endpoint test"""
    response = await client.get("/v1/characters", headers={"X-User-Key": user_key})
    assert response.status_code == 200
    data = response.json()
    assert "characters" in data


@pytest.mark.asyncio
async def test_library(client, user_key):
    """Library endpoint test"""
    response = await client.get("/v1/library", headers={"X-User-Key": user_key})
    assert response.status_code == 200
    data = response.json()
    assert "books" in data


# ==================== Validation Tests ====================


@pytest.mark.asyncio
async def test_book_spec_validation_topic_too_long(user_key):
    """Topic exceeding max length should fail"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/books",
            json={
                "topic": "x" * 300,  # Max is 200
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 8,
            },
            headers={"X-User-Key": user_key},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_book_spec_validation_invalid_age(user_key):
    """Invalid target age should fail"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/books",
            json={
                "topic": "토끼 이야기",
                "language": "ko",
                "target_age": "invalid",
                "style": "watercolor",
                "page_count": 8,
            },
            headers={"X-User-Key": user_key},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_book_spec_validation_page_count_out_of_range(user_key):
    """Page count out of range should fail"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/books",
            json={
                "topic": "토끼 이야기",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 20,  # Max is 12
            },
            headers={"X-User-Key": user_key},
        )
        assert response.status_code == 422
