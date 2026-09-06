"""Inspect one generated portrait before offering it for parental approval."""

import asyncio
import base64
from io import BytesIO
from typing import Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core.config import settings
from src.core.errors import ErrorCode, ImageError
from src.services.illustration_diagnostics import record_illustration_diagnostic
from src.services.openai_contract import request_openai_json
from src.services.photo_processing import ensure_photo_processing_ready
from src.services.storage import get_object_bytes, key_from_public_url


class AvatarIllustrationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issues: list[Literal[
        "readable_text", "multiple_characters", "malformed_character",
        "unsafe_depiction", "photographic_rendering", "uncertain",
    ]] = Field(max_length=6)


async def verify_avatar_illustration(url: str) -> None:
    ensure_photo_processing_ready()
    key = key_from_public_url(url)
    if not key:
        raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "캐릭터 그림을 확인할 수 없습니다.")
    if settings.image_provider == "mock":
        return  # Explicit local structural test; no live visual-quality claim.
    data, mime = await get_object_bytes(key)
    mime = mime.split(";")[0]
    failure = ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "캐릭터 그림이 검사를 통과하지 못했습니다. 다시 만들어주세요.")
    if not data or len(data) > 8 * 1024 * 1024 or mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise failure
    try:
        with Image.open(BytesIO(data)) as picture:
            if picture.width * picture.height > 16_777_216 or getattr(picture, "is_animated", False):
                raise failure
            picture.verify()
        raw = await asyncio.wait_for(request_openai_json(
            model=settings.llm_model, api_key=settings.llm_api_key, timeout=45,
            system_prompt=(
                "Review a generated standalone storybook character portrait, not a source photo. "
                "Report readable text/letters/instructions/logos, multiple or duplicated characters, "
                "clearly malformed or extra body parts, unsafe/sexual/graphic content, or an unreadable "
                "image. Report photographic_rendering when the face or body looks like a photograph, "
                "a photographic cutout, or a photo merely covered with watercolor/paint texture. "
                "Paper texture or a painted background alone does not make a photographic face "
                "acceptable. The character itself must use clearly simplified illustrated shapes. "
                "Accept stylized hand-drawn, watercolor, crayon, cartoon, pixel, painterly, clay or "
                "toy-like 3D illustration; do not require every medium to have outlines or paper. "
                "Do not penalize normal cartoon stylization or infer identity or likeness. "
                "The expected image is one friendly clothed character with a simple blank background. "
                "Return issues=[] only if no listed defect is visible. Return only the supplied schema."
            ),
            user_prompt="Inspect the generated character illustration before the parent sees it.",
            max_tokens=512,
            image_urls=[f"data:{mime};base64," + base64.b64encode(data).decode("ascii")],
            response_schema=AvatarIllustrationReview.model_json_schema(),
        ), timeout=45)
        if not isinstance(raw, str) or len(raw) > 4096:
            raise failure
        review = AvatarIllustrationReview.model_validate_json(raw)
        if review.issues:
            record_illustration_diagnostic(
                "avatar_findings", "findings", error_code=ErrorCode.IMAGE_QUALITY_FAILED,
                issue_counts=dict.fromkeys(review.issues, 1),
            )
            raise failure
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, ValidationError,
            Image.DecompressionBombError, TimeoutError):
        raise failure from None
