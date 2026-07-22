"""Money-path per-glob coverage gate (L2).

전역 커버리지 임계(CI: API 40% / Flutter 25%)는 결제·크레딧 파일이 0%로 떨어져도
전역만 넘으면 통과시킨다. 이 게이트는 money 경로 각 파일의 라인 커버리지가 지정 임계
이상인지 coverage.xml에서 검사해, 결제 코드의 테스트 소실을 릴리스 게이트가 감지하게 한다.

임계값은 '현행 실측 기준 회귀 방지' 원칙 — 지금 통과하는 값보다 약간 아래로 잡아, 커버리지가
크게 떨어질 때만 red. money 티켓들이 테스트를 추가하면 이후 상향할 수 있다.

사용: python scripts/coverage_gate.py [coverage.xml]
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

# 파일 경로(coverage.xml의 filename과 동일 형식) → 최소 라인 커버리지(%).
# 값은 2026-07-22 실측(각 파일 실제 커버리지)에서 약 5%p 아래로 잡은 '회귀 방지' 기준선:
# credits 74.6 / routers.credits 77.3 / iap_verifier 39.4 / routers.iap 58.0 / periodic 65.3.
# money 티켓들이 테스트를 추가하면 이 기준선을 상향한다(특히 iap_verifier는 커버리지가 낮음).
MONEY_PATH_THRESHOLDS: dict[str, float] = {
    "services/credits.py": 70.0,
    "routers/credits.py": 72.0,
    "services/iap_verifier.py": 35.0,
    "routers/iap.py": 52.0,
    "services/periodic_credits.py": 60.0,
}


def parse_coverage(xml_path: str) -> dict[str, float]:
    """coverage.xml → {filename: line-rate percent}.

    coverage.py의 cobertura xml은 <class filename="..." line-rate="0.xx"> 형식.
    filename은 --cov=src 기준 상대경로(예: services/credits.py).
    """
    root = ET.parse(xml_path).getroot()
    result: dict[str, float] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename")
        if filename is None:
            continue
        result[filename] = float(cls.get("line-rate", "0")) * 100.0
    return result


def evaluate(
    coverage: dict[str, float], thresholds: dict[str, float]
) -> list[str]:
    """임계 미달(또는 데이터 부재) 파일의 사유 목록. 빈 리스트면 통과."""
    failures: list[str] = []
    for path, min_pct in thresholds.items():
        actual = coverage.get(path)
        if actual is None:
            failures.append(
                f"{path}: coverage 데이터 없음 — 테스트가 이 money 경로를 전혀 실행하지 않음"
            )
        elif actual < min_pct:
            failures.append(f"{path}: {actual:.1f}% < 임계 {min_pct:.0f}%")
    return failures


def main(xml_path: str = "coverage.xml") -> int:
    coverage = parse_coverage(xml_path)
    failures = evaluate(coverage, MONEY_PATH_THRESHOLDS)
    if failures:
        print("Money-path coverage gate FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("Money-path coverage gate passed (all money paths meet per-file thresholds).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "coverage.xml"))
