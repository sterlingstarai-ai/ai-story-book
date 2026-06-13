"""골든 프롬프트 구조검증 하니스 — CI 게이트 + 체크 변별력(teeth) 증명.

두 가지를 보장한다.
1) 게이트: 모든 골든 프롬프트가 실제 mock 파이프라인을 완주하고 구조 계약을 통과한다.
2) teeth: 결정적 체크들이 *고장 난 출력을 실제로 떨어뜨린다*(rubber-stamp 방지).
   정상 베이스라인은 실제 파이프라인 산출물이고, 불량 케이스는 그 model_dump 를 외과적으로
   훼손한 것이라 스키마 드리프트에 강하다.
"""

import uuid
from pathlib import Path

import pytest
import pytest_asyncio

from src.core.database import async_engine
from src.models.dto import BookResult
from src.qa.golden_harness import (
    _generate_one,
    build_book_spec,
    run_harness,
    setup_db,
    structural_checks,
    teardown_db,
)

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "docs" / "qa" / "golden-prompts.json"

_BASELINE_ENTRY = {
    "id": "baseline-ko-5-7",
    "language": "ko",
    "target_age": "5-7",
    "style": "watercolor",
    "theme": "우정",
    "topic": "토끼와 다람쥐가 함께 겨울 먹이를 찾는 이야기",
}

# 구조검증 게이트에서 반드시 존재해야 하는 핵심 항목(누락 시 게이트가 비어버림 방지).
# quiz_* 는 항상 대칭으로 방출되므로(없으면 None) 포함 가능 — 누가 체크를 통째로 지우면 잡힘.
_REQUIRED_STRUCTURAL = {
    "pipeline_completed",
    "pages_well_formed",
    "cover_image_present",
    "page_images_present",
    "learning_assets_present",
    "no_degraded_warnings",
    "asset_status_generated",
    "language_matches_spec",
    "target_age_matches_spec",
    "quiz_gradeable",
    "quiz_grounded",
}


@pytest_asyncio.fixture
async def golden_db():
    """앱 async 엔진에 테이블을 만들고 끝나면 정리(다른 테스트 격리)."""
    await setup_db()
    try:
        yield
    finally:
        await teardown_db()
        # 모듈 전역 async_engine 의 풀을 비워 드롭된 스키마로의 stale 커넥션이 후속 테스트로
        # 새어 SQLite 락/플래키를 일으키지 않게 한다.
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_all_golden_prompts_pass_structural(golden_db):
    """게이트: 실제 golden-prompts.json 전부 구조검증 통과."""
    report = await run_harness(GOLDEN_PATH, live=False, manage_db=False)

    assert report.prompts, "골든 프롬프트가 하나도 로드되지 않음"
    assert report.structural_passed(), (
        "구조검증 실패: "
        + "; ".join(
            f"{p.prompt_id}: {[c.name for c in p.structural_failures()]}"
            for p in report.prompts
            if not p.passed()
        )
    )

    # 각 프롬프트가 실제로 생성됐고, 핵심 체크가 존재하며, False 가 없어야 한다.
    for p in report.prompts:
        assert p.generated, f"{p.prompt_id} 생성 실패(job={p.job_status} err={p.error_code})"
        names = {c.name for c in p.checks}
        missing = _REQUIRED_STRUCTURAL - names
        assert not missing, f"{p.prompt_id} 핵심 구조 체크 누락: {missing}"
        false_checks = [
            c.name for c in p.checks if c.kind == "structural" and c.passed is False
        ]
        assert not false_checks, f"{p.prompt_id} 구조 체크 실패: {false_checks}"

        # 골든 베이스라인은 채점가능·근거 있는 퀴즈를 산출해야 한다(퀴즈가 통째로 사라지면
        # quiz_* 가 True→None 으로 바뀌므로, None 이 아니라 True 임을 명시 단언해 회귀를 잡는다).
        by_name = {c.name: c for c in p.checks}
        assert by_name["quiz_gradeable"].passed is True, (
            f"{p.prompt_id} 퀴즈 채점가능 회귀: {by_name['quiz_gradeable'].detail}"
        )
        assert by_name["quiz_grounded"].passed is True, (
            f"{p.prompt_id} 퀴즈 근거 회귀: {by_name['quiz_grounded'].detail}"
        )


def _outcome_map(result: BookResult, spec):
    return {c.name: c.passed for c in structural_checks(result, spec)}


def _quiz_page(dump: dict):
    for lp in (dump.get("learning_assets") or {}).get("pages", []):
        if lp.get("quiz"):
            return lp
    return None


@pytest.mark.asyncio
async def test_structural_checks_have_teeth(golden_db):
    """teeth: 정상은 전부 통과, 각 불량 변형은 *해당* 체크를 떨어뜨린다."""
    spec = build_book_spec(_BASELINE_ENTRY)
    gen = await _generate_one(spec, str(uuid.uuid4()))
    assert gen["result"] is not None, f"베이스라인 생성 실패: {gen}"
    healthy: BookResult = gen["result"]

    # 정상 베이스라인: 결정적 구조 체크에 False 가 하나도 없어야 한다(false-FAIL 방지).
    healthy_map = _outcome_map(healthy, spec)
    healthy_false = [k for k, v in healthy_map.items() if v is False]
    assert not healthy_false, f"정상 출력이 구조 체크에서 떨어짐: {healthy_false}"
    # 학습자산/퀴즈 체크가 실제로 평가됐는지(mock 에 퀴즈 존재) 확인.
    assert healthy_map.get("quiz_gradeable") is True
    assert healthy_map.get("learning_assets_present") is True

    base = healthy.model_dump()

    def _mutate(fn):
        import copy

        d = copy.deepcopy(base)
        fn(d)
        return BookResult.model_validate(d)

    def _set_placeholder_cover(d):
        d["cover_image_url"] = "https://placeholder.invalid/image-unavailable.png"

    def _set_placeholder_page(d):
        d["pages"][0]["image_url"] = "https://placeholder.invalid/image-unavailable.png"

    def _drop_learning(d):
        d["learning_assets"] = None

    def _remove_page(d):
        d["pages"].pop(1)  # 페이지 2 제거 → 비연속

    def _degrade_status(d):
        d["pages"][0]["asset_status"]["image"] = {
            "state": "degraded",
            "reason": "placeholder_image",
            "url": "https://placeholder.invalid/x.png",
        }

    def _add_warning(d):
        d["generation_warnings"].append(
            {
                "code": "page_placeholder_image",
                "message": "임시 이미지",
                "asset": "image",
                "page_number": 1,
            }
        )

    def _mismatch_style(d):
        d["style"] = "pixel"  # spec 은 watercolor

    def _mismatch_language(d):
        d["language"] = "ja"  # spec 은 ko

    def _mismatch_target_age(d):
        d["target_age"] = "7-9"  # spec 은 5-7

    def _dup_quiz_options(d):
        lp = _quiz_page(d)
        assert lp is not None
        lp["quiz"][0]["options"] = ["같다", "같다"]
        lp["quiz"][0]["answer_index"] = 0

    def _ungrounded_quiz(d):
        lp = _quiz_page(d)
        assert lp is not None
        lp["quiz"][0]["options"] = ["zzqqxx", "wwvvtt"]
        lp["quiz"][0]["answer_index"] = 0

    cases = {
        "cover_image_present": _set_placeholder_cover,
        "page_images_present": _set_placeholder_page,
        "learning_assets_present": _drop_learning,
        "pages_well_formed": _remove_page,
        "asset_status_generated": _degrade_status,
        "no_degraded_warnings": _add_warning,
        "style_matches_spec": _mismatch_style,
        "language_matches_spec": _mismatch_language,
        "target_age_matches_spec": _mismatch_target_age,
        "quiz_gradeable": _dup_quiz_options,
        "quiz_grounded": _ungrounded_quiz,
    }

    for check_name, mutate in cases.items():
        # 전제: 정상은 이 체크를 통과한다(변별 가능 대상).
        assert healthy_map.get(check_name) is True, (
            f"정상 베이스라인이 {check_name} 를 통과하지 않아 teeth 검증 불가"
        )
        mutated = _mutate(mutate)
        outcomes = _outcome_map(mutated, spec)
        assert outcomes.get(check_name) is False, (
            f"불량 변형이 {check_name} 를 떨어뜨리지 못함(rubber-stamp 위험): "
            f"got {outcomes.get(check_name)}"
        )
