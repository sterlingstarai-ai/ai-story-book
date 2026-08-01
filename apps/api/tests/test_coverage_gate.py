"""money 경로 per-glob 커버리지 게이트 단위 테스트 (L2).

순수 함수 evaluate/parse_coverage를 픽스처로 검증 — 실제 coverage.xml 없이 결정적.
"""

from __future__ import annotations

from pathlib import Path

from scripts.coverage_gate import MONEY_PATH_THRESHOLDS, evaluate, parse_coverage

THRESHOLDS = {"services/credits.py": 80.0, "services/iap_verifier.py": 75.0}


def test_gate_fails_on_money_path_regression():
    # money 경로 커버리지가 0%로 떨어지면 게이트 실패.
    failures = evaluate({"services/credits.py": 0.0, "services/iap_verifier.py": 90.0}, THRESHOLDS)
    assert any("services/credits.py" in f for f in failures)


def test_gate_fails_when_money_path_absent():
    # money 경로가 coverage에 아예 없으면(테스트 전무) 실패.
    failures = evaluate({}, THRESHOLDS)
    assert len(failures) == 2
    assert all("coverage 데이터 없음" in f for f in failures)


def test_gate_passes_when_money_paths_covered():
    failures = evaluate(
        {"services/credits.py": 92.0, "services/iap_verifier.py": 80.0}, THRESHOLDS
    )
    assert failures == []


def test_gate_ignores_non_money_low_coverage():
    # money 외 파일이 낮아도 money 글로브만 임계 이상이면 통과(전역 임계와 분리).
    failures = evaluate(
        {
            "services/credits.py": 85.0,
            "services/iap_verifier.py": 78.0,
            "routers/some_unrelated.py": 3.0,
        },
        THRESHOLDS,
    )
    assert failures == []


def test_parse_coverage_reads_cobertura_line_rate(tmp_path: Path):
    xml = tmp_path / "coverage.xml"
    xml.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages><package><classes>
    <class filename="services/credits.py" line-rate="0.83"/>
    <class filename="services/iap_verifier.py" line-rate="0.5"/>
  </classes></package></packages>
</coverage>
"""
    )
    cov = parse_coverage(str(xml))
    assert cov["services/credits.py"] == 83.0
    assert cov["services/iap_verifier.py"] == 50.0


def test_money_thresholds_cover_expected_paths():
    # 회귀: money 글로브 목록에 핵심 결제 경로가 빠지지 않도록 고정.
    for expected in ("services/credits.py", "services/iap_verifier.py", "routers/iap.py"):
        assert expected in MONEY_PATH_THRESHOLDS
