from __future__ import annotations

from typing import Iterable, Optional


_PLACEHOLDER_MARKERS = ("placeholder.invalid",)


def is_placeholder_asset_url(url: Optional[str]) -> bool:
    if not isinstance(url, str):
        return False
    normalized = url.strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


def build_image_asset_status(url: Optional[str]) -> dict:
    normalized = url.strip() if isinstance(url, str) else ""
    if not normalized:
        return {
            "state": "missing",
            "reason": "image_missing",
        }
    if is_placeholder_asset_url(normalized):
        return {
            "state": "degraded",
            "reason": "placeholder_image",
            "url": normalized,
        }
    return {
        "state": "generated",
        "url": normalized,
    }


def build_audio_asset_status(urls: Iterable[Optional[str]]) -> dict:
    for candidate in urls:
        normalized = candidate.strip() if isinstance(candidate, str) else ""
        if normalized:
            return {
                "state": "available",
                "url": normalized,
            }
    return {
        "state": "missing",
        "reason": "audio_not_generated",
    }


def build_page_asset_status(
    image_url: Optional[str],
    *,
    audio_urls: Iterable[Optional[str]] = (),
) -> dict:
    return {
        "image": build_image_asset_status(image_url),
        "audio": build_audio_asset_status(audio_urls),
    }


def _is_missing_asset_url(url: Optional[str]) -> bool:
    """URL이 비어있음/None(예외 실패로 image_url='' 저장)인지. asset_status의 'missing'과 일관."""
    return not (isinstance(url, str) and url.strip())


def build_generation_warnings(
    *,
    cover_image_url: Optional[str],
    page_images: Iterable[tuple[int, Optional[str]]],
) -> list[dict]:
    warnings: list[dict] = []

    # M19: placeholder(강등)뿐 아니라 빈/None URL(예외 실패)도 경고 — 그림 없는 페이지가
    # 경고 배너 없이 '완성'으로 배달되던 비대칭(asset_status는 'missing'인데 warnings는 0건) 해소.
    if is_placeholder_asset_url(cover_image_url):
        warnings.append(
            {
                "code": "cover_placeholder_image",
                "message": "표지 이미지 생성이 실패해 임시 이미지를 표시하고 있습니다.",
                "asset": "cover",
                "page_number": 0,
            }
        )
    elif _is_missing_asset_url(cover_image_url):
        warnings.append(
            {
                "code": "cover_image_missing",
                "message": "표지 이미지 생성에 실패했습니다.",
                "asset": "cover",
                "page_number": 0,
            }
        )

    for page_number, image_url in page_images:
        if is_placeholder_asset_url(image_url):
            warnings.append(
                {
                    "code": "page_placeholder_image",
                    "message": "일부 페이지 이미지 생성이 실패해 임시 이미지를 표시하고 있습니다.",
                    "asset": "image",
                    "page_number": page_number,
                }
            )
        elif _is_missing_asset_url(image_url):
            warnings.append(
                {
                    "code": "page_image_missing",
                    "message": "일부 페이지 이미지 생성에 실패했습니다.",
                    "asset": "image",
                    "page_number": page_number,
                }
            )

    return warnings
