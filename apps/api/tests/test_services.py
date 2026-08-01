"""
Service Layer Tests
서비스 레이어 테스트
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPDFServiceSSRF:
    """PDF Service SSRF protection tests."""

    def test_url_validation_allowed_domains(self):
        """Test URL validation allows whitelisted domains."""
        from src.services.pdf import PDFService

        service = PDFService()

        # Allowed domains
        assert service._is_url_allowed("https://picsum.photos/200") is True
        assert service._is_url_allowed("http://localhost:9000/bucket/image.png") is True

        # Not allowed domains (potential SSRF)
        assert (
            service._is_url_allowed("http://169.254.169.254/latest/meta-data/") is False
        )
        assert service._is_url_allowed("http://internal-server/secret") is False
        assert service._is_url_allowed("file:///etc/passwd") is False

    def test_url_validation_schemes(self):
        """Test URL validation rejects non-HTTP schemes."""
        from src.services.pdf import PDFService

        service = PDFService()

        # Reject non-HTTP schemes
        assert service._is_url_allowed("ftp://server/file") is False
        assert service._is_url_allowed("file:///etc/passwd") is False
        assert service._is_url_allowed("gopher://server/") is False

    def test_url_validation_allows_s3_public_url_host(self, monkeypatch):
        """H11: s3_public_url 호스트(≠ s3_endpoint)를 허용 — R2 공개도메인/CDN 구성."""
        from src.core.config import settings
        from src.services.pdf import PDFService

        monkeypatch.setattr(settings, "s3_endpoint", "https://minio:9000")
        monkeypatch.setattr(settings, "s3_public_url", "https://cdn.example.com")
        service = PDFService()
        # 저장되는 이미지 URL은 s3_public_url/{key} 형태 — 허용되어야 삽화가 들어간다.
        assert (
            service._is_url_allowed(
                "https://cdn.example.com/storybook/books/x/cover.png"
            )
            is True
        )

    def test_url_validation_still_blocks_ssrf_with_public_host(self, monkeypatch):
        """H11: 공개 호스트 허용 후에도 SSRF(메타데이터·file://) 차단 회귀 없음."""
        from src.core.config import settings
        from src.services.pdf import PDFService

        monkeypatch.setattr(settings, "s3_endpoint", "https://minio:9000")
        monkeypatch.setattr(settings, "s3_public_url", "https://cdn.example.com")
        service = PDFService()
        assert (
            service._is_url_allowed("http://169.254.169.254/latest/meta-data/")
            is False
        )
        assert service._is_url_allowed("file:///etc/passwd") is False


class TestCreditsService:
    """Credits service tests."""

    @pytest.mark.asyncio
    async def test_get_or_create_credits_new_user(self, db_session):
        """Test creating credits for new user."""
        from src.services.credits import credits_service

        user_key = "new-test-user-key-123456789012"
        credits = await credits_service.get_or_create_credits(db_session, user_key)

        assert credits is not None
        assert credits.user_key == user_key
        assert credits.credits >= 0

    @pytest.mark.asyncio
    async def test_get_or_create_credits_existing_user(self, db_session):
        """Test getting credits for existing user."""
        from src.services.credits import credits_service

        user_key = "existing-test-user-key-1234567"
        # Create first
        credits1 = await credits_service.get_or_create_credits(db_session, user_key)
        # Get again
        credits2 = await credits_service.get_or_create_credits(db_session, user_key)

        assert credits1.user_key == credits2.user_key

    @pytest.mark.asyncio
    async def test_has_credits_true(self, db_session):
        """Test has_credits returns true when user has credits."""
        from src.services.credits import credits_service

        user_key = "credits-test-user-key-1234567"
        await credits_service.get_or_create_credits(db_session, user_key)
        await credits_service.add_credits(
            db_session,
            user_key,
            10,
            transaction_type="bonus",
            description="Test credits",
        )

        has = await credits_service.has_credits(db_session, user_key, required=5)
        assert has is True

    @pytest.mark.asyncio
    async def test_has_credits_false(self, db_session):
        """Test has_credits returns false when user lacks credits."""
        from src.services.credits import credits_service

        user_key = "no-credits-test-user-key-1234"
        await credits_service.get_or_create_credits(db_session, user_key)

        has = await credits_service.has_credits(db_session, user_key, required=100)
        assert has is False


class TestStreakService:
    """Streak service tests."""

    @pytest.mark.asyncio
    async def test_get_streak_info_new_user(self, db_session):
        """Test streak info for new user."""
        from src.services.streak import streak_service

        user_key = "streak-test-user-key-123456789"
        info = await streak_service.get_streak_info(db_session, user_key)

        assert info is not None
        assert info["current_streak"] == 0
        assert info["read_today"] is False

    @pytest.mark.asyncio
    async def test_get_today_story(self, db_session):
        """Test getting today's story."""
        from src.services.streak import streak_service

        story = await streak_service.get_today_story(db_session)

        assert story is not None
        assert "date" in story
        assert "theme" in story
        assert "topic" in story


class TestStorageService:
    """Storage service tests."""

    @pytest.mark.asyncio
    async def test_upload_bytes_mock(self):
        """Test upload_bytes with mocked S3 client."""
        from src.services import storage

        # Mock the module-level functions
        with patch.object(storage, "ensure_bucket_exists", new_callable=AsyncMock):
            with patch.object(storage, "get_s3_client") as mock_get_client:
                mock_client = MagicMock()
                mock_get_client.return_value = mock_client

                # Test upload_bytes
                url = await storage.storage_service.upload_bytes(
                    data=b"test data",
                    key="test/path/file.txt",
                    content_type="text/plain",
                )
                # Should return a URL
                assert url is not None
                # Should have called put_object
                mock_client.put_object.assert_called_once()


class TestModerationOutput:
    """Output moderation tests."""

    @pytest.mark.asyncio
    async def test_moderate_output_safe_content(self):
        """Test moderation passes safe content."""
        from src.services.orchestrator import moderate_output
        from src.models.dto import (
            StoryDraft,
            StoryPage,
            StoryCover,
            StoryCharacter,
            StoryContinuity,
            Language,
            TargetAge,
        )

        story = StoryDraft(
            title="Happy Bunny",
            language=Language.ko,
            target_age=TargetAge.a5_7,
            theme="friendship",
            moral="Friends help each other",
            characters=[
                StoryCharacter(
                    id="char1", name="Bunny", role="main", brief="A friendly bunny"
                )
            ],
            cover=StoryCover(
                cover_text="Happy Bunny Adventure",
                scene="Bunny in meadow",
                mood="cheerful",
                camera="wide shot",
            ),
            pages=[
                StoryPage(
                    page=1,
                    text="Hello friends!",
                    scene="Meadow",
                    mood="happy",
                    camera="medium shot",
                    characters_present=["Bunny"],
                ),
                StoryPage(
                    page=2,
                    text="Let's play together!",
                    scene="Park",
                    mood="excited",
                    camera="medium shot",
                    characters_present=["Bunny"],
                ),
                StoryPage(
                    page=3,
                    text="What a fun day!",
                    scene="Sunset",
                    mood="happy",
                    camera="wide shot",
                    characters_present=["Bunny"],
                ),
                StoryPage(
                    page=4,
                    text="Goodnight everyone!",
                    scene="Bedroom",
                    mood="peaceful",
                    camera="close up",
                    characters_present=["Bunny"],
                ),
            ],
            continuity=StoryContinuity(
                character_consistency_notes="Bunny always wears blue",
                style_notes_for_images="Watercolor style",
            ),
        )

        result = await moderate_output(story, {0: "cover.png", 1: "page1.png"})
        assert result is True

    @pytest.mark.asyncio
    async def test_moderate_output_unsafe_content(self):
        """Test moderation catches unsafe content."""
        from src.services.orchestrator import moderate_output
        from src.models.dto import (
            StoryDraft,
            StoryPage,
            StoryCover,
            StoryCharacter,
            StoryContinuity,
            Language,
            TargetAge,
        )

        story = StoryDraft(
            title="Story with 폭력",  # Contains forbidden word
            language=Language.ko,
            target_age=TargetAge.a5_7,
            theme="adventure",
            moral="Be kind",
            characters=[
                StoryCharacter(
                    id="char1", name="Character", role="main", brief="A character"
                )
            ],
            cover=StoryCover(
                cover_text="Title", scene="Scene", mood="mood", camera="camera"
            ),
            pages=[
                StoryPage(
                    page=1,
                    text="Page 1 text",
                    scene="Scene",
                    mood="mood",
                    camera="camera",
                    characters_present=["Character"],
                ),
                StoryPage(
                    page=2,
                    text="Page 2 text",
                    scene="Scene",
                    mood="mood",
                    camera="camera",
                    characters_present=["Character"],
                ),
                StoryPage(
                    page=3,
                    text="Page 3 text",
                    scene="Scene",
                    mood="mood",
                    camera="camera",
                    characters_present=["Character"],
                ),
                StoryPage(
                    page=4,
                    text="Page 4 text",
                    scene="Scene",
                    mood="mood",
                    camera="camera",
                    characters_present=["Character"],
                ),
            ],
            continuity=StoryContinuity(
                character_consistency_notes="Notes", style_notes_for_images="Style"
            ),
        )

        result = await moderate_output(story, {})
        assert result is False  # Should catch forbidden word


class TestReplicatePolling:
    """M20/G16: Replicate 폴링 상한이 image_timeout에서 파생(60초 하드코딩 제거)."""

    def test_replicate_poll_derives_from_image_timeout(self):
        import inspect

        from src.services import image as image_module

        src = inspect.getsource(image_module._generate_replicate)
        # 하드코딩 60 폴링 제거, image_timeout 파생.
        assert "range(60)" not in src
        assert "settings.image_timeout" in src
        assert "max_polls" in src
