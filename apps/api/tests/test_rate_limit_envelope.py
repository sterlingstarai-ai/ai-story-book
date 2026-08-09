"""M2 회귀 게이트 — 429 응답 봉투의 에러 코드 규약.

2026-08-09 중간 E2E: 서버 429 봉투 코드만 소문자 `rate_limit_exceeded` 였다. 다른 모든
코드는 UPPER_SNAKE(`VALIDATION_ERROR`·`NOT_FOUND`·`PAYMENT_REQUIRED`…)다. 모바일
(`api_error.dart`)은 서버 봉투 코드를 상태코드 매핑보다 **우선**하므로
`case 'RATE_LIMIT_EXCEEDED'` 에 매칭하지 못했고, 결과적으로 en/ja 사용자에게 서버가 준
한국어 문구가 그대로 노출됐다(M15 로컬라이즈 게이트 우회).

모바일 쪽 짝 테스트: `apps/mobile/test/api_error_test.dart` 의 '실제 서버 429 봉투' 케이스.
"""

import pathlib

import pytest

from src.core.exceptions import RateLimitError


def test_rate_limit_error_uses_upper_snake_code():
    err = RateLimitError(retry_after=60)
    assert err.error_code == "RATE_LIMIT_EXCEEDED", (
        f"에러 코드 규약 위반: {err.error_code!r} — 클라이언트 코드 매칭이 깨진다"
    )


def test_rate_limit_error_carries_retry_after_in_details_and_header():
    err = RateLimitError(retry_after=45)
    assert err.details == {"retry_after": 45}
    assert err.headers == {"Retry-After": "45"}, (
        "표준 Retry-After 헤더가 사라지면 클라이언트 백오프가 깨진다"
    )


@pytest.mark.asyncio
async def test_429_response_envelope_matches_contract(client, monkeypatch):
    """실제 HTTP 응답 봉투를 확인한다 — 코드/details/헤더가 계약대로인지."""
    from src.core import rate_limit as rate_limit_module

    async def always_limited(_user_key):
        return False, 0

    monkeypatch.setattr(rate_limit_module.rate_limiter, "is_allowed", always_limited)
    monkeypatch.setattr(
        rate_limit_module.settings, "rate_limit_enforce_in_testing", True
    )

    res = await client.get(
        "/v1/credits/balance", headers={"X-User-Key": "11111111-1111-1111-1111-111111111111"}
    )

    assert res.status_code == 429, f"429가 나오지 않았다: {res.status_code}"
    body = res.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED", (
        f"봉투 코드 규약 위반: {body['error']['code']!r}"
    )
    assert body["error"]["details"] == {"retry_after": 60}
    assert res.headers.get("retry-after") == "60", "Retry-After 헤더 누락"


# --------------------------------------------------------------- 규약 불변식(일반화)


def test_all_envelope_error_codes_are_upper_snake():
    """모든 봉투 에러 코드가 UPPER_SNAKE 인지 소스에서 전수 확인한다.

    M2 는 rate_limit 한 곳만 고쳤는데, 예산·과부하 가드(429/503)에 같은 소문자 코드가
    3곳 더 있었다(라이브 검증 중 발견). 규약 위반은 클라이언트 코드 매칭을 조용히
    깨뜨리므로(en/ja 에 한국어 노출) 소스 레벨로 잠근다.
    """
    import re

    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    bad = []
    for path in src.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for code in re.findall(r'error_code\s*=\s*"([^"]+)"', line):
                if not re.fullmatch(r"[A-Z][A-Z0-9_]*", code):
                    bad.append(f"{path.name}:{i} {code!r}")
    assert bad == [], f"UPPER_SNAKE 가 아닌 봉투 코드: {bad}"


def test_routers_do_not_hand_roll_error_envelopes():
    """라우터가 HTTPException detail 딕셔너리로 봉투 코드를 직접 만들지 않는다.

    `raise HTTPException(detail={"error": "...", ...})` 패턴이 바로 소문자 코드가 새어
    들어온 경로다. 봉투는 `APIError`(및 서브클래스)를 통해서만 만든다 — 그래야 코드 규약·
    details·headers 처리가 한 곳에 모인다.
    """
    import re

    routers = pathlib.Path(__file__).resolve().parents[1] / "src" / "routers"
    offenders = []
    for path in sorted(routers.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"HTTPException\((.{0,400}?)\)", text, re.S):
            block = match.group(1)
            if '"error"' in block or "'error'" in block:
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
    assert offenders == [], (
        f"HTTPException 으로 봉투를 직접 만든 곳: {offenders} — APIError 를 쓸 것"
    )
