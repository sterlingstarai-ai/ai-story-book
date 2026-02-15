"""
v0.2 Endpoint Tests
v0.2 기능 엔드포인트 테스트

- Credits: 잔액, 구독, 거래 내역
- Streak: 스트릭 정보, 오늘의 동화, 읽기 기록
- Library: 필터링/정렬
- Books: PDF, Audio, Series
- Characters: from-text
"""

import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock


# ==================== Credits Tests ====================


class TestCreditsEndpoints:
    """크레딧 API 테스트"""

    @pytest.mark.asyncio
    async def test_get_credits_status(self, client: AsyncClient, headers: dict):
        """크레딧 상태 조회"""
        response = await client.get("/v1/credits/status", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "credits" in data
        assert "available_plans" in data

    @pytest.mark.asyncio
    async def test_get_credits_balance(self, client: AsyncClient, headers: dict):
        """크레딧 잔액 조회"""
        response = await client.get("/v1/credits/balance", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "credits" in data

    @pytest.mark.asyncio
    async def test_get_transactions_empty(self, client: AsyncClient, headers: dict):
        """거래 내역 조회 (비어 있음)"""
        response = await client.get("/v1/credits/transactions", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_subscribe_invalid_plan(self, client: AsyncClient, headers: dict):
        """잘못된 플랜 구독 시도"""
        response = await client.post(
            "/v1/credits/subscribe",
            json={"plan": "nonexistent_plan"},
            headers=headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_subscribe_valid_plan(self, client: AsyncClient, headers: dict):
        """유효한 플랜 구독"""
        response = await client.post(
            "/v1/credits/subscribe",
            json={"plan": "basic"},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_cancel_subscription_no_active(
        self, client: AsyncClient, headers: dict
    ):
        """활성 구독 없이 취소 시도"""
        response = await client.post(
            "/v1/credits/cancel-subscription", headers=headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_add_credits_no_admin_key(
        self, client: AsyncClient, headers: dict
    ):
        """관리자 키 없이 크레딧 추가 시도"""
        response = await client.post(
            "/v1/credits/add",
            json={"amount": 10, "transaction_id": "tx_123"},
            headers=headers,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_check_credits(self, client: AsyncClient, headers: dict):
        """크레딧 확인"""
        response = await client.get(
            "/v1/credits/check?required=1", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "has_credits" in data
        assert "current_credits" in data


# ==================== Streak Tests ====================


class TestStreakEndpoints:
    """스트릭 API 테스트"""

    @pytest.mark.asyncio
    async def test_get_streak_info(self, client: AsyncClient, headers: dict):
        """스트릭 정보 조회"""
        response = await client.get("/v1/streak/info", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "current_streak" in data
        assert "read_today" in data
        assert data["current_streak"] == 0

    @pytest.mark.asyncio
    async def test_get_today_story(self, client: AsyncClient, headers: dict):
        """오늘의 동화 조회"""
        response = await client.get("/v1/streak/today", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "date" in data
        assert "theme" in data
        assert "topic" in data

    @pytest.mark.asyncio
    async def test_get_themes(self, client: AsyncClient, headers: dict):
        """테마 목록 조회"""
        response = await client.get("/v1/streak/themes", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "themes" in data
        assert len(data["themes"]) > 0

    @pytest.mark.asyncio
    async def test_reading_history_empty(self, client: AsyncClient, headers: dict):
        """읽기 히스토리 (빈 상태)"""
        response = await client.get("/v1/streak/history", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "history" in data

    @pytest.mark.asyncio
    async def test_streak_calendar(self, client: AsyncClient, headers: dict):
        """스트릭 캘린더 조회"""
        response = await client.get(
            "/v1/streak/calendar?year=2026&month=2", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2026
        assert data["month"] == 2
        assert "days" in data


# ==================== Library Filter/Sort Tests ====================


class TestLibraryFilterSort:
    """서재 필터/정렬 테스트"""

    @pytest.mark.asyncio
    async def test_library_default_sort(self, client: AsyncClient, headers: dict):
        """기본 정렬 (newest)"""
        response = await client.get("/v1/library", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "books" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_library_sort_oldest(self, client: AsyncClient, headers: dict):
        """오래된 순 정렬"""
        response = await client.get(
            "/v1/library?sort=oldest", headers=headers
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_library_sort_title(self, client: AsyncClient, headers: dict):
        """제목순 정렬"""
        response = await client.get(
            "/v1/library?sort=title", headers=headers
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_library_filter_style(self, client: AsyncClient, headers: dict):
        """스타일 필터"""
        response = await client.get(
            "/v1/library?style=watercolor", headers=headers
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_library_filter_age(self, client: AsyncClient, headers: dict):
        """연령대 필터"""
        response = await client.get(
            "/v1/library?target_age=5-7", headers=headers
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_library_pagination(self, client: AsyncClient, headers: dict):
        """페이지네이션"""
        response = await client.get(
            "/v1/library?limit=5&offset=0", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data


# ==================== Book PDF/Audio Tests ====================


class TestBookExport:
    """책 내보내기 테스트"""

    @pytest.mark.asyncio
    async def test_pdf_book_not_found(self, client: AsyncClient, headers: dict):
        """존재하지 않는 책 PDF 요청"""
        response = await client.get(
            "/v1/books/nonexistent-book/pdf", headers=headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_audio_book_not_found(self, client: AsyncClient, headers: dict):
        """존재하지 않는 책 오디오 요청"""
        response = await client.post(
            "/v1/books/nonexistent-book/audio", headers=headers
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_page_audio_not_found(self, client: AsyncClient, headers: dict):
        """존재하지 않는 페이지 오디오 요청"""
        response = await client.get(
            "/v1/books/nonexistent-book/pages/1/audio", headers=headers
        )
        assert response.status_code == 404


# ==================== Series Tests ====================


class TestSeriesEndpoint:
    """시리즈 API 테스트"""

    @pytest.mark.asyncio
    async def test_series_missing_character(
        self, client: AsyncClient, headers: dict
    ):
        """존재하지 않는 캐릭터로 시리즈 생성 시도"""
        response = await client.post(
            "/v1/books/series",
            json={
                "character_id": "nonexistent-char",
                "topic": "토끼의 두 번째 모험",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_series_with_character(
        self, client: AsyncClient, headers: dict, valid_character: dict
    ):
        """캐릭터 생성 후 시리즈 생성"""
        # 1. 캐릭터 생성
        char_response = await client.post(
            "/v1/characters", json=valid_character, headers=headers
        )
        assert char_response.status_code == 200
        char_id = char_response.json()["character_id"]

        # 2. 시리즈 생성 시도
        response = await client.post(
            "/v1/books/series",
            json={
                "character_id": char_id,
                "topic": "토끼의 두 번째 모험",
                "target_age": "5-7",
                "style": "watercolor",
            },
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data


# ==================== Characters From Text Tests ====================


class TestCharacterFromText:
    """텍스트 기반 캐릭터 생성 테스트"""

    @pytest.mark.asyncio
    async def test_from_text_success(self, client: AsyncClient, headers: dict):
        """텍스트 설명으로 캐릭터 생성"""
        with patch(
            "src.services.photo_character.photo_character_service.create_character_from_text",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = {
                "name": "토리",
                "master_description": "5살 귀여운 토끼 캐릭터",
                "appearance": {
                    "age_visual": "5세",
                    "face": "둥근 얼굴",
                    "hair": "없음",
                    "skin": "갈색 털",
                    "body": "통통한 체형",
                },
                "clothing": {
                    "top": "줄무늬 티셔츠",
                    "bottom": "바지",
                    "shoes": "운동화",
                    "accessories": "없음",
                },
                "personality_traits": ["호기심 많은", "용감한"],
                "visual_style_notes": "cartoon style",
            }

            response = await client.post(
                "/v1/characters/from-text",
                data={
                    "name": "토리",
                    "age": "5살",
                    "traits": "호기심 많은, 용감한",
                    "style": "cartoon",
                },
                headers=headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "토리"
            assert "character_id" in data


# ==================== Dependencies Tests ====================


class TestUserKeyValidation:
    """user_key UUID 검증 테스트"""

    @pytest.mark.asyncio
    async def test_valid_uuid(self, client: AsyncClient):
        """유효한 UUID는 허용"""
        response = await client.get(
            "/v1/library",
            headers={"X-User-Key": "550e8400-e29b-41d4-a716-446655440000"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_format_rejected(self, client: AsyncClient):
        """비-UUID 형식은 거부"""
        response = await client.get(
            "/v1/library",
            headers={"X-User-Key": "not-a-valid-uuid"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_short_key_rejected(self, client: AsyncClient):
        """짧은 키는 거부"""
        response = await client.get(
            "/v1/library",
            headers={"X-User-Key": "short"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_key_rejected(self, client: AsyncClient):
        """빈 키는 거부"""
        response = await client.get(
            "/v1/library",
            headers={"X-User-Key": ""},
        )
        # FastAPI may return 422 for empty required header or 400
        assert response.status_code in (400, 422)
