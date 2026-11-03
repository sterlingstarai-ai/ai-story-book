"""Narration excludes production labels without rewriting story content."""
from unittest.mock import AsyncMock

import pytest

from src.services import tts


@pytest.mark.parametrize(('source', 'expected'), [
    ('페이지 1\n토끼가 숲으로 갔어요.', '토끼가 숲으로 갔어요.'),
    ('Page 1: A rabbit smiled.', 'A rabbit smiled.'),
    ('ページ 1\nうさぎが笑いました。', 'うさぎが笑いました。'),
    ('페이지 2: 장면 2의 이야기입니다. 토끼가 웃었어요.', '토끼가 웃었어요.'),
    ('\n페이지 2\n\n장면 2의 이야기입니다. 토끼가 웃었어요.', '토끼가 웃었어요.'),
    ('\n토끼가 웃었어요.', '\n토끼가 웃었어요.'),
    ('장면 2의 이야기 입니다. 안녕!', '안녕!'),
    ('페이지 1의 비밀을 찾아요.', '페이지 1의 비밀을 찾아요.'),
    ('페이지 1.2는 마법의 숫자였어요.', '페이지 1.2는 마법의 숫자였어요.'),
    ('Page 1.2 was a clue.', 'Page 1.2 was a clue.'),
    ('“페이지 1!” 하고 토끼가 외쳤어요.', '“페이지 1!” 하고 토끼가 외쳤어요.'),
    ('토끼가 말했어요. 장면 2의 이야기입니다.', '토끼가 말했어요. 장면 2의 이야기입니다.'),
])
def test_only_leading_production_labels_are_removed(source, expected):
    assert tts.narration_text_without_heading(source) == expected


@pytest.mark.asyncio
async def test_provider_receives_story_without_a_leading_label(monkeypatch):
    service = tts.TTSService()
    service._provider = AsyncMock()
    service._provider.synthesize.return_value = b'audio'
    monkeypatch.setattr(tts, 'require_daily_generation_budget', AsyncMock())
    result = await service.synthesize_page('페이지 1\n토끼가 웃었어요.')
    assert result == b'audio'
    assert service._provider.synthesize.await_args.args[0] == '토끼가 웃었어요.'


@pytest.mark.asyncio
@pytest.mark.parametrize('text', ['페이지 1.', '페이지 1', '장면 2의 이야기입니다'])
async def test_label_only_never_consumes_generation_budget(monkeypatch, text):
    service = tts.TTSService()
    budget = AsyncMock()
    monkeypatch.setattr(tts, 'require_daily_generation_budget', budget)
    with pytest.raises(ValueError, match='story narration'):
        await service.synthesize_page(text)
    budget.assert_not_awaited()
