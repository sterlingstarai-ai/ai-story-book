"""Product length defaults and truncated-provider responses, with no live calls."""

import json
from unittest.mock import AsyncMock

import pytest

from src.core.errors import ErrorCode, LLMError
from src.models.dto import BookSpec, CharacterSheet, SeriesNextRequest, StoryDraft
from src.services import llm
from tests.test_live_generation_improvements import prompts
from tests.test_llm_schema_diagnostics import valid_story


def spec(**overrides):
    return BookSpec(topic="도서관 친구들의 모험", target_age="7-9", style="watercolor", **overrides)


def test_new_and_series_stories_default_to_twelve_body_pages():
    assert spec().page_count == 12
    assert SeriesNextRequest(character_id="hero", topic="다음 모험").page_count == 12


@pytest.mark.parametrize("count", [4, 8, 12])
def test_explicit_trial_short_and_standard_lengths_remain_compatible(count):
    assert spec(page_count=count).page_count == count
    assert SeriesNextRequest(character_id="hero", topic="다음 모험", page_count=count).page_count == count


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["ko", "en", "ja"])
async def test_short_provider_story_is_rejected_before_illustrations(monkeypatch, language):
    story = valid_story()
    story["language"] = language
    monkeypatch.setattr(llm, "call_llm", AsyncMock(return_value=json.dumps(story)))
    with pytest.raises(LLMError) as caught:
        await llm.call_story_generation(spec(language=language))
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID
    assert caught.value.details["raw_output"] is None


@pytest.mark.asyncio
async def test_missing_later_image_prompts_are_rejected(monkeypatch, valid_character):
    story = StoryDraft.model_validate(valid_story())
    story.pages = [story.pages[0].model_copy(update={"page": number}) for number in range(1, 13)]
    character = CharacterSheet(character_id="hero", **valid_character)
    monkeypatch.setattr(llm, "call_llm", AsyncMock(return_value=prompts(8).model_dump_json()))
    with pytest.raises(LLMError) as caught:
        await llm.call_image_prompts_generation(spec(), story, character)
    assert caught.value.code == ErrorCode.LLM_JSON_INVALID


@pytest.mark.asyncio
async def test_twelve_page_retell_preserves_all_pages_with_scaled_output_budget(monkeypatch):
    original = [f"도서관 친구들의 {number}번째 모험이에요." for number in range(1, 13)]
    provider = AsyncMock(return_value=json.dumps({"title": "도서관 모험", "pages": original}))
    monkeypatch.setattr(llm, "call_llm", provider)
    result = await llm.call_story_retext("도서관 모험", original, "3-5", "ko")
    assert result.pages == original
    assert provider.call_args.kwargs["max_tokens"] == 7200
