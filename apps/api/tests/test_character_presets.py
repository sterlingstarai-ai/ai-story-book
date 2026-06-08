"""기본 캐릭터 프리셋(아이 얼굴 주인공의 '기본 이미지' 경로) 테스트."""

import pytest

from src.core.character_presets import CHARACTER_PRESETS, get_preset

H = {"X-User-Key": "77777777-7777-4777-8777-777777777777"}

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
