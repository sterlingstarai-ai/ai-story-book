"""M19 — 이미지 부분 실패 게이트: placeholder뿐 아니라 빈/None URL도 경고(비대칭 해소)."""

from src.core.book_assets import build_generation_warnings


def _codes(warnings):
    return {w["code"] for w in warnings}


def test_flags_empty_page_url():
    """빈 URL 페이지(예외 실패)가 page_image_missing 경고를 낸다(수정 전 0건)."""
    warnings = build_generation_warnings(
        cover_image_url="https://x/cover.png",
        page_images=[(1, ""), (2, "https://x/p2.png")],
    )
    assert "page_image_missing" in _codes(warnings)
    # 정상 페이지 2는 경고 없음.
    assert not any(w["page_number"] == 2 for w in warnings)


def test_flags_empty_cover_url():
    warnings = build_generation_warnings(
        cover_image_url="",
        page_images=[(1, "https://x/p1.png")],
    )
    assert "cover_image_missing" in _codes(warnings)


def test_placeholder_warnings_preserved():
    """회귀: placeholder 경로 기존 경고 유지, missing과 별도 코드."""
    warnings = build_generation_warnings(
        cover_image_url="https://placeholder.invalid/cover",
        page_images=[(1, "https://placeholder.invalid/p1")],
    )
    codes = _codes(warnings)
    assert "cover_placeholder_image" in codes
    assert "page_placeholder_image" in codes
    assert "cover_image_missing" not in codes  # placeholder는 missing 아님


def test_all_generated_no_warnings():
    warnings = build_generation_warnings(
        cover_image_url="https://x/cover.png",
        page_images=[(1, "https://x/p1.png"), (2, "https://x/p2.png")],
    )
    assert warnings == []
