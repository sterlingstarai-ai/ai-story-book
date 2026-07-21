"""i18n 기반 — 스토리 생성 언어 파라미터화 + 주인공 이름 반영."""

import pytest

from src.core.i18n import SUPPORTED_LANGUAGES, language_display_name
from src.services.llm import render_prompt


def test_supported_languages_and_display():
    assert "ko" in SUPPORTED_LANGUAGES
    assert "en" in SUPPORTED_LANGUAGES
    assert "ja" in SUPPORTED_LANGUAGES
    assert language_display_name("en") == "English"
    assert language_display_name("ja") == "日本語"
    # zh/es도 정상 표시명(학습자산 맵 단일출처화 회귀 방지, L16)
    assert language_display_name("zh") == "中文"
    assert language_display_name("es") == "Español"
    # 미지원 코드는 조용한 ko 폴백 대신 시끄럽게 실패(L16) — 맵 갱신 누락을 즉시 드러냄.
    with pytest.raises((KeyError, ValueError)):
        language_display_name("zz")


def test_learning_assets_map_single_sourced():
    """llm.call_learning_assets가 자체 {ko,en,ja} 맵 대신 i18n 단일출처를 쓰는지 소스 확인(L16).

    자체 language_names 중복 맵이 제거돼야 zh/es가 코드('zh')가 아니라 표시명(中文)으로 간다.
    """
    import inspect

    from src.services import llm as llm_module

    src = inspect.getsource(llm_module.call_learning_assets)
    # 중복 맵(Language.ja: "日本語") 리터럴이 제거되고 language_display_name을 사용해야 함.
    assert "language_display_name" in src
    assert '"日本語"' not in src


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


def test_character_sheet_prompt_is_english_bound_not_korean():
    """M28: 캐릭터 시트 master_description이 '한글로' 대신 영어로 작성되도록 지시."""
    rendered = render_prompt("generate_character_sheet.system.jinja2")
    assert "한글로" not in rendered
    assert "영어로" in rendered  # 영어 고정 지시 존재


def test_image_prompt_system_requires_english_positive_prompt():
    """M28: positive_prompt를 영어로만 작성하도록 명시(다국어 혼입 차단)."""
    rendered = render_prompt("generate_image_prompts.system.jinja2")
    assert "영어로만" in rendered
