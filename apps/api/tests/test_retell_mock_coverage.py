"""M3 회귀 게이트 — 연령 리텔링(retell)이 mock 프로바이더에서 완주한다.

2026-08-09 중간 E2E: `POST /v1/books/{id}/retell` 이 mock 구성에서 **항상 500**
(`LLM_JSON_INVALID`)이었다. mock LLM 이 프롬프트 유형 5개만 분기하고 나머지는
`{"result": "mock response"}` 로 폴백하는데, 프롬프트 템플릿 8종 중
`rewrite_story_for_age.system.jinja2` 하나만 그 분기에 걸리지 않았기 때문이다.

핵심 차별화 기능(연령 리텔링)이 단위 테스트 밖에서는 한 번도 통과된 적이 없었다는 뜻이다.
mock 커버리지 공백은 '실제 결함이 있어도 알 수 없는 상태'를 만든다.
"""

import pytest

from src.models.dto import Language, TargetAge
from src.services.llm import call_story_retext


@pytest.mark.asyncio
@pytest.mark.parametrize("target_age", ["3-5", "5-7", "7-9", "adult"])
async def test_retell_returns_valid_story_in_mock(target_age):
    original = [
        "페이지 1: 토끼는 숲속을 걸으며 새로운 모험을 시작했어요.",
        "페이지 2: 다람쥐 친구를 만났어요.",
        "페이지 3: 함께 별을 보았어요.",
    ]
    result = await call_story_retext(
        title="용감한 토끼의 숲속 모험",
        pages_text=original,
        target_age=target_age,
        language="ko",
    )
    assert result.title.strip(), "retell 제목이 비었다"
    assert len(result.pages) == len(original), (
        f"pages 길이가 원본과 다르다 — 삽화 재사용 계약 위반: "
        f"{len(result.pages)} != {len(original)}"
    )
    assert all(str(p).strip() for p in result.pages), "빈 페이지 본문이 있다"


@pytest.mark.asyncio
async def test_no_prompt_falls_through_to_mock_fallback():
    """모든 프롬프트 템플릿이 mock 의 fallback 센티널로 떨어지지 않는지.

    주의(범위 한정): 이 검사는 `{"result": "mock response"}` 폴백만 잡는다. **분기에
    걸리더라도 스키마가 어긋나면** 여전히 500 이다 — 실제로 `rewrite_page_text` 는
    '스토리' 분기에 걸려 StoryDraft 모양을 돌려주지만 엔드포인트는 `RewriteResult`
    (page/revised_text)를 기대한다(2026-08-09 발견, 이번 수정 범위 밖 — 보고서 참조).
    스키마 정합까지 보려면 프롬프트별 기대 타입 매핑이 필요하다.
    """
    from pathlib import Path

    from src.services.llm import _call_mock

    prompts_dir = Path(__file__).resolve().parents[1] / "src" / "prompts"
    # rewrite_page_text 는 user 프롬프트가 템플릿이 아니라 코드에서 f-string 으로 만들어진다
    # (llm.py `call_page_rewrite`). 실제 형태를 넣어야 분기 판정이 실제와 일치한다.
    inline_user_prompts = {
        "rewrite_page_text.system.jinja2": (
            "입력:\n- language: ko\n- target_age: 5-7\n- forbidden_elements: []\n"
            "- page: 2\n- original_text: 토끼가 숲을 걸었어요.\n- page_scene: 숲\n"
            "- book_summary: 제목 - 교훈\n- feedback: 더 밝게\n\n"
            "요청:\n피드백을 반영해 revised_text를 작성하라."
        ),
    }
    uncovered = []
    for path in sorted(prompts_dir.glob("*.system.jinja2")):
        system_prompt = path.read_text(encoding="utf-8")
        user_prompt = inline_user_prompts.get(path.name, "")
        user_path = path.with_name(path.name.replace(".system.", ".user."))
        if not user_prompt and user_path.exists():
            user_prompt = user_path.read_text(encoding="utf-8")
        raw = await _call_mock(system_prompt, user_prompt, 1000, 0.7)
        if '"result": "mock response"' in raw or '"result":"mock response"' in raw:
            uncovered.append(path.name)

    assert uncovered == [], (
        f"mock LLM 이 커버하지 못하는 프롬프트: {uncovered} — 해당 기능은 mock 구성에서 "
        "항상 500 이며 E2E 사각지대가 된다"
    )


@pytest.mark.asyncio
async def test_retell_endpoint_succeeds(client, db_session):
    """엔드포인트 레벨 — 매트릭스 #14 재검증."""
    import uuid

    from src.models.db import Book, Job, Page

    user_key = str(uuid.uuid4())
    book_id = f"book_retell_{uuid.uuid4().hex[:8]}"
    job_id = f"job_retell_{uuid.uuid4().hex[:8]}"
    db_session.add(Job(id=job_id, status="done", progress=100, user_key=user_key))
    await db_session.flush()
    db_session.add(
        Book(
            id=book_id,
            job_id=job_id,
            user_key=user_key,
            title="용감한 토끼의 숲속 모험",
            language=Language.ko.value,
            target_age=TargetAge.a5_7.value,
            style="watercolor",
            cover_image_url="https://picsum.photos/seed/1/768/1024",
        )
    )
    for i in range(1, 4):
        db_session.add(
            Page(
                book_id=book_id,
                page_number=i,
                text=f"페이지 {i}: 토끼는 숲속을 걸었어요.",
                image_url=f"https://picsum.photos/seed/{i}/768/1024",
                image_prompt="prompt",
            )
        )
    await db_session.commit()

    res = await client.post(
        f"/v1/books/{book_id}/retell",
        headers={"X-User-Key": user_key, "X-Idempotency-Key": str(uuid.uuid4())},
        json={"target_age": "3-5"},
    )
    assert res.status_code == 200, (
        f"retell 엔드포인트 실패(M3 회귀): {res.status_code} {res.text[:400]}"
    )


@pytest.mark.asyncio
async def test_page_rewrite_returns_rewrite_result_shape():
    """S1 — mock 페이지 재작성이 `RewriteResult` 스키마로 완주한다.

    수정 전에는 '스토리' 분기에 걸려 StoryDraft 모양이 나왔고, 엔드포인트는 잡 등록 200 만
    돌려주므로 **조용히 실패**했다(매트릭스 #12/#22 가 두 라운드 연속 false-pass).
    페이지 번호 보존과 '실제로 바뀐 텍스트'까지 확인한다.
    """
    from src.models.dto import BookSpec, StoryDraft
    from src.services.llm import call_story_generation, call_text_rewrite

    spec = BookSpec(
        topic="토끼의 숲속 모험", target_age="5-7", style="watercolor",
        page_count=8, language="ko",
    )
    story: StoryDraft = await call_story_generation(spec)
    original = next(p.text for p in story.pages if p.page == 2)

    result = await call_text_rewrite(spec, story, page_number=2, feedback="더 밝게")

    assert result.page == 2, f"페이지 번호가 보존되지 않았다: {result.page}"
    assert result.revised_text.strip(), "재작성 텍스트가 비었다"
    assert result.revised_text != original, "텍스트가 실제로 바뀌지 않았다"
