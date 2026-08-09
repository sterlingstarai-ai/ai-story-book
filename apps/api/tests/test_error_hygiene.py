"""A1 회귀 게이트 — 도메인 에러가 내부 정보를 클라이언트로 흘리지 않는다.

2026-08-09 CTO 재감사 추가 발견: `POST /v1/books/{id}/retell` 의 500 응답 `detail` 에
pydantic 검증 덤프 원문이 그대로 실려 나갔다(내부 스키마명 `RetoldStory`,
`errors.pydantic.dev` URL). 더 나아가 `LLMError.details` 는 `raw_output`(모델 원문 응답
500자)을 담고 있어 **미검열 생성물**이 그대로 새는 경로였다.

원문은 로그로만, 클라이언트에는 안정 코드 + 일반 문구 + 안전한 키만.
"""

import uuid

import pytest

from src.core.errors import ErrorCode, ImageError, LLMError, SafetyError
from src.main import sanitize_domain_error


def test_llm_validation_dump_is_not_exposed():
    exc = LLMError(
        ErrorCode.LLM_JSON_INVALID,
        "응답 검증 실패: 2 validation errors for RetoldStory\n"
        "title\n  Field required [type=missing, input_value={'result': 'mock response'}]\n"
        "For further information visit https://errors.pydantic.dev/2.10/v/missing",
        raw_output='{"result": "mock response", "internal": "secret"}',
    )
    message, details = sanitize_domain_error(exc)

    assert "RetoldStory" not in message, "내부 스키마명이 노출됐다"
    assert "pydantic" not in message, "pydantic 진단 URL이 노출됐다"
    assert "validation error" not in message.lower()
    assert details is None or "raw_output" not in details, (
        f"raw_output(모델 원문 응답)이 클라이언트로 나간다: {details}"
    )


def test_safety_errors_keep_actionable_message_and_suggestions():
    """안전성 위반은 사용자가 조치할 수 있는 문구다 — 일반화하면 안 된다."""
    exc = SafetyError("폭력적인 표현이 포함되어 있습니다.", is_input=True,
                      suggestions=["다른 주제를 시도해보세요"])
    message, details = sanitize_domain_error(exc)

    assert message == "폭력적인 표현이 포함되어 있습니다."
    assert details == {"suggestions": ["다른 주제를 시도해보세요"]}


def test_non_safety_details_allow_only_whitelisted_keys():
    exc = ImageError(ErrorCode.IMAGE_FAILED, "provider said: internal-trace-xyz", page=3)
    message, details = sanitize_domain_error(exc)

    assert "internal-trace-xyz" not in message
    assert details == {"page": 3}, f"화이트리스트 밖 키가 샜다: {details}"


@pytest.mark.asyncio
async def test_retell_failure_response_is_sanitized(client, db_session, monkeypatch):
    """엔드포인트 실측 — 실패 응답 본문에 내부 덤프가 없다."""
    from src.models.db import Book, Job, Page
    from src.routers import books as books_router

    user_key = str(uuid.uuid4())
    job_id = f"job_hyg_{uuid.uuid4().hex[:8]}"
    book_id = f"book_hyg_{uuid.uuid4().hex[:8]}"
    db_session.add(Job(id=job_id, status="done", progress=100, user_key=user_key))
    await db_session.flush()
    db_session.add(
        Book(
            id=book_id,
            job_id=job_id,
            user_key=user_key,
            title="제목",
            language="ko",
            target_age="5-7",
            style="watercolor",
            cover_image_url="https://picsum.photos/seed/1/768/1024",
        )
    )
    db_session.add(
        Page(
            book_id=book_id, page_number=1, text="본문",
            image_url="https://picsum.photos/seed/2/768/1024", image_prompt="p",
        )
    )
    await db_session.commit()

    async def exploding_retext(**_kwargs):
        raise LLMError(
            ErrorCode.LLM_JSON_INVALID,
            "응답 검증 실패: 2 validation errors for RetoldStory ... errors.pydantic.dev",
            raw_output='{"result": "mock response"}',
        )

    monkeypatch.setattr(books_router, "call_story_retext", exploding_retext, raising=False)
    monkeypatch.setattr(
        "src.services.llm.call_story_retext", exploding_retext, raising=False
    )

    res = await client.post(
        f"/v1/books/{book_id}/retell",
        headers={"X-User-Key": user_key, "X-Idempotency-Key": str(uuid.uuid4())},
        json={"target_age": "3-5"},
    )

    body = res.text
    assert "RetoldStory" not in body, f"내부 스키마명이 응답에 노출됐다: {body[:400]}"
    assert "pydantic" not in body, f"pydantic 진단 URL이 응답에 노출됐다: {body[:400]}"
    assert "mock response" not in body, f"raw_output 이 응답에 노출됐다: {body[:400]}"
