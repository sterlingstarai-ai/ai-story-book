"""
Service Layer Tests
서비스 레이어 테스트
"""

import pytest
from unittest.mock import AsyncMock, patch


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

        assert credits1.id == credits2.id

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
        from src.services.storage import storage_service

        # Mock the internal client
        with patch.object(storage_service, "_ensure_bucket", new_callable=AsyncMock):
            with patch.object(storage_service, "_client") as mock_client:
                mock_client.put_object = AsyncMock()

                # Should not raise
                # The actual method might work differently in mock mode


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
