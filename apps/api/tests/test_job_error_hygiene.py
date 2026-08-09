"""A1-R 회귀 게이트 — **저장된** 잡 에러가 서빙될 때의 위생.

2026-08-09 CTO 반송: A1 은 예외 핸들러 경로만 위생 처리했다. 그런데 워커가
`jobs.error_message` 에 저장한 `str(e)` 원문이 **잡 상태 조회 엔드포인트로 그대로**
서빙된다 — pydantic 덤프 + `input_value`(모델 응답 원문 조각)까지. 실키에선 미검열
생성물 유출 경로다.

H2 에서 배운 것과 같은 구조다: 쓰기 경로만 고치면 **이미 저장된 행**이 그대로 샌다.
따라서 서빙 시점 위생이 load-bearing이고, 저장 시점 정리는 그 위의 방어선이다.
그래서 이 파일의 정본 테스트는 '원문이 이미 DB 에 있는' 상태를 시드해서 검증한다.
"""

import uuid

import pytest
from sqlalchemy import select

from src.core.errors import ErrorCode, client_safe_message
from src.models.db import Job

PYDANTIC_DUMP = (
    "응답 검증 실패: 2 validation errors for RewriteResult\n"
    "page\n  Field required [type=missing, "
    "input_value={'title': '용감한 토끼', 'pages': ['비밀 원문 조각']}, input_type=dict]\n"
    "For further information visit https://errors.pydantic.dev/2.10/v/missing"
)

LEAK_MARKERS = ("pydantic", "input_value", "errors.pydantic.dev", "RewriteResult",
                "비밀 원문 조각", "validation error")


async def _seed_failed_job(db_session, *, code: str, message: str) -> tuple[str, str]:
    user_key = str(uuid.uuid4())
    job_id = f"job_hyg_{uuid.uuid4().hex[:10]}"
    db_session.add(
        Job(
            id=job_id,
            status="failed",
            progress=100,
            current_step="실패",
            user_key=user_key,
            error_code=code,
            error_message=message[:300],
        )
    )
    await db_session.commit()
    return job_id, user_key


# ------------------------------------------------------------------ 서빙 시점(정본)


@pytest.mark.asyncio
async def test_stored_dump_is_not_served(client, db_session):
    """이미 원문이 저장된 잡 행이어도 상태 조회 응답에 덤프가 없어야 한다."""
    job_id, user_key = await _seed_failed_job(
        db_session, code=ErrorCode.LLM_JSON_INVALID.value, message=PYDANTIC_DUMP
    )

    res = await client.get(f"/v1/books/{job_id}", headers={"X-User-Key": user_key})
    assert res.status_code == 200, res.text[:300]
    body = res.text

    for marker in LEAK_MARKERS:
        assert marker not in body, (
            f"저장된 잡 에러 원문이 서빙됐다(A1-R 회귀): {marker!r} 노출\n{body[:500]}"
        )

    # DB 원문은 남아 있어도(진단용) 응답만 위생 처리된 것이 정본 동작이다.
    stored = (
        await db_session.execute(select(Job).where(Job.id == job_id))
    ).scalar_one()
    assert stored.error_message  # 시드값 그대로 존재


@pytest.mark.asyncio
async def test_error_code_is_preserved_for_retry_decisions(client, db_session):
    """위생 처리가 error.code 정보성을 깎지 않는다(재시도 판단 근거).

    메시지는 일반화하되, 코드는 그대로여야 클라이언트가 재시도 가능 여부를 판단한다.
    """
    for code in (
        ErrorCode.LLM_TIMEOUT,
        ErrorCode.IMAGE_RATE_LIMIT,
        ErrorCode.STORAGE_UPLOAD_FAILED,
        ErrorCode.QUEUE_FAILED,
    ):
        job_id, user_key = await _seed_failed_job(
            db_session, code=code.value, message="internal trace xyz"
        )
        res = await client.get(f"/v1/books/{job_id}", headers={"X-User-Key": user_key})
        assert res.status_code == 200
        error = res.json()["error"]
        assert error["code"] == code.value, f"error.code 가 뭉개졌다: {error}"
        assert "internal trace xyz" not in error["message"]


@pytest.mark.asyncio
async def test_safety_message_still_reaches_user(client, db_session):
    """SAFETY_* 는 사용자가 조치할 수 있는 안내다 — 일반화하면 안 된다."""
    actionable = "입력에 폭력적인 표현이 포함되어 있습니다. 다른 주제를 시도해보세요."
    job_id, user_key = await _seed_failed_job(
        db_session, code=ErrorCode.SAFETY_INPUT.value, message=actionable
    )
    res = await client.get(f"/v1/books/{job_id}", headers={"X-User-Key": user_key})
    assert res.json()["error"]["message"] == actionable


# ------------------------------------------------------------------ 규칙 단위


def test_client_safe_message_rules():
    assert client_safe_message(ErrorCode.SAFETY_OUTPUT, "안전 안내") == "안전 안내"
    assert client_safe_message(ErrorCode.SAFETY_INPUT, "   ") != "   "  # 빈 값이면 일반 문구
    generic = client_safe_message(ErrorCode.LLM_JSON_INVALID, PYDANTIC_DUMP)
    for marker in LEAK_MARKERS:
        assert marker not in generic
    # enum 밖 코드(job_monitor 의 SLA_BREACH 등)도 안전하게 일반 문구로 떨어진다.
    assert client_safe_message("SLA_BREACH", PYDANTIC_DUMP) == generic
    assert client_safe_message(None, PYDANTIC_DUMP) == generic


# ------------------------------------------------------------------ 저장 시점(2차 방어)


@pytest.mark.asyncio
async def test_worker_failure_marking_stores_sanitized_message(db_session):
    """워커 실패 마킹은 원문을 저장하지 않는다(저장 시점 방어).

    서빙 시점 위생이 정본이지만, 저장 자체를 줄여 로그 외 유출면을 없앤다.
    """
    from src.services.tasks import _mark_job_failed_async

    user_key = str(uuid.uuid4())
    job_id = f"job_store_{uuid.uuid4().hex[:10]}"
    db_session.add(
        Job(id=job_id, status="running", progress=50, current_step="생성 중",
            user_key=user_key)
    )
    await db_session.commit()

    await _mark_job_failed_async(job_id, PYDANTIC_DUMP)

    await db_session.commit()  # 다른 세션의 변경을 보기 위해 트랜잭션 갱신
    stored = (
        await db_session.execute(select(Job).where(Job.id == job_id))
    ).scalar_one()
    await db_session.refresh(stored)
    assert stored.status == "failed"
    for marker in LEAK_MARKERS:
        assert marker not in (stored.error_message or ""), (
            f"저장된 메시지에 원문이 남았다: {marker!r} / {stored.error_message!r}"
        )
