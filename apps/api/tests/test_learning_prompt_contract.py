import json
from types import SimpleNamespace

import pytest

from src.models.dto import Language, TargetAge
from src.services import llm


@pytest.mark.asyncio
async def test_learning_prompt_uses_schema_language_codes(monkeypatch):
    async def respond(system, user, **kwargs):
        # Reply with the concrete JSON example we actually instructed the model
        # to follow, expanding it to the minimum four page contract.
        data = json.loads(system.split("```json")[1].split("```")[0])
        assert data["source_language"] == "ko"
        assert data["target_language"] == "en"
        assert "{{" not in system
        assert "example" not in data["pages"][0]["vocab"][0]
        data["pages"] = [dict(data["pages"][0], page=i) for i in range(1, 5)]
        return json.dumps(data, ensure_ascii=False)

    monkeypatch.setattr(llm, "call_llm", respond)
    story = SimpleNamespace(title="친구", target_age=TargetAge.a7_9,
                            moral="친절", pages=[], language=Language.ko)
    result = await llm.call_learning_assets(story, Language.ko, Language.en)
    assert result.source_language == Language.ko
    assert len(result.pages) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "language, text, word, expected",
    [
        (Language.ko, '토끼가 손을 흔들었어요. “사과를 먹자!” 모두 모였어요.', "사과", "“사과를 먹자!”"),
        (Language.en, "The sun rose. He picked up the basket.", "he", "He picked up the basket."),
        (Language.ja, "空が明るい。うさぎは小さな森に行った。", "森", "うさぎは小さな森に行った。"),
        (Language.ko, "사과나무와 바구니가 있었어요.", "배", None),
        (Language.en, "basket " + "x" * 300, "basket", None),
    ],
)
async def test_learning_examples_quote_the_matching_source_page(
    monkeypatch, language, text, word, expected,
):
    target = Language.ko if language == Language.en else Language.en

    async def respond(system, user, **kwargs):
        data = json.loads(system.split("```json")[1].split("```")[0])
        data["pages"] = [dict(data["pages"][0], page=i) for i in range(1, 5)]
        data["pages"][0]["vocab"] = [
            {"word": word, "meaning": "A meaning"},
            {"word": word, "meaning": "A meaning", "example": "Existing provider example."},
        ]
        return json.dumps(data, ensure_ascii=False)

    monkeypatch.setattr(llm, "call_llm", respond)
    story = SimpleNamespace(
        title="친구", target_age=TargetAge.a7_9, moral="친절",
        pages=[SimpleNamespace(page=1, text=text), SimpleNamespace(page=2, text=word)],
    )
    result = await llm.call_learning_assets(story, language, target)
    assert [item.example for item in result.pages[0].vocab] == [expected, "Existing provider example."]
