"""기본 캐릭터 프리셋(아이 얼굴 주인공의 '기본 이미지' 경로) 테스트."""

import pytest

from src.core.character_presets import (
    CHARACTER_PRESETS,
    get_preset,
    get_preset_localized,
)

H = {"X-User-Key": "77777777-7777-4777-8777-777777777777"}


def _has_korean(text: str) -> bool:
    """한글 음절(가-힣)이 하나라도 포함되는지."""
    return any("가" <= ch <= "힣" for ch in text)


def _appearance_clothing_strings(preset: dict) -> str:
    """appearance/clothing dict 값들을 한 문자열로 이어붙인다(한글 스캔용)."""
    parts: list[str] = []
    for field in ("appearance", "clothing"):
        value = preset.get(field, {})
        if isinstance(value, dict):
            parts.extend(str(v) for v in value.values())
    return " ".join(parts)

_REQUIRED = {
    "preset_id",
    "name",
    "master_description",
    "appearance",
    "clothing",
    "personality_traits",
    "visual_style_notes",
    "thumbnail_asset",
}


def test_get_preset_lookup_and_shape():
    assert get_preset("bright_girl") is not None
    assert get_preset("nonexistent") is None
    for preset in CHARACTER_PRESETS:
        assert _REQUIRED.issubset(preset.keys())
        assert len(preset["master_description"]) >= 10
        assert set(preset["appearance"].keys()) == {
            "age_visual",
            "face",
            "hair",
            "skin",
            "body",
        }


@pytest.mark.asyncio
async def test_list_presets(client):
    res = await client.get("/v1/characters/presets", headers=H)
    assert res.status_code == 200, res.text
    presets = res.json()["presets"]
    assert len(presets) >= 4
    assert all("preset_id" in p for p in presets)


@pytest.mark.asyncio
async def test_create_from_preset_with_child_name(client):
    res = await client.post(
        "/v1/characters/from-preset",
        json={"preset_id": "bright_girl", "name": "지우"},
        headers=H,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["name"] == "지우"  # 아이 이름으로 override
    assert data["character_id"].startswith("char_")
    assert len(data["master_description"]) >= 10
    assert "face" in data["appearance"]


@pytest.mark.asyncio
async def test_create_from_preset_unknown_returns_404(client):
    res = await client.post(
        "/v1/characters/from-preset",
        json={"preset_id": "does-not-exist"},
        headers=H,
    )
    assert res.status_code == 404


# --- M27: 프리셋 로케일 서빙 (표시명·외형은 로케일, master_description은 영어 고정) ---


@pytest.mark.asyncio
async def test_list_presets_localized_en(client):
    """?language=en → 표시 텍스트에 한글 부재 + master_description 영어(한글 부재)."""
    res = await client.get("/v1/characters/presets?language=en", headers=H)
    assert res.status_code == 200, res.text
    presets = res.json()["presets"]
    assert len(presets) >= 4
    for p in presets:
        assert not _has_korean(p["name"]), p["name"]
        assert not _has_korean(p["master_description"]), p["master_description"]
        assert not _has_korean(_appearance_clothing_strings(p)), p["preset_id"]


@pytest.mark.asyncio
async def test_list_presets_default_ko(client):
    """language 미지정 → 기존 한국어 표시 유지(하위호환)."""
    res = await client.get("/v1/characters/presets", headers=H)
    assert res.status_code == 200, res.text
    presets = res.json()["presets"]
    # 최소 하나의 프리셋 표시명이 한국어여야 한다(기존 계약 유지).
    assert any(_has_korean(p["name"]) for p in presets)


@pytest.mark.asyncio
async def test_from_preset_persists_localized_en(client):
    """from-preset language=en → 저장 표시명은 한글 부재, master_description은 영어."""
    res = await client.post(
        "/v1/characters/from-preset",
        json={"preset_id": "bright_girl", "language": "en"},
        headers=H,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert not _has_korean(data["name"]), data["name"]
    assert not _has_korean(data["master_description"]), data["master_description"]
    assert len(data["master_description"]) >= 10


def test_get_preset_localized_fallback_unsupported():
    """미지원 언어('fr') → ko 폴백(표시명은 ko와 동일)."""
    ko = get_preset_localized("bright_girl", "ko")
    fr = get_preset_localized("bright_girl", "fr")
    assert fr is not None
    assert fr["name"] == ko["name"]
    assert _has_korean(fr["name"])  # ko 폴백이므로 한국어


def test_get_preset_localized_master_description_english_all_langs():
    """모든 언어에서 master_description은 영어 고정(한글 부재)."""
    for lang in ("ko", "en", "ja", "zh", "es", "fr"):
        for preset in CHARACTER_PRESETS:
            localized = get_preset_localized(preset["preset_id"], lang)
            assert not _has_korean(localized["master_description"]), (
                preset["preset_id"],
                lang,
            )


def test_get_preset_localized_unknown_preset_returns_none():
    assert get_preset_localized("does-not-exist", "en") is None
