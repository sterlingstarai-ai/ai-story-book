"""P0-5: 캐릭터 고유 특징(distinctive_features)이 시트와 이미지 프롬프트에 실리는지 검증."""

from src.models.dto import (
    CharacterAppearance,
    CharacterClothing,
    CharacterSheet,
)
from src.services.llm import render_prompt


def _sheet(**kw) -> CharacterSheet:
    return CharacterSheet(
        character_id="c1",
        name="토리",
        master_description="둥근 얼굴의 용감한 다섯 살 아이, 파란 멜빵바지를 입었다.",
        appearance=CharacterAppearance(
            age_visual="5세",
            face="둥근 얼굴",
            hair="짧은 갈색",
            skin="밝은 피부",
            body="작고 통통",
        ),
        clothing=CharacterClothing(
            top="파란 멜빵바지",
            bottom="없음",
            shoes="운동화",
            accessories="없음",
        ),
        personality_traits=["용감함"],
        visual_style_notes="수채화",
        **kw,
    )


def test_character_sheet_accepts_distinctive_features():
    sheet = _sheet(distinctive_features=["round glasses", "freckles"])
    assert sheet.distinctive_features == ["round glasses", "freckles"]


def test_character_sheet_distinctive_features_default_none():
    assert _sheet().distinctive_features is None


def test_image_prompt_carries_distinctive_features():
    # tojson은 비ASCII를 escape하므로 영문 특징으로 통과 검증(파이프라인 전달만 확인).
    sheet = _sheet(distinctive_features=["round glasses", "freckles"])
    prompt = render_prompt(
        "generate_image_prompts.user.jinja2",
        target_age="5-7",
        style="watercolor",
        character_sheet=sheet.model_dump(),
        cover={"page": 0, "scene": "표지"},
        pages=[{"page": 1, "scene": "숲"}],
    )
    assert "round glasses" in prompt
    assert "freckles" in prompt
