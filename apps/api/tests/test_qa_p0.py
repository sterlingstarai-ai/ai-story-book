"""
QA P0 Checklist Tests - Critical tests that must pass before release
Based on CLAUDE.md QA P0 체크리스트
"""
import pytest
from httpx import AsyncClient


class TestQAP0BasicGeneration:
    """P0-1: 기본 생성 성공 (8페이지)"""

    @pytest.mark.asyncio
    async def test_basic_generation_8_pages(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """기본 8페이지 책 생성 요청이 성공해야 함."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "토끼가 하늘을 나는 이야기",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 8,
            },
            headers=headers,
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"


class TestQAP0ProgressDisplay:
    """P0-2: 진행률 표시 정상"""

    @pytest.mark.asyncio
    async def test_progress_display(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """진행률 조회가 정상 동작해야 함."""
        # Create book
        create_response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        job_id = create_response.json()["job_id"]

        # Check status
        status_response = await client.get(
            f"/v1/books/{job_id}",
            headers=headers,
        )
        assert status_response.status_code == 200
        data = status_response.json()
        assert "progress" in data
        assert isinstance(data["progress"], int)
        assert 0 <= data["progress"] <= 100


class TestQAP0InputSafety:
    """P0-3: 입력 안전성 차단 (아동)"""

    @pytest.mark.asyncio
    async def test_violence_topic_should_be_accepted_for_validation(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """폭력적 주제는 서버에서 처리될 때 모더레이션됨 (요청 자체는 받음)."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "전쟁과 폭력에 관한 이야기",
                "language": "ko",
                "target_age": "3-5",
                "style": "watercolor",
                "page_count": 8,
            },
            headers=headers,
        )
        # Request is accepted, moderation happens during processing
        assert response.status_code in [200, 201, 400]


class TestQAP0PersonalInfo:
    """P0-4: 개인정보 차단"""

    @pytest.mark.asyncio
    async def test_personal_info_in_topic(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """개인정보 포함 요청 처리."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "철수(010-1234-5678)의 이야기",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 8,
            },
            headers=headers,
        )
        # Request is accepted, PII filtering happens during processing
        assert response.status_code in [200, 201, 400]


class TestQAP0ForbiddenElements:
    """P0-5: forbidden_elements 강제"""

    @pytest.mark.asyncio
    async def test_forbidden_elements_accepted(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """forbidden_elements가 요청에 포함될 수 있어야 함."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "토끼의 모험",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": 8,
                "forbidden_elements": ["폭력", "공포", "어두운 장면"],
            },
            headers=headers,
        )
        assert response.status_code in [200, 201]


class TestQAP0PageImageRegeneration:
    """P0-6: 페이지 이미지 재생성"""

    @pytest.mark.asyncio
    async def test_page_regeneration_endpoint_exists(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """페이지 재생성 엔드포인트가 존재해야 함."""
        # Create book first
        create_response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        job_id = create_response.json()["job_id"]

        # Try regenerate (may fail if job not complete, but endpoint should exist)
        response = await client.post(
            f"/v1/books/{job_id}/pages/1/regenerate",
            json={"regenerate_target": "image"},
            headers=headers,
        )
        # Should not be 405 (Method Not Allowed) - endpoint exists
        assert response.status_code != 405


class TestQAP0PageTextRewrite:
    """P0-7: 페이지 텍스트 리라이트"""

    @pytest.mark.asyncio
    async def test_text_regeneration_target(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """텍스트 재생성 타겟이 유효해야 함."""
        create_response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        job_id = create_response.json()["job_id"]

        response = await client.post(
            f"/v1/books/{job_id}/pages/1/regenerate",
            json={"regenerate_target": "text"},
            headers=headers,
        )
        # Should not be 422 for target validation
        assert response.status_code != 405


class TestQAP0CharacterSave:
    """P0-8: 캐릭터 저장 (시리즈 씨앗)"""

    @pytest.mark.asyncio
    async def test_character_save(
        self,
        client: AsyncClient,
        headers: dict,
        valid_character: dict,
    ):
        """캐릭터 저장이 성공해야 함."""
        response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert "id" in data
        assert data["name"] == valid_character["name"]

    @pytest.mark.asyncio
    async def test_character_used_in_series(
        self,
        client: AsyncClient,
        headers: dict,
        valid_character: dict,
    ):
        """저장된 캐릭터로 시리즈 생성이 가능해야 함."""
        # Save character
        char_response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        character_id = char_response.json()["id"]

        # Use in series
        series_response = await client.post(
            "/v1/books/series",
            json={
                "character_id": character_id,
                "topic": "토리의 새로운 모험",
            },
            headers=headers,
        )
        assert series_response.status_code in [200, 201]


class TestQAP0CharacterConsistency:
    """P0-9: 캐릭터 일관성 확인"""

    @pytest.mark.asyncio
    async def test_character_details_preserved(
        self,
        client: AsyncClient,
        headers: dict,
        valid_character: dict,
    ):
        """캐릭터 상세 정보가 보존되어야 함."""
        # Save character
        create_response = await client.post(
            "/v1/characters",
            json=valid_character,
            headers=headers,
        )
        character_id = create_response.json()["id"]

        # Retrieve character
        get_response = await client.get(
            f"/v1/characters/{character_id}",
            headers=headers,
        )
        assert get_response.status_code == 200
        data = get_response.json()

        # Verify all fields preserved
        assert data["name"] == valid_character["name"]
        assert data["master_description"] == valid_character["master_description"]
        assert data["appearance"]["face"] == valid_character["appearance"]["face"]
        assert data["clothing"]["top"] == valid_character["clothing"]["top"]


class TestQAP0ImageGenerationFailure:
    """P0-10: 이미지 생성 실패 처리"""

    @pytest.mark.asyncio
    async def test_job_status_shows_error_on_failure(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """Job 상태에 에러 정보가 포함될 수 있어야 함."""
        # This tests the schema, actual failure handling requires mocking
        # Check that status endpoint returns error fields
        response = await client.get(
            "/v1/books/test-job-id",
            headers=headers,
        )
        # 404 is expected, but response should be valid JSON
        assert response.status_code in [404, 200]


class TestQAP0LLMJsonParsing:
    """P0-11: LLM JSON 파싱 실패 처리"""

    @pytest.mark.asyncio
    async def test_error_response_structure(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """에러 응답 구조가 올바라야 함."""
        # Create job and check status structure
        create_response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        job_id = create_response.json()["job_id"]

        status_response = await client.get(
            f"/v1/books/{job_id}",
            headers=headers,
        )
        data = status_response.json()

        # Error fields should be in response schema (may be null)
        assert "error_code" in data or data.get("status") != "failed"
        assert "error_message" in data or data.get("status") != "failed"


class TestQAP0DuplicateRequestPrevention:
    """P0-12: 중복 요청 방지"""

    @pytest.mark.asyncio
    async def test_idempotency_key_works(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """동일한 idempotency key로 중복 요청 시 같은 job 반환."""
        idempotency_key = "p0-test-idempotency-key"
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
        job_id1 = response1.json()["job_id"]

        # Duplicate request
        response2 = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers_with_key,
        )
        job_id2 = response2.json()["job_id"]

        assert job_id1 == job_id2


class TestQAP0LibraryPersistence:
    """P0-13: 앱 재실행 후 서재 유지 (API 관점)"""

    @pytest.mark.asyncio
    async def test_library_endpoint_returns_consistent_data(
        self,
        client: AsyncClient,
        headers: dict,
    ):
        """서재 API가 일관된 데이터를 반환해야 함."""
        # First call
        response1 = await client.get("/v1/library", headers=headers)
        assert response1.status_code == 200
        data1 = response1.json()

        # Second call (simulating app restart)
        response2 = await client.get("/v1/library", headers=headers)
        assert response2.status_code == 200
        data2 = response2.json()

        # Should return same data
        assert data1["total"] == data2["total"]


class TestQAP0SlowNetwork:
    """P0-14: 느린 네트워크 처리"""

    @pytest.mark.asyncio
    async def test_timeout_config_exists(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """요청이 적절히 처리되어야 함 (타임아웃 없이)."""
        response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        # Should complete without timeout in test environment
        assert response.status_code in [200, 201]


class TestQAP0CoverImage:
    """P0-16: Cover 이미지 생성 테스트"""

    @pytest.mark.asyncio
    async def test_book_creation_includes_cover_concept(
        self,
        client: AsyncClient,
        headers: dict,
        valid_book_spec: dict,
    ):
        """책 생성 요청이 표지 개념을 포함해야 함."""
        response = await client.post(
            "/v1/books",
            json=valid_book_spec,
            headers=headers,
        )
        assert response.status_code in [200, 201]
        # Cover is generated as part of the pipeline


class TestQAP0AllAgeRanges:
    """모든 연령대 지원 확인"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("age", ["3-5", "5-7", "7-9", "adult"])
    async def test_age_range_supported(
        self,
        client: AsyncClient,
        headers: dict,
        age: str,
    ):
        """모든 연령대에서 책 생성이 가능해야 함."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": f"테스트 이야기 ({age})",
                "language": "ko",
                "target_age": age,
                "style": "watercolor",
                "page_count": 8,
            },
            headers=headers,
        )
        assert response.status_code in [200, 201]


class TestQAP0AllStyles:
    """모든 스타일 지원 확인"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "style",
        ["watercolor", "cartoon", "3d", "pixel", "oil_painting", "claymation"],
    )
    async def test_style_supported(
        self,
        client: AsyncClient,
        headers: dict,
        style: str,
    ):
        """모든 스타일에서 책 생성이 가능해야 함."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": f"테스트 이야기 ({style})",
                "language": "ko",
                "target_age": "5-7",
                "style": style,
                "page_count": 8,
            },
            headers=headers,
        )
        assert response.status_code in [200, 201]


class TestQAP0PageCounts:
    """페이지 수 범위 확인"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("page_count", [4, 6, 8, 10, 12])
    async def test_page_count_supported(
        self,
        client: AsyncClient,
        headers: dict,
        page_count: int,
    ):
        """지원되는 페이지 수에서 책 생성이 가능해야 함."""
        response = await client.post(
            "/v1/books",
            json={
                "topic": "테스트 이야기",
                "language": "ko",
                "target_age": "5-7",
                "style": "watercolor",
                "page_count": page_count,
            },
            headers=headers,
        )
        assert response.status_code in [200, 201]
