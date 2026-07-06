"""P1-10: 다중 캐릭터 관계(남매/친구 등)가 DTO와 스토리 프롬프트에 반영되는지 검증."""

from src.models.dto import BookSpec
from src.services.llm import render_prompt


def test_book_spec_accepts_character_relationship():
    spec = BookSpec(
        topic="남매가 함께 보물을 찾는 모험",
        language="ko",
        target_age="5-7",
        style="watercolor",
        character_ids=["char-a", "char-b"],
        character_relationship="남매",
    )
    assert spec.character_relationship == "남매"


def test_book_spec_relationship_defaults_to_none():
    spec = BookSpec(
        topic="혼자 떠나는 모험",
        language="ko",
        target_age="5-7",
        style="watercolor",
    )
    assert spec.character_relationship is None


def test_story_prompt_includes_relationship_for_multi_character():
    prompt = render_prompt(
        "generate_story.user.jinja2",
        topic="남매 모험",
        protagonist_name=None,
        language="ko",
        target_age="5-7",
        theme=None,
        style="watercolor",
        page_count=8,
        character_spec=None,
        character_specs=[{"name": "토리"}, {"name": "하나"}],
        character_relationship="남매",
        forbidden_elements=[],
    )
    assert "남매" in prompt
    assert "character_relationship" in prompt


def test_story_prompt_omits_relationship_when_single_character():
    prompt = render_prompt(
        "generate_story.user.jinja2",
        topic="혼자 모험",
        protagonist_name=None,
        language="ko",
        target_age="5-7",
        theme=None,
        style="watercolor",
        page_count=8,
        character_spec={"name": "토리"},
        character_specs=None,
        character_relationship=None,
        forbidden_elements=[],
    )
    assert "character_relationship" not in prompt
