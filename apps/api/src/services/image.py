"""
Image Generation Service: 이미지 생성 API 연동
"""

import httpx
import asyncio
import structlog

from src.core.config import settings
from src.core.errors import ImageError, ErrorCode
from src.models.dto import ImagePrompt

logger = structlog.get_logger()


async def generate_image(prompt: ImagePrompt) -> str:
    """
    Generate image from prompt

    Returns:
        Image URL
    """
    if settings.image_provider == "replicate":
        return await _generate_replicate(prompt)
    elif settings.image_provider == "fal":
        return await _generate_fal(prompt)
    elif settings.image_provider == "mock":
        return await _generate_mock(prompt)
    else:
        raise ValueError(f"Unknown image provider: {settings.image_provider}")


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
                body=response.text,
            )
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"Replicate API error: {response.status_code}",
                page=prompt.page,
            )

        prediction = response.json()
        prediction_id = prediction["id"]

        # Poll for completion
        for _ in range(60):  # Max 60 attempts (1 per second)
            await asyncio.sleep(1)

            poll_response = await client.get(
                f"https://api.replicate.com/v1/predictions/{prediction_id}",
                headers={"Authorization": f"Token {settings.image_api_key}"},
            )

            if poll_response.status_code != 200:
                continue

            result = poll_response.json()
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
                "FAL API error", status=response.status_code, body=response.text
            )
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"FAL API error: {response.status_code}",
                page=prompt.page,
            )

        result = response.json()
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
