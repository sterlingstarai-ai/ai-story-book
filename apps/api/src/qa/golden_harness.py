"""골든 프롬프트 구조검증 하니스.

`docs/qa/golden-prompts.json` 의 기준 프롬프트들을 **실제 생성 파이프라인**으로 통과시키고,
그 결과(BookResult)가 출시 품질의 **구조 계약**을 지키는지 결정적으로 검증한다.

설계 핵심
---------
- **드라이버는 in-process 오케스트레이터**(`start_book_generation`)를 직접 호출한다.
  HTTP 라우터(`POST /v1/books`)를 우회하므로 무료플랜 스타일게이트·크레딧·일일한도 같은
  job-setup 마찰이 없다(프리미엄 스타일도 그대로 통과). 결과는 운영과 동일한 읽기 경로
  (`_build_book_result`)로 DB에서 재구성한다 — 검증 로직 중복 0.
- **두 단계의 검증을 분리한다.**
    · STRUCTURAL(구조): mock provider로 키 없이 *지금* 결정적으로 검증 가능.
      (파이프라인 완주·페이지 정합·placeholder 없음·학습자산 존재·퀴즈 채점가능/근거·
       generation_warnings/asset_status 정합) → **CI 게이트**.
    · CONTENT(내용): 실키 생성물에 대해서만 의미가 있는 결정적 검사
      (연령별 단어수·언어/연령 일치) + `scripts/quality_check.py` 재사용 → **--live**.
    · SEMANTIC(의미): 이야기 구조·정서 톤·캐릭터 일관성·표지-본문 시각 일관성·번역 의미정합.
      LLM/사람 심사가 필요(판정자 보정·기준쌍 없이 자동 채점 금지 — target leakage 위험).
      자동 채점하지 않고 산출물을 덤프하고 "미실행(심사 필요)"로 **명시 보고**한다.

mock의 한계(정직 보고)
----------------------
mock LLM은 요청 언어/연령(`language`/`target_age`)을 프롬프트에서 감지해 반영하므로, spec→story
*전파* 일치(`language_matches_spec`/`target_age_matches_spec`)와 `style`은 mock 에서도 구조검증된다.
그러나 mock 텍스트는 고정 길이/내용이라 *내용*이 연령에 맞는지(단어수)·품질 점수·의미 축은
검증할 수 없다 → CONTENT/SEMANTIC(live 전용).
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from src.core.book_assets import is_placeholder_asset_url
from src.core.database import AsyncSessionLocal, Base, async_engine
from src.models.db import Book, Job, Page
from src.models.dto import BookResult, BookSpec, Language, Style, TargetAge, Theme

# 운영 정의를 단일 출처로 재사용한다(하니스의 '유효' 개념을 파이프라인과 일치시킴).
from src.services.orchestrator import (
    _grounding_corpus,
    _is_gradeable_quiz,
    _quiz_answer_grounded,
    start_book_generation,
)

# 연령별 단어수 기준 — scripts/quality_check.py 의 AGE_REQUIREMENTS 와 정렬.
AGE_REQUIREMENTS: Dict[str, Dict[str, int]] = {
    "3-5": {"min_words_per_page": 10, "max_words_per_page": 30},
    "5-7": {"min_words_per_page": 20, "max_words_per_page": 50},
    "7-9": {"min_words_per_page": 30, "max_words_per_page": 70},
    "adult": {"min_words_per_page": 40, "max_words_per_page": 120},
}

# 의미(SEMANTIC) 축 — 자동 채점하지 않고 산출물과 함께 "심사 필요"로 보고한다.
SEMANTIC_AXES = [
    ("이야기 구조", "도입-갈등-해결의 명확성"),
    ("연령 적합성(정서 톤)", "자극 강도·정서 안정성이 연령에 맞는가"),
    ("캐릭터 일관성", "외형/성격/말투가 끝까지 유지되는가"),
    ("시각 품질", "표지와 본문 장면의 분위기·연속성"),
    ("이중언어 의미정합", "원문과 번역 학습자산이 의미적으로 정합하는가"),
]


# ==================== 결과 모델 ====================


@dataclass
class CheckOutcome:
    """단일 검증 항목의 결과.

    passed=None 은 '미실행/유예'(SEMANTIC 또는 live 전용을 mock에서 건너뜀)를 뜻한다.
    """

    name: str
    axis: str
    kind: str  # "structural" | "content" | "semantic"
    severity: str  # "critical" | "high" | "info"
    passed: Optional[bool]
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PromptReport:
    prompt_id: str
    spec: Dict[str, Any]
    generated: bool
    job_status: str
    error_code: Optional[str]
    book_id: Optional[str]
    checks: List[CheckOutcome] = field(default_factory=list)
    artifact_path: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def structural_failures(self) -> List[CheckOutcome]:
        return [
            c
            for c in self.checks
            if c.kind == "structural" and c.passed is False
        ]

    def passed(self) -> bool:
        """구조검증 게이트 통과 여부(STRUCTURAL 항목만 평가)."""
        return self.generated and not self.structural_failures()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "spec": self.spec,
            "generated": self.generated,
            "job_status": self.job_status,
            "error_code": self.error_code,
            "book_id": self.book_id,
            "passed": self.passed(),
            "checks": [c.to_dict() for c in self.checks],
            "artifact_path": self.artifact_path,
            "notes": self.notes,
        }


@dataclass
class HarnessReport:
    mode: str  # "mock" | "live"
    golden_path: str
    prompts: List[PromptReport] = field(default_factory=list)

    def structural_passed(self) -> bool:
        return all(p.passed() for p in self.prompts) and bool(self.prompts)

    def to_dict(self) -> Dict[str, Any]:
        total = len(self.prompts)
        passed = sum(1 for p in self.prompts if p.passed())
        return {
            "mode": self.mode,
            "golden_path": self.golden_path,
            "summary": {
                "total": total,
                "structural_passed": passed,
                "structural_failed": total - passed,
            },
            "prompts": [p.to_dict() for p in self.prompts],
        }


# ==================== DB 라이프사이클 ====================


async def setup_db() -> None:
    """앱 async 엔진에 모든 테이블을 생성(idempotent)."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def teardown_db() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ==================== spec 빌드 ====================


def build_book_spec(entry: Dict[str, Any]) -> BookSpec:
    """골든 엔트리 → BookSpec. 유효하지 않은 theme 은 조용히 제거하지 않고 호출부에서 노트 처리."""
    kwargs: Dict[str, Any] = {
        "topic": entry["topic"],
        "language": Language(entry["language"]),
        "target_age": TargetAge(entry["target_age"]),
        "style": Style(entry["style"]),
        "page_count": int(entry.get("page_count", 8)),
    }
    theme = entry.get("theme")
    if theme:
        kwargs["theme"] = Theme(theme)  # 유효하지 않으면 ValueError → 호출부에서 처리
    return BookSpec(**kwargs)


# ==================== 드라이버 ====================


async def _generate_one(spec: BookSpec, user_key: str) -> Dict[str, Any]:
    """Job 행 생성 → 실 파이프라인 구동 → DB 재구성. 반환: {job_status, error_code, result}."""
    job_id = f"golden_{uuid.uuid4().hex[:12]}"

    async with AsyncSessionLocal() as session:
        session.add(Job(id=job_id, status="queued", user_key=user_key))
        await session.commit()

    # start_book_generation 은 예외를 삼키고 Job 을 failed 로 마킹한다(반환 없음).
    await start_book_generation(job_id, spec, user_key)

    async with AsyncSessionLocal() as session:
        job = (
            await session.execute(select(Job).where(Job.id == job_id))
        ).scalar_one_or_none()
        status = job.status if job else "missing"
        error_code = job.error_code if job else None

        result: Optional[BookResult] = None
        if status == "done":
            from src.routers.books import _build_book_result

            book = (
                await session.execute(select(Book).where(Book.job_id == job_id))
            ).scalar_one_or_none()
            if book is not None:
                pages = (
                    (
                        await session.execute(
                            select(Page)
                            .where(Page.book_id == book.id)
                            .order_by(Page.page_number)
                        )
                    )
                    .scalars()
                    .all()
                )
                result = _build_book_result(book, pages)

    return {"job_status": status, "error_code": error_code, "result": result}


# ==================== 검증 배터리 ====================

_SAFETY_ERROR_CODES = {"SAFETY_INPUT", "SAFETY_OUTPUT"}


def structural_checks(result: BookResult, spec: BookSpec) -> List[CheckOutcome]:
    """키 없이 결정적으로 검증 가능한 구조 계약. (mock + live 공통)"""
    out: List[CheckOutcome] = []

    # book_id (운영 추적성)
    out.append(
        CheckOutcome(
            "book_id_present",
            "운영 품질",
            "structural",
            "info",
            bool(result.book_id),
            f"book_id={result.book_id!r}",
        )
    )

    # 페이지 수(유효 범위) + 정합(1-indexed 연속·정렬·텍스트 비어있지 않음)
    pages = result.pages
    page_numbers = [p.page_number for p in pages]
    out.append(
        CheckOutcome(
            "page_count_in_range",
            "이야기 구조",
            "structural",
            "info",
            4 <= len(pages) <= 12,
            f"pages={len(pages)}",
        )
    )
    contiguous = page_numbers == list(range(1, len(pages) + 1))
    nonempty_text = all((p.text or "").strip() for p in pages)
    out.append(
        CheckOutcome(
            "pages_well_formed",
            "이야기 구조",
            "structural",
            "high",
            contiguous and nonempty_text,
            f"numbers={page_numbers} contiguous={contiguous} nonempty_text={nonempty_text}",
        )
    )

    # 스타일(spec 유래 → mock 에서도 유효; 프리미엄 스타일 통과의 증거)
    out.append(
        CheckOutcome(
            "style_matches_spec",
            "운영 품질",
            "structural",
            "high",
            result.style == spec.style.value,
            f"result={result.style!r} spec={spec.style.value!r}",
        )
    )

    # 언어/연령 전파(spec → story → BookResult). mock 이 요청 언어/연령을 충실히 반영하므로
    # 구조 단계에서 검증한다(전파가 깨지면 여기서 잡힘). 단, *내용*이 연령에 맞는지(단어수)는
    # 실 텍스트가 필요 → content(--live).
    out.append(
        CheckOutcome(
            "language_matches_spec",
            "연령/언어 적합성",
            "structural",
            "high",
            result.language == spec.language,
            f"result={result.language.value} spec={spec.language.value}",
        )
    )
    out.append(
        CheckOutcome(
            "target_age_matches_spec",
            "연령 적합성",
            "structural",
            "high",
            result.target_age == spec.target_age,
            f"result={result.target_age.value} spec={spec.target_age.value}",
        )
    )

    # 표지 이미지 — 존재 + placeholder 아님
    cover_ok = bool(result.cover_image_url) and not is_placeholder_asset_url(
        result.cover_image_url
    )
    out.append(
        CheckOutcome(
            "cover_image_present",
            "시각 품질",
            "structural",
            "critical",
            cover_ok,
            f"cover={result.cover_image_url[:60]!r}",
        )
    )

    # 모든 페이지 이미지 — 존재 + placeholder 아님
    bad_imgs = [
        p.page_number
        for p in pages
        if not p.image_url or is_placeholder_asset_url(p.image_url)
    ]
    out.append(
        CheckOutcome(
            "page_images_present",
            "시각 품질",
            "structural",
            "critical",
            not bad_imgs,
            f"placeholder_or_missing_pages={bad_imgs}",
        )
    )

    # generation_warnings — 정상 경로엔 degraded/placeholder 경고가 없어야 함
    out.append(
        CheckOutcome(
            "no_degraded_warnings",
            "운영 품질",
            "structural",
            "high",
            len(result.generation_warnings) == 0,
            f"warnings={[w.code for w in result.generation_warnings]}",
        )
    )

    # asset_status — 모든 페이지 image state == generated (warnings 와 교차검증)
    bad_status = []
    for p in pages:
        img = (p.asset_status or {}).get("image")
        state = img.state if img is not None else None
        if state != "generated":
            bad_status.append((p.page_number, state))
    out.append(
        CheckOutcome(
            "asset_status_generated",
            "운영 품질",
            "structural",
            "high",
            not bad_status,
            f"non_generated={bad_status}",
        )
    )

    # 학습 자산 존재 — ≥1 페이지에 vocab 또는 quiz (GOLDEN_PROMPTS: 빈 학습자산=실패)
    la = result.learning_assets
    la_present = la is not None and any(
        (p.vocab or p.quiz) for p in la.pages
    )
    out.append(
        CheckOutcome(
            "learning_assets_present",
            "학습 자산",
            "structural",
            "critical",
            bool(la_present),
            "learning_assets=None" if la is None else f"pages={len(la.pages)}",
        )
    )

    # 퀴즈 채점가능 + 근거(파이프라인이 이미 보장 — 회귀 안전망). 퀴즈 없으면 vacuous pass + 노트.
    quiz_items = []
    if la is not None:
        for lp in la.pages:
            quiz_items.extend(lp.quiz or [])
        if quiz_items:
            story_text = " ".join(p.text for p in pages)
            corpus = _grounding_corpus(la, story_text)
            ungradeable = [
                q.question[:30] for q in quiz_items if not _is_gradeable_quiz(q)
            ]
            ungrounded = [
                q.question[:30]
                for q in quiz_items
                if not _quiz_answer_grounded(q, corpus)
            ]
            out.append(
                CheckOutcome(
                    "quiz_gradeable",
                    "학습 자산",
                    "structural",
                    "high",
                    not ungradeable,
                    f"ungradeable={ungradeable}",
                )
            )
            out.append(
                CheckOutcome(
                    "quiz_grounded",
                    "학습 자산",
                    "structural",
                    "high",
                    not ungrounded,
                    f"ungrounded={ungrounded}",
                )
            )
    if not quiz_items:
        # 퀴즈가 없으면 두 체크 모두 None(미평가)로 *대칭* 출력 — 보고 구조 일관성 유지 +
        # 한쪽만 사라져 회귀가 가려지는 것 방지. (vocab 만으로 학습자산 충족은 가능.)
        for _name, _msg in (
            ("quiz_gradeable", "퀴즈 항목 없음(vocab 만으로 학습자산 충족 가능)"),
            ("quiz_grounded", "퀴즈 항목 없음(근거 확인 불필요)"),
        ):
            out.append(
                CheckOutcome(_name, "학습 자산", "structural", "info", None, _msg)
            )

    return out


def content_checks(result: BookResult, spec: BookSpec) -> List[CheckOutcome]:
    """실키 생성물에 대해서만 의미 있는 결정적 검사 (live 전용).

    content 항목은 게이트하지 않는다(구조검증만 exit code 결정) → severity=info 로 표기해
    "[content/high] 인데 왜 통과?" 혼동을 없앤다. 언어/연령 *전파* 일치는 structural 로 이동했고,
    여기는 실 텍스트가 있어야 의미 있는 *내용* 검사(연령별 단어수·품질 점수)만 남긴다.
    """
    out: List[CheckOutcome] = []

    # 연령별 단어수 — 실 텍스트에 대해 결정적(mock 텍스트는 고정 길이라 live 전용)
    req = AGE_REQUIREMENTS.get(spec.target_age.value)
    if req:
        offenders = []
        for p in result.pages:
            words = len(re.findall(r"\w+", p.text or ""))
            if not (req["min_words_per_page"] <= words <= req["max_words_per_page"]):
                offenders.append((p.page_number, words))
        out.append(
            CheckOutcome(
                "age_fit_word_counts",
                "연령 적합성",
                "content",
                "info",
                not offenders,
                f"band={req} offenders(page,words)={offenders}",
            )
        )

    # scripts/quality_check.py 재사용(중복 금지) — forbidden/repetition/vocab/character
    qc = _run_quality_check_reused(result, spec)
    if qc is None:
        out.append(
            CheckOutcome(
                "content_quality_score",
                "내용 품질",
                "content",
                "info",
                None,
                "quality_check.py 임포트 불가 — 콘텐츠 점수 미실행(침묵 실패 방지 차원 명시).",
            )
        )
    else:
        for name, sub in qc["checks"].items():
            out.append(
                CheckOutcome(
                    f"qc::{name}",
                    "내용 품질",
                    "content",
                    "info",
                    bool(sub["passed"]),
                    f"score={sub['score']:.2f} {sub['details']}",
                )
            )
    return out


def semantic_deferred(entry: Dict[str, Any]) -> List[CheckOutcome]:
    """의미 축은 자동 채점하지 않는다 — 산출물 + expected_signals 와 함께 '심사 필요'로 보고."""
    signals = entry.get("expected_signals", [])
    out = [
        CheckOutcome(
            f"semantic::{axis}",
            axis,
            "semantic",
            "high",
            None,
            f"심사 필요(자동채점 안 함). {desc}",
        )
        for axis, desc in SEMANTIC_AXES
    ]
    if signals:
        out.append(
            CheckOutcome(
                "semantic::expected_signals",
                "이야기 구조",
                "semantic",
                "info",
                None,
                " | ".join(signals),
            )
        )
    return out


def _run_quality_check_reused(
    result: BookResult, spec: BookSpec
) -> Optional[Dict[str, Any]]:
    """repo-root scripts/quality_check.py 의 run_quality_check 재사용(best-effort)."""
    try:
        scripts_dir = Path(__file__).resolve().parents[4] / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import quality_check  # type: ignore
    except (ImportError, ModuleNotFoundError):
        # 진짜로 파일이 없을 때만 '미실행'으로 표기. 구문/런타임 오류는 삼키지 않고
        # 그대로 터뜨려(loud) 깨진 도구가 '단지 없음'으로 위장되는 false-confidence 를 막는다.
        return None

    book_data = {
        "book_id": result.book_id,
        "title": result.title,
        "target_age": spec.target_age.value,
        "pages": [
            {
                "page_number": p.page_number,
                "text": p.text,
                "image_prompt": p.image_prompt or "",
            }
            for p in result.pages
        ],
    }
    report = quality_check.run_quality_check(book_data)
    return report.to_dict()


# ==================== 산출물 덤프(live, 의미 심사용) ====================


def dump_artifact(result: BookResult, entry: Dict[str, Any], report_dir: Path) -> str:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{entry['id']}.json"
    payload = {
        "prompt": entry,
        "title": result.title,
        "language": result.language.value,
        "target_age": result.target_age.value,
        "style": result.style,
        "cover_image_url": result.cover_image_url,
        "pages": [
            {
                "page_number": p.page_number,
                "text": p.text,
                "text_ko": p.text_ko,
                "text_en": p.text_en,
                "image_url": p.image_url,
                "image_prompt": p.image_prompt,
                "vocab": [v.model_dump() for v in (p.vocab or [])],
                "quiz": [q.model_dump() for q in (p.quiz or [])],
            }
            for p in result.pages
        ],
        "character_sheet": result.character_sheet.model_dump()
        if result.character_sheet
        else None,
        # 캐릭터 시트는 생성 후 DB 에 독립 저장되지 않아 재구성 시 null 이 된다(설계 한계).
        # 캐릭터 일관성 의미 심사는 각 페이지 image_prompt(master_description 포함)로 한다.
        "character_sheet_note": (
            "character_sheet 는 영속화되지 않아 재구성 산출물에선 null 일 수 있음 — "
            "캐릭터 일관성 심사는 pages[*].image_prompt 사용"
        ),
        "learning_assets": result.learning_assets.model_dump()
        if result.learning_assets
        else None,
        "generation_warnings": [w.model_dump() for w in result.generation_warnings],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


# ==================== 단일 프롬프트 실행 ====================


async def run_one(
    entry: Dict[str, Any], *, live: bool, report_dir: Optional[Path]
) -> PromptReport:
    prompt_id = entry.get("id", "unknown")
    notes: List[str] = []

    # spec 빌드(유효성 자체가 검증 — invalid style/theme 는 여기서 드러남)
    try:
        spec = build_book_spec(entry)
    except (ValueError, KeyError) as e:
        return PromptReport(
            prompt_id=prompt_id,
            spec=entry,
            generated=False,
            job_status="invalid_spec",
            error_code=type(e).__name__,
            book_id=None,
            checks=[
                CheckOutcome(
                    "spec_valid",
                    "운영 품질",
                    "structural",
                    "critical",
                    False,
                    f"BookSpec 생성 실패: {e}",
                )
            ],
            notes=[f"골든 엔트리가 유효한 BookSpec 으로 변환되지 않음: {e}"],
        )

    user_key = str(uuid.uuid4())
    gen = await _generate_one(spec, user_key)
    status = gen["job_status"]
    error_code = gen["error_code"]
    result: Optional[BookResult] = gen["result"]

    if result is None:
        # 실패(또는 reconstruct 불가). 안전필터 과잉차단을 별도 표기.
        over_block = error_code in _SAFETY_ERROR_CODES
        detail = f"job_status={status} error_code={error_code}"
        if over_block:
            detail += " — 안전 필터 과잉 차단 의심(양성 프롬프트가 차단됨)"
        return PromptReport(
            prompt_id=prompt_id,
            spec=entry,
            generated=False,
            job_status=status,
            error_code=error_code,
            book_id=None,
            checks=[
                CheckOutcome(
                    "pipeline_completed",
                    "안전 필터 과잉 차단" if over_block else "운영 품질",
                    "structural",
                    "critical",
                    False,
                    detail,
                )
            ],
            notes=notes,
        )

    checks: List[CheckOutcome] = [
        CheckOutcome(
            "pipeline_completed",
            "운영 품질",
            "structural",
            "critical",
            True,
            "job_status=done",
        )
    ]
    checks += structural_checks(result, spec)

    artifact_path: Optional[str] = None
    if live:
        checks += content_checks(result, spec)
        checks += semantic_deferred(entry)
        if report_dir is not None:
            artifact_path = dump_artifact(result, entry, report_dir)
    else:
        notes.append(
            "mock 모드: 단어수·내용품질·의미 축은 미실행(--live 필요). "
            "언어/연령 *전파*는 structural 로 검증됨."
        )

    return PromptReport(
        prompt_id=prompt_id,
        spec=entry,
        generated=True,
        job_status=status,
        error_code=error_code,
        book_id=result.book_id,
        checks=checks,
        artifact_path=artifact_path,
        notes=notes,
    )


# ==================== 엔트리 포인트 ====================


def load_golden(golden_path: Path) -> List[Dict[str, Any]]:
    data = json.loads(Path(golden_path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("golden-prompts.json 은 객체 배열이어야 합니다.")
    return data


async def run_harness(
    golden_path: Path,
    *,
    live: bool = False,
    report_dir: Optional[Path] = None,
    manage_db: bool = True,
) -> HarnessReport:
    """모든 골든 프롬프트를 구동하고 리포트를 반환.

    manage_db=True 면 테이블을 생성한다(standalone). pytest 처럼 외부에서 DB 를 관리하면 False.
    """
    entries = load_golden(golden_path)
    if manage_db:
        await setup_db()

    report = HarnessReport(
        mode="live" if live else "mock",
        golden_path=str(golden_path),
    )
    for entry in entries:
        report.prompts.append(await run_one(entry, live=live, report_dir=report_dir))
    return report
