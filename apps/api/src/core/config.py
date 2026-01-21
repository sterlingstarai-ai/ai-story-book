from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    app_name: str = "AI Story Book API"
    app_version: str = "0.1.0"
    debug: bool = True

    # Database
    database_url: str = "postgresql://storybook:storybook123@localhost:5432/storybook"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # S3/Minio
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin123"
    s3_bucket: str = "storybook"
    s3_public_url: str = "http://localhost:9000/storybook"

    # LLM
    llm_provider: str = "openai"  # openai, anthropic
    llm_api_key: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout: int = 30

    # Image Generation
    image_provider: str = "replicate"  # replicate, fal
    image_api_key: Optional[str] = None
    image_timeout: int = 90
    image_max_concurrent: int = 3
    image_max_retries: int = 3  # Maximum retries for image generation

    # TTS (Text-to-Speech)
    tts_provider: str = "mock"  # mock, google, elevenlabs
    google_tts_api_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # Rate Limiting
    rate_limit_requests: int = 10
    rate_limit_window: int = 60  # seconds

    # Job Settings
    job_max_retries: int = 3
    job_sla_seconds: int = 600  # 10 minutes
    use_celery: bool = False  # Use Celery for background tasks (True for production)

    # Guardrails
    daily_job_limit_per_user: int = 20  # Max jobs per user per day
    max_pending_jobs: int = 100  # Max pending jobs in queue before rejecting

    # CORS
    cors_origins: str = "*"  # Comma-separated origins or "*" for all

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
