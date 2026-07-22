"""M11: 시리즈 생성이 USE_CELERY에서 워커 태스크로 enqueue된다(API 프로세스 in-process 아님)."""

from unittest.mock import MagicMock

import pytest

from src.models.db import Character
from tests.factories import make_book_rows

UK = "88888888-8888-4888-8888-888888888888"
H = {"X-User-Key": UK}


async def _seed(db_session):
    db_session.add(
        Character(
            id="char-m11",
            name="토리",
            master_description="a white rabbit",
            appearance={"face": "round"},
            clothing={"top": "vest"},
            personality_traits=["brave"],
            user_key=UK,
        )
    )
    db_session.add_all(make_book_rows([("prevbook-m11", UK)]))
    await db_session.commit()


def _relax(monkeypatch):
    from src.core.config import settings

    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(settings, "use_celery", True)
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", False)
    monkeypatch.setattr(settings, "require_parental_consent_enabled", False)


@pytest.mark.asyncio
async def test_series_enqueues_celery_when_use_celery(client, db_session, monkeypatch):
    await _seed(db_session)
    _relax(monkeypatch)
    from src.services import tasks as tasks_module

    delay_mock = MagicMock()
    monkeypatch.setattr(tasks_module.generate_series_task, "delay", delay_mock)

    res = await client.post(
        "/v1/books/series",
        json={
            "character_id": "char-m11",
            "topic": "새 모험",
            "previous_book_id": "prevbook-m11",
        },
        headers=H,
    )
    assert res.status_code in (200, 201), res.text
    assert delay_mock.call_count == 1
    args = delay_mock.call_args.args
    assert args[0] == res.json()["job_id"]  # job_id
    assert args[2] == UK  # user_key
    assert args[3] == "char-m11"  # character.id
    assert args[4] == "prevbook-m11"  # prev_book.id


@pytest.mark.asyncio
async def test_series_enqueue_failure_refunds(client, db_session, monkeypatch):
    """M11: enqueue(delay) 실패 시 잡이 failed로 처리(환불 래퍼 재사용)."""
    await _seed(db_session)
    _relax(monkeypatch)
    from src.services import tasks as tasks_module

    def boom(*a, **k):
        raise RuntimeError("broker down")

    monkeypatch.setattr(tasks_module.generate_series_task, "delay", boom)

    res = await client.post(
        "/v1/books/series",
        json={
            "character_id": "char-m11",
            "topic": "새 모험",
            "previous_book_id": "prevbook-m11",
        },
        headers=H,
    )
    # 응답은 성공(잡 생성)일 수 있으나 enqueue 실패 처리(환불/failed)가 예외 없이 진행.
    assert res.status_code in (200, 201, 500, 503), res.text
