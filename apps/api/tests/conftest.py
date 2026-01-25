import pytest
import pytest_asyncio
import os
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# 테스트 환경 설정
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["IMAGE_PROVIDER"] = "mock"
# S3 credentials for testing (mock values)
os.environ["S3_ACCESS_KEY"] = "test-access-key"
os.environ["S3_SECRET_KEY"] = "test-secret-key"

from src.main import app
from src.core.database import get_db
from src.models.db import Base


# 테스트용 DB 엔진
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database for each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with database session override."""
    from src.services.credits import credits_service

    async def override_get_db():
        yield db_session

    # Mock credits service to always allow
    original_has_credits = credits_service.has_credits
    original_use_credit = credits_service.use_credit

    async def mock_has_credits(*args, **kwargs):
        return True

    async def mock_use_credit(*args, **kwargs):
        return True

    credits_service.has_credits = mock_has_credits
    credits_service.use_credit = mock_use_credit

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Restore original methods
    credits_service.has_credits = original_has_credits
    credits_service.use_credit = original_use_credit
    app.dependency_overrides.clear()


@pytest.fixture
def user_key():
    """Test user key."""
    return "test-user-key-12345678901234567890"


@pytest.fixture
def headers(user_key):
    """Default headers with user key."""
    return {"X-User-Key": user_key}


@pytest.fixture
def valid_book_spec():
    """Valid book specification for testing."""
    return {
        "topic": "토끼가 하늘을 나는 이야기",
        "language": "ko",
        "target_age": "5-7",
        "style": "watercolor",
        "page_count": 8,
        "theme": "감정코칭",
        "forbidden_elements": ["폭력", "공포"],
    }


@pytest.fixture
def valid_character():
    """Valid character data for testing."""
    return {
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


# Mock LLM 응답
@pytest.fixture
def mock_story_response():
    """Mock LLM story generation response."""
    return {
        "title": "하늘을 나는 토끼 토리",
        "pages": [
            {"page_number": 1, "text": "옛날 옛적에 토리라는 토끼가 살았어요."},
            {"page_number": 2, "text": "토리는 하늘을 날고 싶었어요."},
            {"page_number": 3, "text": "어느 날, 마법의 날개를 발견했어요."},
            {"page_number": 4, "text": "토리는 날개를 달고 하늘로 날아올랐어요."},
            {"page_number": 5, "text": "구름 위에서 친구들을 만났어요."},
            {"page_number": 6, "text": "함께 하늘을 날며 놀았어요."},
            {"page_number": 7, "text": "해가 지자 토리는 집으로 돌아왔어요."},
            {"page_number": 8, "text": "토리는 행복한 꿈을 꾸었어요. 끝."},
        ],
        "moral": "꿈을 포기하지 않으면 이루어질 수 있어요.",
    }


@pytest.fixture
def mock_character_sheet():
    """Mock character sheet response."""
    return {
        "name": "토리",
        "master_description": "5~6세 느낌의 귀여운 토끼, 둥근 얼굴, 큰 눈, 갈색 털, 작고 통통한 체형",
        "appearance": {
            "age_visual": "5~6세",
            "face": "둥근 얼굴, 큰 눈, 작은 코",
            "hair": "없음 (토끼)",
            "skin": "부드러운 갈색 털",
            "body": "작고 통통함",
        },
        "clothing": {
            "top": "노란 줄무늬 티셔츠",
            "bottom": "파란 멜빵바지",
            "shoes": "빨간 운동화",
            "accessories": "없음",
        },
        "personality_traits": ["호기심 많은", "용감한", "친절한"],
    }


@pytest.fixture
def mock_image_prompts():
    """Mock image prompts response."""
    return {
        "cover": "A cute brown rabbit named Tori flying in the blue sky with magical wings, watercolor style, soft colors, children's book illustration",
        "pages": [
            "A cute brown rabbit in a cozy burrow, watercolor style",
            "A rabbit looking up at the sky dreaming, watercolor style",
            "A rabbit finding magical glowing wings, watercolor style",
            "A rabbit soaring into the sky with wings, watercolor style",
            "A rabbit meeting cloud friends in the sky, watercolor style",
            "Rabbits playing together in the clouds, watercolor style",
            "A rabbit flying home at sunset, watercolor style",
            "A rabbit sleeping peacefully with a smile, watercolor style",
        ],
    }


@pytest.fixture
def mock_moderation_safe():
    """Mock safe moderation response."""
    return {"is_safe": True, "flags": [], "reason": None}


@pytest.fixture
def mock_moderation_unsafe():
    """Mock unsafe moderation response."""
    return {
        "is_safe": False,
        "flags": ["violence"],
        "reason": "Content contains violent themes inappropriate for children",
    }
