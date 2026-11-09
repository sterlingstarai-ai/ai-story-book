"""학습 자산 품질 게이트 — 채점 불가 퀴즈 제거 + 미달 플래그."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.dto import (
    Language,
    LearningAssets,
    LearningPageAssets,
    ParentGuide,
    QuizItem,
    TargetAge,
    VocabItem,
)
from src.services.orchestrator import (
    _assess_and_clean_learning_quality,
    _is_gradeable_quiz,
    generate_learning_assets,
)


def _quiz(answer_index, options):
    return QuizItem(question="무엇일까요?", options=options, answer_index=answer_index)


def _assets(pages_quiz):
    pages = [
        LearningPageAssets(
            page=i,
            translated_text="text",
            vocab=[VocabItem(word="사과", meaning="apple")],
            comprehension_questions=[],
            quiz=quiz,
        )
        for i, quiz in enumerate(pages_quiz, start=1)
    ]
    return LearningAssets(
        source_language=Language.ko,
        target_language=Language.en,
        title_translation="Title",
        pages=pages,
        parent_guide=ParentGuide(summary="s", discussion_prompts=[], activities=[]),
    )


def test_is_gradeable_quiz():
    assert _is_gradeable_quiz(_quiz(1, ["가", "나", "다"])) is True
    assert _is_gradeable_quiz(_quiz(3, ["가", "나"])) is False  # 정답 인덱스 초과
    assert _is_gradeable_quiz(_quiz(0, ["가", "가"])) is False  # 중복 보기
    assert _is_gradeable_quiz(_quiz(0, ["가", " \t "])) is False
    assert _is_gradeable_quiz(_quiz(0, ["A seed", "Ａ  seed "])) is False


def test_quality_gate_drops_ungradeable_quizzes():
    assets = _assets(
        [
            [_quiz(1, ["가", "나"]), _quiz(3, ["가", "나"])],  # valid + invalid(index)
            [_quiz(0, ["가", "가"])],  # invalid(dup)
            [],
            [],
        ]
    )
    issues = _assess_and_clean_learning_quality(assets)
    assert any("채점 불가 퀴즈 2개" in s for s in issues)
    remaining = sum(len(p.quiz) for p in assets.pages)
    assert remaining == 1


def test_quality_gate_flags_empty_quiz():
    assets = _assets([[], [], [], []])  # vocab 있음, quiz 없음
    issues = _assess_and_clean_learning_quality(assets)
    assert "퀴즈 0개" in issues
    assert "어휘 0개" not in issues


def test_quality_gate_drops_ungrounded_quiz():
    # 정답 '우주 비행사'는 본문에 없음 → 환각 의심 드롭. '숲속 친구'는 본문에 있음 → 유지.
    assets = _assets(
        [
            [
                _quiz(0, ["숲속 친구", "바닷가"]),
                _quiz(0, ["우주 비행사", "공룡"]),
            ],
            [],
            [],
            [],
        ]
    )
    story_text = "오늘 숲속 친구를 만났어요."
    issues = _assess_and_clean_learning_quality(assets, story_text)
    assert any("환각" in s for s in issues)
    assert sum(len(p.quiz) for p in assets.pages) == 1  # '숲속 친구'만 유지


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pages, languages, accepted",
    [
        ([4, 2, 1, 3], (Language.ko, Language.en), True),
        ([1, 2, 2, 4], (Language.ko, Language.en), False),
        ([1, 2, 3, 5], (Language.ko, Language.en), False),
        ([1, 2, 3, 4], (Language.en, Language.ko), False),
    ],
)
async def test_learning_assets_require_the_same_story_pages_and_languages(monkeypatch, pages, languages, accepted):
    from src.services import llm

    story = SimpleNamespace(
        language=Language.ko,
        pages=[SimpleNamespace(page=number, text="토끼가 사과를 먹었다.") for number in range(1, 5)],
    )
    assets = _assets([[], [], [], []])
    assets.source_language, assets.target_language = languages
    for page, number in zip(assets.pages, pages, strict=True):
        page.page = number
    provider = AsyncMock(return_value=assets)
    monkeypatch.setattr(llm, "call_learning_assets", provider)

    result = await generate_learning_assets(story)
    assert result is (assets if accepted else None)
    provider.assert_awaited_once_with(story, Language.ko, Language.en)


@pytest.mark.asyncio
async def test_mock_english_story_can_return_learning_assets():
    story = SimpleNamespace(
        language=Language.en,
        title="A short story",
        target_age=TargetAge.a7_9,
        moral="Patience",
        pages=[SimpleNamespace(page=number, text="The rabbit waited.") for number in range(1, 5)],
    )
    assets = await generate_learning_assets(story)
    assert assets is not None
    assert (assets.source_language, assets.target_language) == (Language.en, Language.ko)
