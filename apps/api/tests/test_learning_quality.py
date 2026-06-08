"""학습 자산 품질 게이트 — 채점 불가 퀴즈 제거 + 미달 플래그."""

from src.models.dto import (
    Language,
    LearningAssets,
    LearningPageAssets,
    ParentGuide,
    QuizItem,
    VocabItem,
)
from src.services.orchestrator import (
    _assess_and_clean_learning_quality,
    _is_gradeable_quiz,
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
