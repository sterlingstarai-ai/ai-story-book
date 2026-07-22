"""
Image Generation Service: 이미지 생성 API 연동
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from contextvars import ContextVar
import uuid

import httpx
import asyncio
import structlog

from src.core.config import settings
from src.core.errors import ImageError, ErrorCode
from src.models.dto import ImagePrompt

logger = structlog.get_logger()

# 영속화될 이미지의 스토리지 키 접두를 호출 스코프에서 지정한다. 기본(None)이면
# `images/{provider}/{uuid}`(추적 불가 경로)에 저장되지만, 캐릭터 시트처럼 삭제 가능해야
# 하는 산출물은 image_storage_scope("characters/{id}/sheets")로 감싸 삭제 경로가 닿게 한다.
_storage_key_prefix: ContextVar[str | None] = ContextVar("_storage_key_prefix", default=None)


@contextmanager
def image_storage_scope(prefix: str | None):
    """이 블록에서 생성·영속화되는 이미지의 S3 키 접두를 지정한다(async-task 안전)."""
    token = _storage_key_prefix.set(prefix)
    try:
        yield
    finally:
        _storage_key_prefix.reset(token)


def _make_image_key(provider: str, ext: str) -> str:
    prefix = _storage_key_prefix.get()
    if prefix:
        return f"{prefix.rstrip('/')}/{uuid.uuid4().hex}.{ext}"
    return f"images/{provider}/{uuid.uuid4().hex}.{ext}"


async def generate_image(
    prompt: ImagePrompt, reference_image_url: str | None = None
) -> str:
    """
    Generate image from prompt.

    reference_image_url: 아이 얼굴 사진(또는 캐릭터 원본) URL. 얼굴 보존을 지원하는
    provider(gemini)에서 주인공 얼굴을 모든 페이지에 동화체로 일관 반영하는 데 쓰인다.
    미지원 provider는 무시한다.

    Returns:
        Image URL
    """
    if settings.image_provider == "openai":
        return await _generate_openai(prompt)
    elif settings.image_provider == "gemini":
        return await _generate_gemini(prompt, reference_image_url)
    elif settings.image_provider == "replicate":
        return await _generate_replicate(prompt)
    elif settings.image_provider == "fal":
        return await _generate_fal(prompt)
    elif settings.image_provider == "mock":
        return await _generate_mock(prompt)
    else:
        raise ValueError(f"Unknown image provider: {settings.image_provider}")


def supports_inpaint() -> bool:
    """현재 이미지 제공자가 마스크 기반 인페인트(부분 재생성)를 지원하는가.

    Replicate(SDXL: image+mask 입력)와 FAL만 지원. openai/gemini/mock은 미지원이라
    부분 재생성 대신 전체 페이지 재생성으로 폴백해야 한다.
    """
    return settings.image_provider in ("replicate", "fal")


async def _generate_openai(prompt: ImagePrompt) -> str:
    """Generate image using OpenAI DALL-E API (gpt-image-1 / dall-e-3)"""
    if not settings.image_api_key:
        raise ImageError(
            ErrorCode.IMAGE_FAILED,
            "OpenAI API 키가 설정되지 않았습니다. IMAGE_API_KEY 환경 변수를 설정해주세요.",
            page=prompt.page,
        )

    # dall-e-3는 b64_json을 명시 요청(URL 모드는 ~1시간 후 만료). gpt-image-1은 항상
    # b64_json을 반환하며 response_format/quality 파라미터를 거부하므로 보내지 않는다.
    json_body = {
        "model": settings.image_model,
        "prompt": prompt.positive_prompt,
        "n": 1,
        "size": _get_openai_size(prompt.aspect_ratio),
    }
    if settings.image_model.startswith("dall-e"):
        json_body["response_format"] = "b64_json"
        json_body["quality"] = "standard"

    async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
        response = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {settings.image_api_key}",
                "Content-Type": "application/json",
            },
            json=json_body,
        )

        if response.status_code == 429:
            logger.warning("OpenAI rate limit hit", page=prompt.page)
            raise ImageError(
                ErrorCode.IMAGE_RATE_LIMIT,
                "OpenAI API 요청 한도 초과",
                page=prompt.page,
            )

        if response.status_code != 200:
            logger.error(
                "OpenAI Image API error",
                status=response.status_code,
                body_length=len(response.text or ""),
            )
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"OpenAI Image API error: {response.status_code}",
                page=prompt.page,
            )

        try:
            result = response.json()
        except Exception:
            raise ImageError(
                ErrorCode.IMAGE_FAILED, "Invalid JSON from OpenAI Image API", page=prompt.page
            )

        data = result.get("data", [])
        if data:
            # b64_json(gpt-image-1·요청한 dall-e) 우선, 없으면 url 폴백 — 어느 쪽이든 S3 영속화.
            b64 = data[0].get("b64_json")
            if b64:
                return await _persist_image_bytes(
                    base64.b64decode(b64), "image/png", "openai"
                )
            url = data[0].get("url")
            if url:
                return await _persist_external_url(url, "openai", prompt.page)

        raise ImageError(
            ErrorCode.IMAGE_FAILED, "No output from OpenAI Image", page=prompt.page
        )


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


async def _fetch_image_as_base64(url: str) -> tuple[str, str] | None:
    """레퍼런스 이미지 URL → (base64, mime_type). 실패 시 None(얼굴보존 없이 진행)."""
    from src.services.storage import _is_url_allowed

    # 스토리지 이미지 다운로드와 동일한 SSRF 가드(사설/메타데이터 IP·비http 차단, fail-closed).
    if not _is_url_allowed(url):
        logger.warning("reference image URL blocked by SSRF protection", url=url[:100])
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
            return base64.b64encode(resp.content).decode("ascii"), mime
    except Exception as e:  # pragma: no cover - 방어적
        logger.warning("reference image fetch failed", error=str(e))
        return None


async def _generate_gemini(
    prompt: ImagePrompt, reference_image_url: str | None = None
) -> str:
    """Gemini 이미지 생성(Nano Banana Pro / gemini-3-pro-image-preview).

    reference_image_url 이 있으면 아이 얼굴을 inline 레퍼런스로 넣어 모든 페이지에
    같은 아이 얼굴을 동화체로 보존한다. 생성 이미지는 스토리지에 업로드 후 URL 반환.
    """
    if not settings.image_api_key:
        raise ImageError(
            ErrorCode.IMAGE_FAILED,
            "Gemini API 키가 설정되지 않았습니다. IMAGE_API_KEY 환경 변수를 설정해주세요.",
            page=prompt.page,
        )

    parts: list[dict] = []
    if reference_image_url:
        fetched = await _fetch_image_as_base64(reference_image_url)
        if fetched:
            ref_b64, ref_mime = fetched
            parts.append(
                {"text": "아래 사진 속 아이의 얼굴 생김새(눈·코·머리·피부)를 유지하되, 동화 그림책 일러스트 스타일로 그려라. 실사 사진이 아니라 따뜻한 동화 삽화로 변환한다."}
            )
            parts.append({"inline_data": {"mime_type": ref_mime, "data": ref_b64}})
    parts.append({"text": prompt.positive_prompt})

    body = {
        "contents": [{"parts": parts}],
        # Gemini 이미지 모델은 멀티모달이라 TEXT+IMAGE를 함께 요청해야 한다
        # (["IMAGE"] 단독은 공식 plain-generation 규약과 어긋나 이미지 미생성 위험).
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }

    async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
        response = await client.post(
            f"{_GEMINI_BASE_URL}/{settings.image_model}:generateContent",
            params={"key": settings.image_api_key},
            headers={"Content-Type": "application/json"},
            json=body,
        )

        if response.status_code == 429:
            logger.warning("Gemini rate limit hit", page=prompt.page)
            raise ImageError(
                ErrorCode.IMAGE_RATE_LIMIT, "Gemini API 요청 한도 초과", page=prompt.page
            )
        if response.status_code != 200:
            logger.error("Gemini Image API error", status=response.status_code)
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"Gemini Image API error: {response.status_code}",
                page=prompt.page,
            )

        try:
            result = response.json()
        except Exception:
            raise ImageError(
                ErrorCode.IMAGE_FAILED, "Invalid JSON from Gemini", page=prompt.page
            )

    image_bytes, mime = _extract_gemini_image(result)
    if image_bytes is None:
        raise ImageError(
            ErrorCode.IMAGE_FAILED, "No image in Gemini response", page=prompt.page
        )

    return await _persist_image_bytes(image_bytes, mime, "gemini")


_IMAGE_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
}


async def _persist_image_bytes(image_bytes: bytes, mime: str, provider: str) -> str:
    """생성된 이미지 바이트를 S3에 영속화하고 공개 URL 반환.

    provider가 돌려준 임시(만료성) URL을 그대로 DB에 저장하면 수 시간 뒤 404가 되므로,
    모든 실 provider 산출물은 S3로 재업로드해 영구 URL로 만든다(gemini와 동일 패턴).
    """
    from src.services.storage import storage_service

    ext = _IMAGE_MIME_EXT.get(mime.split(";")[0].lower().strip(), "png")
    key = _make_image_key(provider, ext)
    return await storage_service.upload_bytes(image_bytes, key, content_type=mime)


async def _persist_external_url(url: str, provider: str, page: int) -> str:
    """provider의 임시 이미지 URL을 다운로드해 S3로 영속화(만료 방지). SSRF 가드 적용."""
    from src.services.storage import _is_url_allowed

    if not url:
        raise ImageError(
            ErrorCode.IMAGE_FAILED, f"Empty image URL from {provider}", page=page
        )
    if not _is_url_allowed(url):
        logger.warning("generated image URL blocked by SSRF protection", url=url[:100])
        raise ImageError(
            ErrorCode.IMAGE_FAILED, f"Image URL not allowed from {provider}", page=page
        )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"Failed to download {provider} image: {resp.status_code}",
                page=page,
            )
        mime = resp.headers.get("content-type", "image/png").split(";")[0]
        return await _persist_image_bytes(resp.content, mime, provider)


def _extract_gemini_image(result: dict) -> tuple[bytes | None, str]:
    """Gemini 응답에서 첫 inline_data 이미지(base64) 추출 → (bytes, mime)."""
    for candidate in result.get("candidates", []) or []:
        content = candidate.get("content", {}) or {}
        for part in content.get("parts", []) or []:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and inline.get("data"):
                mime = inline.get("mime_type") or inline.get("mimeType") or "image/png"
                try:
                    return base64.b64decode(inline["data"]), mime
                except Exception:
                    return None, mime
    return None, "image/png"


def _get_openai_size(aspect_ratio: str) -> str:
    """Get OpenAI DALL-E size string"""
    # DALL-E 3 지원 사이즈: 1024x1024, 1024x1792, 1792x1024
    sizes = {
        "1:1": "1024x1024",
        "3:4": "1024x1792",  # Portrait (세로)
        "4:3": "1792x1024",  # Landscape (가로)
        "9:16": "1024x1792",  # Portrait
        "16:9": "1792x1024",  # Landscape
    }
    return sizes.get(aspect_ratio, "1024x1792")


async def _generate_replicate(prompt: ImagePrompt) -> str:
    """Generate image using Replicate API (Flux/SDXL)"""
    if not settings.image_api_key:
        raise ImageError(
            ErrorCode.IMAGE_FAILED,
            "Replicate API 키가 설정되지 않았습니다. IMAGE_API_KEY 환경 변수를 설정해주세요.",
            page=prompt.page,
        )

    async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
        # Create prediction
        response = await client.post(
            "https://api.replicate.com/v1/predictions",
            headers={
                "Authorization": f"Token {settings.image_api_key}",
                "Content-Type": "application/json",
            },
            json={
                # Using SDXL model
                "version": "39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
                "input": {
                    "prompt": prompt.positive_prompt,
                    "negative_prompt": prompt.negative_prompt,
                    "seed": prompt.seed,
                    "width": _get_width(prompt.aspect_ratio),
                    "height": _get_height(prompt.aspect_ratio),
                    "num_outputs": 1,
                    "guidance_scale": 7.5,
                    "num_inference_steps": 30,
                    # 인페인트: base 이미지 + 마스크가 있으면 마스크 영역만 재생성
                    # (SDXL은 image/mask 입력으로 인페인트 지원). 없으면 일반 생성.
                    **(
                        {"image": prompt.base_image_url, "mask": prompt.mask_url}
                        if prompt.base_image_url and prompt.mask_url
                        else {}
                    ),
                },
            },
        )

        if response.status_code != 201:
            logger.error(
                "Replicate create error",
                status=response.status_code,
                body_length=len(response.text or ""),
            )
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"Replicate API error: {response.status_code}",
                page=prompt.page,
            )

        try:
            prediction = response.json()
        except Exception:
            raise ImageError(
                ErrorCode.IMAGE_FAILED, "Invalid JSON from Replicate API", page=prompt.page
            )
        prediction_id = prediction.get("id")
        if not prediction_id:
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                "Replicate API response missing 'id' field",
                page=prompt.page,
            )

        # Poll for completion.
        # M20/G16: 폴링 상한을 image_timeout에서 파생(하드코딩 60초 제거) — 60~90초에
        # 정상 완료되는 예측이 IMAGE_TIMEOUT으로 조기 실패하던 스펙(90초) 불일치 해소.
        max_polls = max(1, int(settings.image_timeout))
        for _ in range(max_polls):  # 1 attempt per second, up to image_timeout
            await asyncio.sleep(1)

            poll_response = await client.get(
                f"https://api.replicate.com/v1/predictions/{prediction_id}",
                headers={"Authorization": f"Token {settings.image_api_key}"},
            )

            if poll_response.status_code != 200:
                continue

            try:
                result = poll_response.json()
            except Exception:
                continue
            status = result.get("status")

            if status == "succeeded":
                output = result.get("output", [])
                if output:
                    # Replicate delivery URL은 단기 만료 → S3로 영속화.
                    return await _persist_external_url(
                        output[0], "replicate", prompt.page
                    )
                raise ImageError(
                    ErrorCode.IMAGE_FAILED, "No output from Replicate", page=prompt.page
                )

            elif status == "failed":
                error = result.get("error", "Unknown error")
                raise ImageError(
                    ErrorCode.IMAGE_FAILED,
                    f"Replicate failed: {error}",
                    page=prompt.page,
                )

        raise ImageError(
            ErrorCode.IMAGE_TIMEOUT, "Replicate prediction timeout", page=prompt.page
        )


async def _generate_fal(prompt: ImagePrompt) -> str:
    """Generate image using FAL.ai API"""
    if not settings.image_api_key:
        raise ImageError(
            ErrorCode.IMAGE_FAILED,
            "FAL API 키가 설정되지 않았습니다. IMAGE_API_KEY 환경 변수를 설정해주세요.",
            page=prompt.page,
        )

    # 인페인트: base 이미지 + 마스크가 있으면 마스크 영역만 재생성(별도 엔드포인트).
    is_inpaint = bool(prompt.base_image_url and prompt.mask_url)
    endpoint = (
        settings.image_inpaint_fal_endpoint
        if is_inpaint
        else "https://fal.run/fal-ai/flux/schnell"
    )
    payload = {
        "prompt": prompt.positive_prompt,
        "image_size": _get_fal_size(prompt.aspect_ratio),
        "num_inference_steps": 4,
        "seed": prompt.seed,
        "num_images": 1,
        "enable_safety_checker": True,
    }
    if is_inpaint:
        payload["image_url"] = prompt.base_image_url
        payload["mask_url"] = prompt.mask_url

    async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
        response = await client.post(
            endpoint,
            headers={
                "Authorization": f"Key {settings.image_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        if response.status_code != 200:
            logger.error(
                "FAL API error",
                status=response.status_code,
                body_length=len(response.text or ""),
            )
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"FAL API error: {response.status_code}",
                page=prompt.page,
            )

        try:
            result = response.json()
        except Exception:
            raise ImageError(
                ErrorCode.IMAGE_FAILED, "Invalid JSON from FAL API", page=prompt.page
            )

        images = result.get("images", [])
        if images:
            # FAL media URL은 단기 만료 → S3로 영속화.
            return await _persist_external_url(
                images[0].get("url", ""), "fal", prompt.page
            )

        raise ImageError(ErrorCode.IMAGE_FAILED, "No output from FAL", page=prompt.page)


async def _generate_mock(prompt: ImagePrompt) -> str:
    """Mock image generation for testing"""
    await asyncio.sleep(0.5)  # Simulate API delay
    return f"https://picsum.photos/seed/{prompt.seed}/768/1024"


def _get_width(aspect_ratio: str) -> int:
    """Get width for aspect ratio"""
    ratios = {
        "1:1": 1024,
        "3:4": 768,
        "4:3": 1024,
        "9:16": 576,
    }
    return ratios.get(aspect_ratio, 768)


def _get_height(aspect_ratio: str) -> int:
    """Get height for aspect ratio"""
    ratios = {
        "1:1": 1024,
        "3:4": 1024,
        "4:3": 768,
        "9:16": 1024,
    }
    return ratios.get(aspect_ratio, 1024)


def _get_fal_size(aspect_ratio: str) -> str:
    """Get FAL size string"""
    sizes = {
        "1:1": "square_hd",
        "3:4": "portrait_4_3",
        "4:3": "landscape_4_3",
        "9:16": "portrait_16_9",
    }
    return sizes.get(aspect_ratio, "portrait_4_3")
