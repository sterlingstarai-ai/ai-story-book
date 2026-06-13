#!/usr/bin/env python3
"""골든 프롬프트 구조검증 하니스 — CLI.

`docs/qa/golden-prompts.json` 의 기준 프롬프트를 실제 생성 파이프라인으로 통과시키고
출시 품질의 구조 계약을 결정적으로 검증한다.

기본(mock, 키 불필요 — CI 게이트):
    python scripts/golden_prompts_harness.py
    → 구조검증(파이프라인 완주·페이지 정합·placeholder 없음·학습자산·퀴즈·warnings/asset_status)

실키 품질 실측(--live, 키 필요 — 창업자 결정 단계):
    LLM_PROVIDER=openai IMAGE_PROVIDER=gemini ... \
      python scripts/golden_prompts_harness.py --live --report-dir results/golden
    → 위 구조검증 + 내용검증(언어/연령/단어수 + quality_check.py) + 산출물 덤프
      (의미 축=이야기구조/정서톤/캐릭터일관성/시각/번역정합은 자동채점 안 함 → 사람·LLM 심사)

종료코드: 0=구조검증 전부 통과, 1=하나라도 실패.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# `import src.*` 가 cwd 와 무관하게 동작하도록 apps/api 를 경로에 추가.
API_DIR = Path(__file__).resolve().parents[1]  # apps/api
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GOLDEN = REPO_ROOT / "docs" / "qa" / "golden-prompts.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden", type=Path, default=DEFAULT_GOLDEN, help="golden-prompts.json 경로"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="실키 모드(mock 강제 안 함). 내용검증 + 산출물 덤프 추가.",
    )
    parser.add_argument("--report", type=Path, help="JSON 리포트 출력 경로")
    parser.add_argument(
        "--report-dir", type=Path, help="(live) 의미 심사용 산출물 덤프 디렉토리"
    )
    parser.add_argument("--json", action="store_true", help="요약 대신 JSON 만 출력")
    return parser.parse_args()


def _configure_env(live: bool) -> None:
    """src 임포트 *이전* 에 환경을 설정한다(settings 는 임포트 시점에 env 를 읽음)."""
    # 운영 DB 오염 방지 — 항상 전용 임시 sqlite 사용.
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{API_DIR / '.golden_harness.db'}"
    os.environ.setdefault("S3_ACCESS_KEY", "test-access-key")
    os.environ.setdefault("S3_SECRET_KEY", "test-secret-key")
    if not live:
        os.environ["TESTING"] = "true"
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["IMAGE_PROVIDER"] = "mock"
        os.environ["TTS_PROVIDER"] = "mock"
    else:
        os.environ.setdefault("TESTING", "false")
        # 실키 모드: provider/키는 .env / 호출 환경을 그대로 사용.


def _print_summary(report) -> None:
    print(f"\n== 골든 프롬프트 구조검증 하니스 (mode={report.mode}) ==")
    for p in report.prompts:
        status = "✅ PASS" if p.passed() else "❌ FAIL"
        print(f"\n[{status}] {p.prompt_id}  (job={p.job_status})")
        for c in p.checks:
            if c.passed is True:
                mark = "  ✅"
            elif c.passed is False:
                mark = "  ❌"
            else:
                mark = "  ⏸ "  # 미실행/유예
            print(f"{mark} [{c.kind}/{c.severity}] {c.name}: {c.detail}")
        for note in p.notes:
            print(f"     · {note}")
        if p.artifact_path:
            print(f"     · 산출물: {p.artifact_path}")
    s = report.to_dict()["summary"]
    print(
        f"\n== 구조검증: {s['structural_passed']}/{s['total']} 통과"
        f" ({s['structural_failed']} 실패) =="
    )


def main() -> int:
    args = _parse_args()
    _configure_env(args.live)

    # env 설정 후에 임포트
    from src.qa.golden_harness import run_harness

    report = asyncio.run(
        run_harness(args.golden, live=args.live, report_dir=args.report_dir)
    )

    if args.json:
        import json

        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_summary(report)

    if args.report:
        import json

        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n리포트 저장: {args.report}")

    return 0 if report.structural_passed() else 1


if __name__ == "__main__":
    sys.exit(main())
