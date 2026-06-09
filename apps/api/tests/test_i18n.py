"""i18n 기반 — 스토리 생성 언어 파라미터화 + 주인공 이름 반영."""

from src.core.i18n import SUPPORTED_LANGUAGES, language_display_name
from src.services.llm import render_prompt


def test_supported_languages_and_display():
    assert "ko" in SUPPORTED_LANGUAGES
    assert "en" in SUPPORTED_LANGUAGES
    assert "ja" in SUPPORTED_LANGUAGES
    assert language_display_name("en") == "English"
    assert language_display_name("ja") == "日本語"
    assert language_display_name("zz") == "한국어"  # 미지원 → 기본 폴백


def test_story_system_prompt_is_language_parameterized():
    en = render_prompt(
        "generate_story.system.jinja2",
        page_count=8,
        language="en",
        language_name="English",
    )
    assert "English" in en
    assert '"language": "en"' in en
    assert "한국어 중심" not in en  # 더 이상 한국어 하드코딩 아님

    ko = render_prompt(
        "generate_story.system.jinja2",
        page_count=8,
        language="ko",
        language_name="한국어",
    )
    assert "한국어" in ko
    assert '"language": "ko"' in ko


def test_protagonist_name_in_story_user_prompt():
    """아이가 주인공 — protagonist_name 이 스토리 프롬프트에 반영된다."""
    prompt = render_prompt(
        "generate_story.user.jinja2",
        topic="우주 여행",
        protagonist_name="지우",
        language="en",
        target_age="5-7",
        theme=None,
        style="watercolor",
        page_count=8,
        forbidden_elements=[],
    )
    assert "지우" in prompt
    assert "language: en" in prompt
