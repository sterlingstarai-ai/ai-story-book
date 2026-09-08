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
        data["pages"] = [dict(data["pages"][0], page=i) for i in range(1, 5)]
        return json.dumps(data, ensure_ascii=False)

    monkeypatch.setattr(llm, "call_llm", respond)
    story = SimpleNamespace(title="친구", target_age=TargetAge.a7_9,
                            moral="친절", pages=[], language=Language.ko)
    result = await llm.call_learning_assets(story, Language.ko, Language.en)
    assert result.source_language == Language.ko
    assert len(result.pages) == 4
