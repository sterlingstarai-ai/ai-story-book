from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


API_ROOT = Path(__file__).resolve().parents[2]
API_ENV_FILE = API_ROOT / ".env"

# 앱 버전은 코드가 정본(GA 1.0.0 통일). APP_VERSION env·구버전 .env 잔재가 런타임
# info.version을 흔들어 계약 신선도 테스트를 소음화하지 않도록, pydantic 필드가 아니라
# 모듈 상수 + property로 노출해 env 오버라이드 대상에서 제외한다(M8).
APP_VERSION = "1.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(API_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "AI Story Book API"
    debug: bool = False  # Must be False in production

    @property
    def app_version(self) -> str:
        """코드 정본 버전(APP_VERSION env로 오버라이드 불가)."""
        return APP_VERSION
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
    # 인페인트(부분 재생성) — replicate(SDXL, image+mask 입력 지원) / fal에서만 동작.
    # FAL 인페인트 엔드포인트(배포 환경에서 확정 가능, 기본값 overridable).
    image_inpaint_fal_endpoint: str = "https://fal.run/fal-ai/flux-lora/inpainting"

    # 오디오(낭독·발음) 기능 플래그 — G9: GA에서 명시적 비활성으로 출시(원격 config로 전환).
    # False면 /health/ready가 TTS/STT 라이브 구성을 게이트하지 않는다(기능이 꺼져 있으므로).
    audio_feature_enabled: bool = False

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
    # 기본값은 fail-closed(strict) — 위조 영수증이 무검증으로 통과하지 않게 한다.
    # 개발/테스트는 명시적으로 local을 설정(conftest는 IAP_VERIFICATION_MODE=local 주입).
    iap_verification_mode: str = "strict"
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
    # 앱스토어 리뷰/TestFlight 심사용 Sandbox 영수증을 운영에서 지급 허용할 상품 id 목록
    # (콤마 구분). 이 목록 외 Sandbox 영수증은 운영에서 지급 차단(L10/G8).
    review_sandbox_allowlist: str = ""

    # 공유 링크 기본 도메인(예: https://share.aistorybook.app). 미설정 시 요청 호스트에서 구성.
    share_base_url: str = ""
    # 공유 링크 기본 유효기간(일). 부모가 만든 공개 링크는 만료·철회 가능.
    share_default_expiry_days: int = 30

    # Admin
    admin_api_key: str = ""  # MUST be set in production for /credits/add

    # CORS
    cors_origins: str = (
        ""  # Comma-separated origins, MUST be set explicitly in production
    )

settings = Settings()
