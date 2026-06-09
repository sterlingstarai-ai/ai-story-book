from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


API_ROOT = Path(__file__).resolve().parents[2]
API_ENV_FILE = API_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(API_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "AI Story Book API"
    # 기본값을 커밋된 OpenAPI 계약·.env와 일치시켜, .env 부재(CI Phase Gate)에서도
    # info.version이 흔들리지 않게 한다(계약 테스트 환경 비의존).
    app_version: str = "0.2.0"
    debug: bool = False  # Must be False in production
    testing: bool = False  # Set to True in test environment

    # Database
    # SECURITY: No default - must be set via environment variable
    database_url: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # S3/Minio
    # SECURITY: No defaults for credentials - must be set via environment
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "storybook"
    s3_public_url: str = "http://localhost:9000/storybook"

    # LLM
    llm_provider: str = "openai"  # openai, anthropic
    llm_api_key: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout: int = 30

    # Image Generation
    image_provider: str = "openai"  # openai, gemini, replicate, fal, mock
    image_api_key: Optional[str] = None
    # dall-e-3, gpt-image-1, gemini-3-pro-image-preview(Nano Banana Pro, 얼굴보존)
    image_model: str = "dall-e-3"
    image_timeout: int = 90
    image_max_concurrent: int = 3
    image_max_retries: int = 3  # Maximum retries for image generation

    # TTS (Text-to-Speech)
    tts_provider: str = "mock"  # mock, google, elevenlabs
    google_tts_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # STT (Speech-to-Text)
    stt_provider: str = "mock"  # mock, openai, google
    stt_api_key: Optional[str] = None
    stt_model: str = "whisper-1"
    google_stt_api_key: Optional[str] = None

    # IAP Verification
    # - local: 로컬 검증(개발/테스트)
    # - hybrid: 키가 있으면 스토어 실검증, 없으면 로컬 검증
    # - strict: 스토어 실검증 필수(키 없거나 검증 실패 시 에러)
    iap_verification_mode: str = "local"
    apple_iap_shared_secret: Optional[str] = None
    apple_iap_verify_url: str = "https://buy.itunes.apple.com/verifyReceipt"
    apple_iap_sandbox_verify_url: str = "https://sandbox.itunes.apple.com/verifyReceipt"
    google_play_package_name: Optional[str] = None
    google_play_access_token: Optional[str] = None
    google_play_service_account_json: Optional[str] = None
    google_play_service_account_file: Optional[str] = None
    google_play_verify_base_url: str = "https://androidpublisher.googleapis.com"

    # POD (Print-on-Demand)
    # - local: 로컬 주문 생성/조회만 수행
    # - hybrid: 설정이 있으면 외부 POD API 동기화, 없거나 실패 시 로컬 폴백
    # - strict: 외부 POD API 동기화 필수
    pod_mode: str = "local"
    pod_provider: str = "printful"
    printful_api_key: Optional[str] = None
    printful_store_id: Optional[str] = None
    printful_sync_variant_id: Optional[int] = None
    printful_base_url: str = "https://api.printful.com"

    # Rate Limiting
    rate_limit_requests: int = 10
    rate_limit_window: int = 60  # seconds
    # 테스트에선 시간 기반 리미터가 실행 속도에 따라 플래키하게 429를 내므로 기본 우회.
    # 레이트리밋 자체를 검증하는 테스트만 이 플래그를 켠다(consent 게이트와 동일 패턴).
    rate_limit_enforce_in_testing: bool = False

    # Job Settings
    job_max_retries: int = 3
    job_sla_seconds: int = 600  # 10 minutes
    use_celery: bool = False  # Use Celery for background tasks (True for production)

    # Guardrails
    daily_job_limit_per_user: int = 20  # Max jobs per user per day
    max_pending_jobs: int = 100  # Max pending jobs in queue before rejecting

    # Free plan enforcement
    free_plan_enforcement_enabled: bool = True
    free_plan_enforce_in_testing: bool = False
    free_plan_monthly_book_limit: int = 2

    # Parental consent enforcement (PIPA/COPPA) — gates child photo/face data collection
    require_parental_consent_enabled: bool = True
    require_parental_consent_in_testing: bool = False
    consent_current_version: str = "v2"

    # 결제/보안: 운영에선 검증된 IAP 영수증만으로 구독을 열어야 한다.
    # False면 /v1/credits/subscribe의 유료플랜 직접 크레딧 지급을 차단(테스트는 우회).
    allow_unverified_subscribe: bool = False
    # 설정 시 IAP 웹훅에 ?token= 일치를 요구(미설정=무검증 — 운영에선 반드시 설정).
    iap_webhook_secret: str = ""

    # Admin
    admin_api_key: str = ""  # MUST be set in production for /credits/add

    # CORS
    cors_origins: str = (
        ""  # Comma-separated origins, MUST be set explicitly in production
    )

settings = Settings()
