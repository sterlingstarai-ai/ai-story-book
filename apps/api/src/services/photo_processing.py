"""One explicit gate for every photo-derived AI operation.

The deployment operator verifies provider/data-retention requirements before
enabling this feature. No account status is inferred from an API key or flag.
"""

from src.core.config import settings
from src.core.exceptions import APIError


def ensure_photo_processing_ready() -> None:
    providers = (
        settings.photo_analysis_provider,
        settings.image_provider,
        settings.llm_provider,
    )
    if providers == ("mock", "mock", "mock"):
        return
    from src.services.image_quality import review_provider_configured

    if not (
        settings.photo_processing_enabled
        and providers == ("openai", "openai", "openai")
        and settings.photo_analysis_api_key
        and settings.photo_analysis_model
        and settings.image_api_key
        and settings.image_model.startswith("gpt-image-")
        and settings.llm_api_key
        and settings.illustration_quality_enabled
        and review_provider_configured()
    ):
        raise APIError(
            status_code=503,
            error_code="PHOTO_PROCESSING_UNAVAILABLE",
            message="사진 캐릭터 서비스를 준비 중입니다. 잠시 후 다시 시도해주세요.",
        )
