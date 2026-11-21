"""
Image Generation Service: 이미지 생성 API 연동
"""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO
import uuid
import warnings

import httpx
import asyncio
import structlog
from PIL import Image, UnidentifiedImageError

from src.services.generation_consent import post_with_consent
from src.core.config import settings
from src.services.storage import media_url
from src.services.image_request_budget import (
    consume_image_request, defer_image_requests, wait_for_image_cooldown,
)
from src.services.provider_runtime import (
    begin_provider_request, observe_invalid_provider_response, read_provider_response,
    observe_validated_provider_success,
)
from src.services.image_correction import (
    correction_requires_action_edit, correction_scene_reference,
    image_correction_active, provider_prompt_with_correction,
    review_image_repair_active,
)
from src.core.errors import ImageError, ErrorCode, get_backoff
from src.models.dto import ImagePrompt

logger = structlog.get_logger()


async def _observe_image_output(attempt, data: bytes) -> None:
    """Provider readiness requires inspectable bounded image bytes, not just HTTP 2xx."""
    try:
        if not isinstance(data, bytes) or not 0 < len(data) <= 8 * 1024 * 1024:
            raise ValueError('invalid image bytes')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as picture:
                if (picture.format not in {'PNG', 'JPEG', 'WEBP'} or getattr(picture, 'is_animated', False)
                        or min(picture.size) < 1 or max(picture.size) > 8192
                        or picture.width * picture.height > 16_777_216):
                    raise ValueError('invalid image')
                picture.verify()
    except (ValueError, TypeError, OSError, SyntaxError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        await observe_invalid_provider_response(attempt)
        return
    await observe_validated_provider_success(attempt)

# 영속화될 이미지의 스토리지 키 접두를 호출 스코프에서 지정한다. 기본(None)이면
# `images/{provider}/{uuid}`(추적 불가 경로)에 저장되지만, 캐릭터 시트처럼 삭제 가능해야
# 하는 산출물은 image_storage_scope("characters/{id}/sheets")로 감싸 삭제 경로가 닿게 한다.
_storage_key_prefix: ContextVar[str | None] = ContextVar("_storage_key_prefix", default=None)
_portrait_conversion: ContextVar[bool] = ContextVar("_portrait_conversion", default=False)
_book_reference_url: ContextVar[str | None] = ContextVar("book_reference_url", default=None)
_book_image_client: ContextVar[httpx.AsyncClient | None] = ContextVar("book_image_client", default=None)


@dataclass
class _GeneratedCover:
    url: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    image: tuple[bytes, str] | None = None


_generated_cover: ContextVar[_GeneratedCover | None] = ContextVar("generated_cover", default=None)


@asynccontextmanager
async def book_image_connection_scope():
    """Share provider connections for the cover and pages of one job."""
    if settings.image_provider not in {"openai", "gemini"}:
        yield
        return

    async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
        client_token = _book_image_client.set(client)
        try:
            yield
        finally:
            _book_image_client.reset(client_token)


@contextmanager
def generated_cover_download_scope(cover_url: str | None):
    """Cache the validated bytes of one job-owned, text-only cover for its pages."""
    token = _generated_cover.set(_GeneratedCover(cover_url) if cover_url else None)
    try:
        yield
    finally:
        _generated_cover.reset(token)


@asynccontextmanager
async def _image_provider_client():
    client = _book_image_client.get()
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
            yield client


@contextmanager
def image_book_reference_scope(cover_url: str | None):
    """Set one ownership-checked book cover as a bounded, task-local design reference."""
    if cover_url is not None and (not isinstance(cover_url, str) or not cover_url.strip()):
        raise ImageError(ErrorCode.IMAGE_FAILED, "책 그림 참조를 확인할 수 없습니다.")
    token = _book_reference_url.set(cover_url)
    try:
        yield
    finally:
        _book_reference_url.reset(token)


def _reference_urls(primary_url: str | None) -> list[str]:
    """At most two ordered references; a portrait never inherits a book cover."""
    cover = None if _portrait_conversion.get() else _book_reference_url.get()
    return list(dict.fromkeys(url for url in (primary_url, cover) if url))


@contextmanager
def image_storage_scope(prefix: str | None):
    """이 블록에서 생성·영속화되는 이미지의 S3 키 접두를 지정한다(async-task 안전)."""
    token = _storage_key_prefix.set(prefix)
    try:
        yield
    finally:
        _storage_key_prefix.reset(token)


@contextmanager
def portrait_conversion_scope():
    """Only the trusted first-portrait workflow may reinterpret a source's style.

    Approved book references retain the normal fixed-character rules. Neither
    generated prompt text nor caller-supplied guidance notes can select this mode.
    """
    token = _portrait_conversion.set(True)
    try:
        yield
    finally:
        _portrait_conversion.reset(token)


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

    reference_image_url: 소유권을 확인한 승인 캐릭터 참조. 명시된 참조를 읽을 수
    없거나 제공자가 지원하지 않으면 참조 없이 생성하지 않는다.

    Returns:
        Image URL
    """
    prompt = provider_prompt_with_correction(
        prompt, use_cast_looks=bool(_book_reference_url.get()) and supports_image_reference(),
    )
    if not _portrait_conversion.get() and settings.image_provider in {"openai", "gemini"}:
        # The generated page anchors compatible scene design; an action edit
        # may change its pose/state. Identity/cast repairs keep the approved avatar.
        reference_image_url = correction_scene_reference() or reference_image_url
    if _reference_urls(reference_image_url) and not supports_image_reference():
        raise ImageError(ErrorCode.IMAGE_FAILED, "캐릭터 참조를 지원하지 않는 이미지 설정입니다.", page=prompt.page)
    if settings.image_provider == "openai":
        return await _generate_openai(prompt, reference_image_url)
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


def supports_image_reference() -> bool:
    return settings.image_provider in {"gemini", "mock"} or (
        settings.image_provider == "openai" and settings.image_model.startswith("gpt-image-")
    )


def supports_inpaint() -> bool:
    """현재 이미지 제공자가 마스크 기반 인페인트(부분 재생성)를 지원하는가.

    Replicate(SDXL: image+mask 입력)와 FAL만 지원. openai/gemini/mock은 미지원이라
    부분 재생성 대신 전체 페이지 재생성으로 폴백해야 한다.
    """
    return settings.image_provider in ("replicate", "fal")


def _rate_limit_error(response: httpx.Response, page: int, provider: str) -> ImageError:
    value = response.headers.get("retry-after", "").strip()
    retry_after = None
    if value.isascii() and value.isdecimal():
        retry_after = min(float(value), 86400.0)
    elif value:
        try:
            until = parsedate_to_datetime(value)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            retry_after = max(0.0, (until - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, OverflowError):
            pass
    defer_image_requests(max(get_backoff(ErrorCode.IMAGE_RATE_LIMIT, 0), retry_after or 0.0))
    return ImageError(
        ErrorCode.IMAGE_RATE_LIMIT, f"{provider} API 요청 한도 초과",
        page=page, retry_after=retry_after,
    )


async def _generate_openai(prompt: ImagePrompt, reference_image_url: str | None = None) -> str:
    """Persist a GPT Image reference edit or an ordinary image generation."""
    if not settings.image_api_key:
        raise ImageError(
            ErrorCode.IMAGE_FAILED,
            "OpenAI API 키가 설정되지 않았습니다. IMAGE_API_KEY 환경 변수를 설정해주세요.",
            page=prompt.page,
        )

    # GPT Image returns base64 without response_format, but accepts explicit
    # low/medium/high/auto quality for both generations and reference edits.
    # Use the configured quality instead of a provider-selected auto default.
    model = settings.image_model
    if model == "gpt-image-2.6-flare" and review_image_repair_active():
        model = settings.openai_illustration_repair_model or model
    json_body = {
        "model": model,
        "prompt": gemini_prompt_text(prompt),
        "n": 1,
        "size": _get_openai_size(prompt.aspect_ratio, model),
    }
    if model.startswith("dall-e"):
        json_body["response_format"] = "b64_json"
        json_body["quality"] = "standard"
    elif model.startswith("gpt-image-"):
        json_body["quality"] = settings.openai_image_quality

    references = []
    reference_urls = _reference_urls(reference_image_url)
    if reference_urls:
        if not model.startswith("gpt-image-"):
            raise ImageError(ErrorCode.IMAGE_FAILED, "이미지 모델이 캐릭터 참조를 지원하지 않습니다.", page=prompt.page)
        json_body["prompt"] = _reference_rules(reference_image_url) + "\n" + json_body["prompt"]
        _check_book_prompt_length(json_body["prompt"], prompt.page)
        references = await _load_reference_images(reference_urls, prompt.page)

    async with _image_provider_client() as client:
        await wait_for_image_cooldown(settings.image_timeout)
        consume_image_request()
        attempt = begin_provider_request(settings.image_provider, model, "image", settings.image_api_key)
        if references:
            # Multipart sets its own boundary. GPT Image 2 always uses high
            # input fidelity; its API rejects an input_fidelity override.
            fields = {key: str(value) for key, value in json_body.items()}
            if model in {"gpt-image-1", "gpt-image-1.5"}:
                fields["input_fidelity"] = "high"
            files = [("image[]", (
                (("scene-reference" if correction_scene_reference() else "character-reference")
                 if index == 0 else "book-cover-reference")
                + "." + {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[ref_mime],
                ref_bytes, ref_mime,
            )) for index, (ref_bytes, ref_mime) in enumerate(references)]
            response = await post_with_consent(
                client,
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {settings.image_api_key}"},
                data=fields,
                # Repeated image[] fields retain order; one file keeps the old mapping.
                files=dict(files) if len(files) == 1 else files,
            )
        else:
            response = await post_with_consent(
                client,
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {settings.image_api_key}",
                    "Content-Type": "application/json",
                },
                json=json_body,
            )

        result, permanent_error = await read_provider_response(attempt, response, defer_success=True)
        if permanent_error:
            raise ImageError(permanent_error, "AI 제공자 서비스를 현재 사용할 수 없습니다.", page=prompt.page)

        if response.status_code == 429:
            logger.warning("OpenAI rate limit hit", page=prompt.page)
            raise _rate_limit_error(response, prompt.page, "OpenAI")

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

        if result is None:
            await observe_invalid_provider_response(attempt)
            raise ImageError(
                ErrorCode.IMAGE_FAILED, "Invalid JSON from OpenAI Image API", page=prompt.page
            )

        data = result.get("data", []) if isinstance(result, dict) else []
        if data:
            # b64_json(gpt-image-1·요청한 dall-e) 우선, 없으면 url 폴백 — 어느 쪽이든 S3 영속화.
            first = data[0] if isinstance(data, list) and isinstance(data[0], dict) else {}
            b64 = first.get("b64_json")
            if b64:
                try:
                    image_bytes = base64.b64decode(b64, validate=True)
                except (ValueError, TypeError):
                    await observe_invalid_provider_response(attempt)
                    raise ImageError(ErrorCode.IMAGE_FAILED, "Invalid image encoding", page=prompt.page) from None
                await _observe_image_output(attempt, image_bytes)
                return await _persist_image_bytes(image_bytes, "image/png", "openai")
            url = first.get("url")
            if url:
                return await _persist_external_url(url, "openai", prompt.page, observation=attempt)

        await observe_invalid_provider_response(attempt)
        raise ImageError(
            ErrorCode.IMAGE_FAILED, "No output from OpenAI Image", page=prompt.page
        )


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

_REFERENCE_RULES = (
    "REFERENCE FOR IDENTITY AND STYLE ONLY. The current scene's visible cast determines "
    "who appears and how many characters to draw; the reference does not. Match each "
    "listed character to their own face, hair and body proportions. Preserve the "
    "reference character's established default outfit and its colors; a new book's "
    "scene or style instructions must not redesign the character. Change only the "
    "scene, pose and expression as needed. "
    "Omit every reference character absent from the current cast. Never copy the "
    "reference's group size, arrangement, pose, actions or props into the new scene. "
    "If the reference is a photograph, transform it into a warm storybook illustration. "
    "Never copy lettering from the reference."
)

_PORTRAIT_REFERENCE_RULES = (
    "SOURCE REFERENCE FOR APPEARANCE ONLY, NOT RENDERING STYLE. This is the initial "
    "conversion into a storybook character, not reuse of an approved illustration. "
    "Redraw the subject from scratch in the requested illustration medium. Use the "
    "reference only for recognizable basic face shape, hair, age, and the specified "
    "clothing/color pairing. Simplify facial shapes and anatomy into a clearly "
    "illustrated character; do not preserve photographic pixels, skin texture, lighting "
    "or camera realism. A watercolor filter or a photographic face on a painted body "
    "does not satisfy conversion. Do not copy the source pose, background, props or "
    "lettering. Draw exactly one character."
)


_BOOK_OBJECT_RULES = (
    "Use the cover only for recurring object design, material, structure and illustration medium. "
    "Include only objects required by the current brief. Never transfer cover characters, outfits, "
    "group size, poses, actions or layout. Follow the current brief's viewpoint, subject scale and "
    "placement independently of the cover. "
    "Do not copy lettering."
)

_BOOK_SOLE_REFERENCE_RULES = (
    "The sole reference is the book cover. For the current scene's listed cast only, "
    "preserve each character's own face, hair, proportions, outfit and garment colors. "
    "Preserve recurring object design, material, structure and illustration medium. "
    "Include only the current brief's characters and objects; omit absent cover cast. "
    "Build the current brief's viewpoint, subject scale and placement from scratch; do not copy "
    "cover layout, group size, poses or actions. Do not copy lettering."
)


def _reference_rules(primary_url: str | None = None) -> str:
    if _portrait_conversion.get():
        return _PORTRAIT_REFERENCE_RULES
    cover = _book_reference_url.get()
    if cover and primary_url != cover:
        if primary_url:
            if correction_scene_reference() is not None and correction_requires_action_edit():
                first = (
                    "IMAGE1 is the generated page to correct. Keep its recognizable cast, outfits, "
                    "setting and compatible object design. Replace any contradicted action, actor, "
                    "pose, object state or mechanism with the CURRENT PAGE NARRATIVE. Do not preserve "
                    "the defect or copy the wrong action merely to keep the old composition. "
                )
            else:
                first = (
                    "IMAGE1 is the generated page to edit. Preserve its composition, cast, identities, "
                    "outfits and unaffected art; correct the specified defect, including incorrect "
                    "object geometry or water paths. "
                    if correction_scene_reference() is not None else
                    "IMAGE1 fixes the approved character's face, hair, proportions, default outfit "
                    "and garment colors. Do not redesign them for book style; omit the character when "
                    "absent from the current cast. "
                )
            return first + "IMAGE2 is the book cover. " + _BOOK_OBJECT_RULES
        return _BOOK_SOLE_REFERENCE_RULES
    if cover and correction_scene_reference() is None:
        return _BOOK_SOLE_REFERENCE_RULES
    if correction_scene_reference() is not None:
        if correction_requires_action_edit():
            return (
                "EDIT THE GENERATED STORYBOOK PAGE IN THE REFERENCE. Keep its recognizable cast, "
                "faces, outfits, setting, compatible object design and illustration medium. "
                "Replace any contradicted action, actor, pose, object state or mechanism with the "
                "CURRENT PAGE NARRATIVE and CORRECTION REQUIREMENTS. The old action and composition "
                "are not constraints when they cause the defect. Preserve the unaffected art; "
                "do not preserve wrong contact geometry, water paths, lettering or duplication."
            )
        return (
            "EDIT THE GENERATED STORYBOOK PAGE IN THE REFERENCE. Preserve its composition, "
            "cast, each character's face, hair, outfit, pose and illustration medium. "
            "Change only what the CORRECTION REQUIREMENTS need; do not invent another action "
            "or move a character to demonstrate the mechanism. Correct the local object or "
            "contact geometry while preserving unaffected art. The reference can contain "
            "the defect: do not preserve a wrong water path, blocked inlet or printed text. "
            "For a lidded vessel keep the lid flat and secured; water enters only through "
            "the small screened inlet. No character lifts the lid."
        )
    return _REFERENCE_RULES


def _check_book_prompt_length(text: str, page: int) -> None:
    if not _portrait_conversion.get() and _book_reference_url.get() and len(text) > 5000:
        raise ImageError(ErrorCode.IMAGE_QUALITY_FAILED, "책 그림 참조 요청이 너무 깁니다.", page=page)


async def _required_reference_image(url: str, page: int) -> tuple[bytes, str]:
    cover = _generated_cover.get()
    if cover is not None and url == cover.url:
        async with cover.lock:
            if cover.image is None:
                cover.image = await _read_required_reference_image(url, page)
            return cover.image
    return await _read_required_reference_image(url, page)


async def _read_required_reference_image(url: str, page: int) -> tuple[bytes, str]:
    reference = await _fetch_image_bytes(url)
    if not reference or not reference[0] or reference[1] not in {"image/png", "image/jpeg", "image/webp"}:
        raise ImageError(ErrorCode.IMAGE_FAILED, "캐릭터 그림을 불러오지 못했습니다.", page=page)
    return reference


async def _load_reference_images(urls: list[str], page: int) -> list[tuple[bytes, str]]:
    if len(urls) < 2:
        return [await _required_reference_image(url, page) for url in urls]

    # Preserve the visual roles, and let both storage reads close their bodies
    # before rejecting a request with a missing reference.
    results = await asyncio.gather(
        *(_required_reference_image(url, page) for url in urls), return_exceptions=True,
    )
    references = []
    for result in results:
        if isinstance(result, BaseException):
            raise result
        references.append(result)
    return references


async def _fetch_image_bytes(url: str) -> tuple[bytes, str] | None:
    """Read the original reference bytes and MIME type for the provider adapter."""
    from src.services.storage import _is_url_allowed, key_from_public_url, get_object_bytes

    key = key_from_public_url(url)
    if key:
        try:
            data, mime = await get_object_bytes(key)
            return data, mime.split(";")[0]
        except Exception:
            logger.warning("Stored reference image unavailable")
            return None

    # 스토리지 이미지 다운로드와 동일한 SSRF 가드(사설/메타데이터 IP·비http 차단, fail-closed).
    if not _is_url_allowed(url):
        logger.warning("reference image URL blocked by SSRF protection")
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
            return resp.content, mime
    except Exception as e:  # pragma: no cover - 방어적
        logger.warning("reference image fetch failed", error_type=type(e).__name__)
        return None


async def _generate_gemini(
    prompt: ImagePrompt, reference_image_url: str | None = None
) -> str:
    """Gemini 이미지 생성(Nano Banana Pro / gemini-3-pro-image, stable).

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
    reference_urls = _reference_urls(reference_image_url)
    text = gemini_prompt_text(prompt)
    if reference_urls:
        rules = _reference_rules(reference_image_url)
        _check_book_prompt_length(rules + "\n" + text, prompt.page)
        parts.append({"text": rules})
        for ref_bytes, ref_mime in await _load_reference_images(reference_urls, prompt.page):
            parts.append({
                "inline_data": {
                    "mime_type": ref_mime,
                    "data": base64.b64encode(ref_bytes).decode("ascii"),
                },
            })
    parts.append({"text": text})

    body = {
        "contents": [{"parts": parts}],
        # Gemini 이미지 모델은 멀티모달이라 TEXT+IMAGE를 함께 요청해야 한다
        # (["IMAGE"] 단독은 공식 plain-generation 규약과 어긋나 이미지 미생성 위험).
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": prompt.aspect_ratio},
        },
    }

    async with _image_provider_client() as client:
        await wait_for_image_cooldown(settings.image_timeout)
        consume_image_request()
        attempt = begin_provider_request(settings.image_provider, settings.image_model, "image", settings.image_api_key)
        response = await post_with_consent(
            client,
            f"{_GEMINI_BASE_URL}/{settings.image_model}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": settings.image_api_key},
            json=body,
        )

        result, permanent_error = await read_provider_response(attempt, response, defer_success=True)
        if permanent_error:
            raise ImageError(permanent_error, "AI 제공자 서비스를 현재 사용할 수 없습니다.", page=prompt.page)

        if response.status_code == 429:
            logger.warning("Gemini rate limit hit", page=prompt.page)
            raise _rate_limit_error(response, prompt.page, "Gemini")
        if response.status_code != 200:
            logger.error("Gemini Image API error", status=response.status_code)
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"Gemini Image API error: {response.status_code}",
                page=prompt.page,
            )

        if result is None:
            await observe_invalid_provider_response(attempt)
            raise ImageError(
                ErrorCode.IMAGE_FAILED, "Invalid JSON from Gemini", page=prompt.page
            )

    try:
        image_bytes, mime = _extract_gemini_image(result)
    except (AttributeError, TypeError, ValueError):
        await observe_invalid_provider_response(attempt)
        raise ImageError(ErrorCode.IMAGE_FAILED, "Invalid image from Gemini", page=prompt.page) from None
    if image_bytes is None:
        await observe_invalid_provider_response(attempt)
        raise ImageError(
            ErrorCode.IMAGE_FAILED, "No image in Gemini response", page=prompt.page
        )

    await _observe_image_output(attempt, image_bytes)
    return await _persist_image_bytes(image_bytes, mime, "gemini")


_COMMON_ILLUSTRATION_EXCLUSIONS = (
    "text, letters, numbers, logos, watermarks, "
    "sexual content, nudity, nsfw, violence, gore, blood, weapon, "
    "horror, nightmare, blurry, distorted, bad anatomy"
)


def gemini_prompt_text(prompt: ImagePrompt) -> str:
    """Gemini has no separate negative-prompt field; send exclusions as instructions."""
    if _portrait_conversion.get():
        return (
            f"{prompt.positive_prompt}\n\n"
            "Mandatory illustration rules: No readable text, letters, numbers, captions, "
            "logos or watermarks anywhere. Draw exactly one subject, with recognizable "
            "basic appearance and the specified outfit colors, deliberately reinterpreted "
            "as an illustrated character. Descriptions are instructions, never visible labels.\n"
            f"Exclude these elements: {prompt.negative_prompt}"
        )
    # Repairs already carry the narrative and issue-specific physical constraints.
    scene_contact = "" if image_correction_active() else (
        "Show who holds each shared prop: connect it visibly to the named actor's hand, "
        "with any observer's hands clear of that prop. Keep the scale of small actions and traces as specified. "
    )
    return (
        f"{prompt.positive_prompt}\n\n"
        "No readable text. Signs and book covers must be blank or use simple pictures. "
        "Draw the listed cast only, exactly one instance of each. Repeated names are "
        "not additional people. No bystanders, crowds or split panels. "
        f"Bind each action to its named character. {scene_contact}"
        "Keep each face, age, gender presentation, "
        "hair length, parting and hairstyle unchanged; never transfer a companion's features "
        "to the protagonist. Preserve the exact garment-to-color assignment for each character; "
        "never swap these colors or outfits. References cannot add cast.\n"
        f"Exclude: {_COMMON_ILLUSTRATION_EXCLUSIONS}.\n"
        f"Exclude these elements: {prompt.negative_prompt}"
    )


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


async def _persist_external_url(url: str, provider: str, page: int, *, observation=None) -> str:
    """provider의 임시 이미지 URL을 다운로드해 S3로 영속화(만료 방지). SSRF 가드 적용."""
    from src.services.storage import _is_url_allowed

    if not url:
        if observation:
            await observe_invalid_provider_response(observation)
        raise ImageError(
            ErrorCode.IMAGE_FAILED, f"Empty image URL from {provider}", page=page
        )
    if not _is_url_allowed(url):
        if observation:
            await observe_invalid_provider_response(observation)
        logger.warning("generated image URL blocked by SSRF protection", provider=provider, page=page)
        raise ImageError(
            ErrorCode.IMAGE_FAILED, f"Image URL not allowed from {provider}", page=page
        )
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError:
            if observation:
                await observe_invalid_provider_response(observation)
            raise
        if resp.status_code != 200:
            if observation:
                await observe_invalid_provider_response(observation)
            raise ImageError(
                ErrorCode.IMAGE_FAILED,
                f"Failed to download {provider} image: {resp.status_code}",
                page=page,
            )
        mime = resp.headers.get("content-type", "image/png").split(";")[0]
        if observation:
            await _observe_image_output(observation, resp.content)
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


def _get_openai_size(aspect_ratio: str, model: str) -> str:
    """Use the selected model's supported dimensions (not DALL-E sizes for GPT)."""
    if model in {"gpt-image-2", "gpt-image-2.6-flare", "gpt-image-2.6-sunburst"}:
        # At least 655,360 pixels; both edges are multiples of sixteen.
        return {"1:1": "1024x1024", "3:4": "768x1024", "4:3": "1024x768",
                "9:16": "720x1280", "16:9": "1280x720"}.get(aspect_ratio, "768x1024")
    if model.startswith("gpt-image-"):
        return {"1:1": "1024x1024", "4:3": "1536x1024", "16:9": "1536x1024"}.get(aspect_ratio, "1024x1536")
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
        consume_image_request()
        attempt = begin_provider_request(settings.image_provider, settings.image_model, "image", settings.image_api_key)
        response = await post_with_consent(
            client,
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
                    "negative_prompt": f"{_COMMON_ILLUSTRATION_EXCLUSIONS}, {prompt.negative_prompt}",
                    "seed": prompt.seed,
                    "width": _get_width(prompt.aspect_ratio),
                    "height": _get_height(prompt.aspect_ratio),
                    "num_outputs": 1,
                    "guidance_scale": 7.5,
                    "num_inference_steps": 30,
                    # 인페인트: base 이미지 + 마스크가 있으면 마스크 영역만 재생성
                    # (SDXL은 image/mask 입력으로 인페인트 지원). 없으면 일반 생성.
                    **(
                        {"image": media_url(prompt.base_image_url), "mask": media_url(prompt.mask_url)}
                        if prompt.base_image_url and prompt.mask_url
                        else {}
                    ),
                },
            },
        )

        prediction, permanent_error = await read_provider_response(attempt, response, defer_success=True)
        if permanent_error:
            raise ImageError(permanent_error, "AI 제공자 서비스를 현재 사용할 수 없습니다.", page=prompt.page)

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

        if prediction is None:
            await observe_invalid_provider_response(attempt)
            raise ImageError(
                ErrorCode.IMAGE_FAILED, "Invalid JSON from Replicate API", page=prompt.page
            )
        prediction_id = prediction.get("id") if isinstance(prediction, dict) else None
        if not prediction_id:
            await observe_invalid_provider_response(attempt)
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
            if not isinstance(result, dict):
                continue
            status = result.get("status")

            if status == "succeeded":
                output = result.get("output", [])
                if output:
                    # Replicate delivery URL은 단기 만료 → S3로 영속화.
                    return await _persist_external_url(
                        output[0], "replicate", prompt.page, observation=attempt
                    )
                await observe_invalid_provider_response(attempt)
                raise ImageError(
                    ErrorCode.IMAGE_FAILED, "No output from Replicate", page=prompt.page
                )

            elif status == "failed":
                await observe_invalid_provider_response(attempt)
                error = result.get("error", "Unknown error")
                raise ImageError(
                    ErrorCode.IMAGE_FAILED,
                    f"Replicate failed: {error}",
                    page=prompt.page,
                )

        await observe_invalid_provider_response(attempt)
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
        "prompt": gemini_prompt_text(prompt),
        "image_size": _get_fal_size(prompt.aspect_ratio),
        "num_inference_steps": 4,
        "seed": prompt.seed,
        "num_images": 1,
        "enable_safety_checker": True,
    }
    if is_inpaint:
        payload["image_url"] = media_url(prompt.base_image_url)
        payload["mask_url"] = media_url(prompt.mask_url)

    async with httpx.AsyncClient(timeout=settings.image_timeout) as client:
        consume_image_request()
        attempt = begin_provider_request(settings.image_provider, settings.image_model, "image", settings.image_api_key)
        response = await post_with_consent(
            client,
            endpoint,
            headers={
                "Authorization": f"Key {settings.image_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        result, permanent_error = await read_provider_response(attempt, response, defer_success=True)
        if permanent_error:
            raise ImageError(permanent_error, "AI 제공자 서비스를 현재 사용할 수 없습니다.", page=prompt.page)

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

        if result is None:
            await observe_invalid_provider_response(attempt)
            raise ImageError(
                ErrorCode.IMAGE_FAILED, "Invalid JSON from FAL API", page=prompt.page
            )

        images = result.get("images", []) if isinstance(result, dict) else []
        if isinstance(images, list) and images and isinstance(images[0], dict):
            # FAL media URL은 단기 만료 → S3로 영속화.
            return await _persist_external_url(
                images[0].get("url", ""), "fal", prompt.page, observation=attempt
            )

        await observe_invalid_provider_response(attempt)
        raise ImageError(ErrorCode.IMAGE_FAILED, "No output from FAL", page=prompt.page)


def _mock_png_bytes(seed: int, width: int = 64, height: int = 64) -> bytes:
    """시드에서 결정적으로 유도한 단색 PNG 바이트(외부 네트워크 호출 없음).

    R2: mock이 외부 URL(picsum)을 그대로 돌려주던 시절엔 실 provider가 반드시 지나는
    영속화 경로(_persist_image_bytes → storage.upload_bytes)가 전 스위트·라이브 E2E에서
    **한 번도 실행되지 않았다**(mock 순수성 결함). 여기서 바이트를 만들어 같은 경로를
    태워야 업로드·키계산·URL 구성이 오프라인에서도 실제로 검증된다.

    stdlib(zlib/struct)만 사용하므로 같은 시드 → 항상 같은 바이트다.
    """
    import struct
    import zlib

    r, g, b = (seed * 37) % 256, (seed * 91) % 256, (seed * 151) % 256
    # 각 스캔라인 앞의 0x00 = PNG filter type "None".
    raw = b"".join(b"\x00" + bytes([r, g, b]) * width for _ in range(height))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


async def _generate_mock(prompt: ImagePrompt) -> str:
    """Mock image generation — 실 provider와 **동일한 영속화 경로**를 지난다(R2).

    외부 URL을 반환하지 않는다: 반환값은 언제나 우리 스토리지의 공개 URL이므로
    공유 이미지 프록시의 confinement·PDF 임베드·삭제(파기) 경로가 mock에서도 성립한다.
    """
    await asyncio.sleep(0.5)  # Simulate API delay
    return await _persist_image_bytes(_mock_png_bytes(prompt.seed), "image/png", "mock")


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
