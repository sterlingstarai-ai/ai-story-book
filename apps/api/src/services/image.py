"""
Image Generation Service: 이미지 생성 API 연동
"""

from __future__ import annotations

import base64
import uuid

import httpx
import asyncio
import structlog

from src.core.config import settings
from src.core.errors import ImageError, ErrorCode
from src.models.dto import ImagePrompt

logger = structlog.get_logger()


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


async def _generate_openai(prompt: ImagePrompt) -> str:
    """Generate image using OpenAI DALL-E API (gpt-image-1 / dall-e-3)"""
    if not settings.image_api_key:
        raise ImageError(
            ErrorCode.IMAGE_FAILED,
            "OpenAI API 키가 설정되지 않았습니다. IMAGE_API_KEY 환경 변수를 설정해주세요.",
            page=prompt.page,
        )

    async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
        # DALL-E 3 API 호출
        response = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {settings.image_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.image_model,
                "prompt": prompt.positive_prompt,
                "n": 1,
                "size": _get_openai_size(prompt.aspect_ratio),
                "quality": "standard",
                "response_format": "url",
            },
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
            return data[0].get("url", "")

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

    from src.services.storage import storage_service

    ext = _IMAGE_MIME_EXT.get(mime.split(";")[0].lower().strip(), "png")
    key = f"images/gemini/{uuid.uuid4().hex}.{ext}"
    return await storage_service.upload_bytes(image_bytes, key, content_type=mime)


_IMAGE_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
}


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

        # Poll for completion
        for _ in range(60):  # Max 60 attempts (1 per second)
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
                    return output[0]
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

    async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
        response = await client.post(
            "https://fal.run/fal-ai/flux/schnell",
            headers={
                "Authorization": f"Key {settings.image_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt.positive_prompt,
                "image_size": _get_fal_size(prompt.aspect_ratio),
                "num_inference_steps": 4,
                "seed": prompt.seed,
                "num_images": 1,
                "enable_safety_checker": True,
            },
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
            return images[0].get("url", "")

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
