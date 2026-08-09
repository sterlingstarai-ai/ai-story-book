"""S2 회귀 게이트 — 읽기 레벨 라벨의 서버 로컬라이즈.

2026-08-09 중간 E2E 후속: `GET /v1/growth` 의 `reading_level.label` 이 서버에서 한국어
고정("첫 걸음"·"꾸준히 성장")이라 en/ja 사용자에게 그대로 노출됐다. 클라이언트 폴백만
현지화해도 **서버가 값을 주면** 한국어가 나온다.

M5 에서 확립한 '안정 키 우선' 원칙을 그대로 적용한다: 응답에 `reading_level.key`(예:
`first_steps`)를 싣고, `label` 은 사용자 언어(user_settings.language, tz 와 동일 패턴)로
로컬라이즈한다. 클라이언트는 key 로 자체 l10n, label 은 폴백.
"""

import re
import uuid

import pytest

from src.services.growth import LEVEL_KEYS, composite_reading_score, level_label

HANGUL = re.compile(r"[가-힣]")


def test_every_level_has_stable_key():
    """1~10 전 레벨에 안정 키가 있다(클라 l10n 의 기준)."""
    assert set(LEVEL_KEYS) == set(range(1, 11))
    for key in LEVEL_KEYS.values():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", key), f"불안정한 키 형태: {key!r}"


@pytest.mark.parametrize("language", ["en", "ja"])
def test_labels_are_localized_not_korean(language):
    for level in range(1, 11):
        label = level_label(level, language)
        assert label.strip(), f"{language} level={level} 라벨이 비었다"
        assert not HANGUL.search(label), (
            f"{language} 라벨에 한국어가 남아있다: level={level} label={label!r}"
        )


def test_korean_labels_preserved():
    """ko 는 기존 문구를 유지한다(불필요한 회귀 금지)."""
    assert level_label(1, "ko") == "첫 걸음"
    assert level_label(5, "ko") == "꾸준히 성장"


def test_unsupported_language_falls_back_to_english():
    """스토리 언어는 5종(zh/es 포함)이지만 UI 라벨은 ko/en/ja — 그 외는 영어 폴백."""
    for language in ("zh", "es", "fr", "", None):
        label = level_label(3, language)
        assert not HANGUL.search(label), f"{language!r} 에서 한국어 노출: {label!r}"


def test_composite_score_carries_key_and_localized_label():
    result = composite_reading_score(8, 40, 0.8, 1.0, "5-7", language="en")
    assert result["key"] == LEVEL_KEYS[result["level"]]
    assert not HANGUL.search(result["label"])


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "ja"])
async def test_growth_endpoint_localizes_level_label(client, db_session, language):
    """엔드포인트 실측 — 사용자 언어 설정에 따라 라벨이 로컬라이즈된다."""
    headers = {"X-User-Key": str(uuid.uuid4())}
    patched = await client.patch(
        "/v1/settings", headers=headers, json={"language": language}
    )
    assert patched.status_code == 200, patched.text[:200]

    res = await client.get("/v1/growth", headers=headers)
    assert res.status_code == 200, res.text[:200]
    level = res.json()["reading_level"]

    assert level.get("key"), f"안정 키가 없다: {level}"
    assert not HANGUL.search(level["label"]), (
        f"{language} 사용자에게 한국어 라벨이 노출됐다(S2 회귀): {level}"
    )


@pytest.mark.asyncio
async def test_growth_endpoint_defaults_to_korean(client, db_session):
    """설정이 없으면 기본 ko — 기존 동작 유지."""
    headers = {"X-User-Key": str(uuid.uuid4())}
    res = await client.get("/v1/growth", headers=headers)
    level = res.json()["reading_level"]
    assert level["label"] == "첫 걸음"
    assert level["key"] == "first_steps"


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "ja"])
async def test_query_param_overrides_settings(client, db_session, language):
    """앱은 UI 로캘을 서버에 저장하지 않는다(L13 기기 추종) — 쿼리 파라미터가 정본 경로다."""
    headers = {"X-User-Key": str(uuid.uuid4())}
    res = await client.get(f"/v1/growth?language={language}", headers=headers)
    assert res.status_code == 200, res.text[:200]
    level = res.json()["reading_level"]
    assert not HANGUL.search(level["label"]), (
        f"쿼리 파라미터 {language} 인데 한국어 라벨이 나왔다: {level}"
    )


@pytest.mark.asyncio
async def test_invalid_language_param_is_rejected(client, db_session):
    res = await client.get("/v1/growth?language=xx", headers={"X-User-Key": str(uuid.uuid4())})
    assert res.status_code == 422
