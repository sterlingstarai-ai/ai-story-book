"""#4 [M12/H24]: 재생성·리텔·인페인트 안전 게이트가 ja/zh/es에서 no-op이 아니어야 한다.

M12가 배선한 게이트는 ko/en 키워드망(_moderate_text)만 써서, ja/zh/es 텍스트는 입력·출력
모두 무조건 통과했다. H24가 메인 파이프라인에서 확립한 '키워드망 밖 언어 = fail-open 금지'와
정면 모순 — 출시 5개 언어 중 3종에서 아동 안전망을 우회해 폭력·성인 표현을 본문에 저장 가능.
"""

import pytest

from src.models.dto import Language


@pytest.mark.asyncio
async def test_japanese_unsafe_text_is_blocked_by_llm_fallback(monkeypatch):
    """ja 텍스트는 키워드망을 통과해도 LLM 폴백이 차단해야 한다."""
    from src.services import orchestrator as orch

    called = {}

    class _Result:
        is_safe = False
        reasons = ["violence"]

    async def fake_call_output_moderation(text, language):
        called["text"] = text
        called["language"] = language
        return _Result()

    monkeypatch.setattr(
        "src.services.llm.call_output_moderation", fake_call_output_moderation
    )

    ok = await orch.moderate_text_localized(
        "オオカミがウサギを殺して血まみれにする", Language.ja
    )
    assert ok is False, "ja 텍스트가 안전망을 무조건 통과하면 안 됨"
    assert called["language"] == Language.ja


@pytest.mark.asyncio
async def test_korean_path_does_not_call_llm(monkeypatch):
    """ko/en은 키워드망이 커버 — 불필요한 LLM 호출(비용·지연) 없음."""
    from src.services import orchestrator as orch

    async def boom(text, language):  # pragma: no cover - 호출되면 실패
        raise AssertionError("ko는 LLM 폴백을 호출하면 안 됨")

    monkeypatch.setattr("src.services.llm.call_output_moderation", boom)

    assert await orch.moderate_text_localized("토끼가 숲으로 갔어요", Language.ko) is True


@pytest.mark.asyncio
async def test_keyword_hit_short_circuits_before_llm(monkeypatch):
    """키워드망에서 이미 걸리면 LLM을 부르지 않고 즉시 차단."""
    from src.services import orchestrator as orch

    async def boom(text, language):  # pragma: no cover
        raise AssertionError("키워드 차단 시 LLM 호출 불필요")

    monkeypatch.setattr("src.services.llm.call_output_moderation", boom)

    unsafe_ko = "칼로 찔러 죽이는 장면"
    if orch._moderate_text(unsafe_ko):
        pytest.skip("키워드망이 이 표현을 차단하지 않음 — 케이스 부적합")
    assert await orch.moderate_text_localized(unsafe_ko, Language.ja) is False


@pytest.mark.asyncio
async def test_safe_japanese_text_passes(monkeypatch):
    """정상 ja 텍스트는 통과(과잉 차단 방지)."""
    from src.services import orchestrator as orch

    class _Result:
        is_safe = True
        reasons = []

    async def fake_call(text, language):
        return _Result()

    monkeypatch.setattr("src.services.llm.call_output_moderation", fake_call)

    assert await orch.moderate_text_localized("うさぎが森へ行きました", Language.ja) is True
