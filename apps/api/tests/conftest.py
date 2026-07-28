import pytest
import pytest_asyncio
import os
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# 테스트 환경 설정
os.environ["TESTING"] = "true"
# #12: 테스트 DB 파일을 프로세스별로 분리한다. 고정 경로(./test.db)를 공유하면 동시에
# 도는 다른 pytest 프로세스(로컬 병렬 실행·백그라운드 회귀)의 create_all/drop_all이
# 서로의 스키마를 지워 'no such table'로 무작위 실패한다 — GDPR/erasure 회귀 게이트가
# flaky해지는 원인의 절반(나머지 절반인 실 S3 호출은 아래 _block_real_s3가 차단).
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///./test_{os.getpid()}.db"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["IMAGE_PROVIDER"] = "mock"
# IAP 기본값은 운영 안전을 위해 strict(fail-closed)이므로, 테스트는 로컬 검증 모드를
# 명시 주입해 스토어 키 없이도 영수증 흐름을 검증한다(보안 기본값 변경과 한 세트).
os.environ["IAP_VERIFICATION_MODE"] = "local"
# H1/G9: 운영 GA 기본값은 오디오 비활성(audio_feature_enabled=False)이며, 그 구성에서
# 오디오 엔드포인트는 명시적 409(AUDIO_NOT_SUPPORTED)를 반환한다. 오디오 엔드포인트를
# 통해 '다른' 동작(404·무료플랜 게이트 등)을 검증하는 테스트가 그 게이트에 걸리지 않도록
# 테스트 환경은 '오디오 라이브'로 선언한다. 게이트 자체는 플래그를 끄는
# test_audio_feature_gate.py가 검증한다(프로덕션 코드에 테스트 특례를 두지 않음).
os.environ["AUDIO_FEATURE_ENABLED"] = "true"
os.environ["TTS_PROVIDER"] = "google"
os.environ["GOOGLE_TTS_API_KEY"] = "test-tts-key"
os.environ["STT_PROVIDER"] = "openai"
# S3 credentials for testing (mock values)
os.environ["S3_ACCESS_KEY"] = "test-access-key"
os.environ["S3_SECRET_KEY"] = "test-secret-key"

from src.main import app
from src.core.database import get_db
from src.models.db import Base


# 테스트용 DB 엔진
TEST_DATABASE_URL = os.environ["DATABASE_URL"]
_TEST_DB_FILE = TEST_DATABASE_URL.replace("sqlite+aiosqlite:///", "")
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)


# SQLite는 기본적으로 FK를 강제하지 않는다. 운영 Postgres와 동치를 만들어 FK 위반
# (책 삭제 시 자식 행 누락 등)을 테스트가 잡도록 PRAGMA foreign_keys=ON 을 강제한다.
@event.listens_for(test_engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
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
    """Test user key (UUID format)."""
    return "550e8400-e29b-41d4-a716-446655440000"


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


# ── #12: 테스트에서 실 S3(boto3) 네트워크 호출 차단 ─────────────────────────────
# erasure/삭제 테스트 다수가 storage를 mock하지 않아 실제 boto3가 localhost:9000으로
# 나갔고(런당 수십 초 지연), 그 타이밍이 테스트 경계를 넘어 GDPR 회귀 게이트가 flaky해졌다
# (실행마다 다른 테스트가 실패). S3 클라이언트 팩토리만 인메모리 페이크로 대체해
# 키 계산·페이지네이션·에러 처리 등 storage 실로직은 그대로 통과시킨다.
class _FakeS3Client:
    def __init__(self):
        self.objects: dict = {}

    def head_bucket(self, **kwargs):
        return {}

    def create_bucket(self, **kwargs):
        return {}

    def put_object(self, **kwargs):
        self.objects[kwargs.get("Key")] = kwargs.get("Body", b"")
        return {}

    def get_object(self, **kwargs):
        key = kwargs.get("Key")
        if key not in self.objects:
            raise KeyError(key)
        body = self.objects[key]

        class _Body:
            def read(self_inner):
                return body

        return {"Body": _Body(), "ContentType": "application/octet-stream"}

    def list_objects_v2(self, **kwargs):
        prefix = kwargs.get("Prefix", "")
        keys = [k for k in self.objects if k.startswith(prefix)]
        if not keys:
            return {"KeyCount": 0}
        return {
            "KeyCount": len(keys),
            "Contents": [{"Key": k} for k in keys],
            "IsTruncated": False,
        }

    def delete_objects(self, **kwargs):
        deleted = []
        for obj in (kwargs.get("Delete") or {}).get("Objects", []):
            self.objects.pop(obj["Key"], None)
            deleted.append(obj)
        return {"Deleted": deleted}


@pytest.fixture(autouse=True)
def _block_real_s3(monkeypatch, request):
    """실 S3 호출 차단(기본). 실제 S3가 필요한 테스트는 @pytest.mark.real_s3로 예외."""
    if request.node.get_closest_marker("real_s3"):
        return
    fake = _FakeS3Client()
    monkeypatch.setattr("src.services.storage.get_s3_client", lambda: fake)
    return fake


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_db_file():
    """프로세스별 테스트 DB 파일을 세션 종료 시 정리(작업 디렉터리 오염 방지)."""
    yield
    try:
        path = _TEST_DB_FILE.lstrip("./")
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
