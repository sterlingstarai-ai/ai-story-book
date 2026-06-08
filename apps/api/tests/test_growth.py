"""읽기 성장 측정(growth) — 응답 기록 + 집계 리포트 테스트."""

import pytest

from src.core.utils import utcnow
from src.models.db import ReadingLog
from src.services.growth import estimate_reading_level, growth_service

H = {"X-User-Key": "11111111-1111-4111-8111-111111111111"}
FRESH = {"X-User-Key": "22222222-2222-4222-8222-222222222222"}


@pytest.mark.asyncio
async def test_growth_empty_returns_zeros(client):
    res = await client.get("/v1/growth", headers=FRESH)
    assert res.status_code == 200
    data = res.json()
    assert data["books_read"] == 0
    assert data["quiz_total"] == 0
    assert data["vocab_learned"] == 0
    assert data["quiz_accuracy"] == 0.0
    assert data["reading_level"]["level"] == 1
    assert data["reading_level"]["estimated"] is True


@pytest.mark.asyncio
async def test_record_answers_and_aggregate(client):
    # vocab 2개 정답(서로 다른 단어) + vocab 1개 오답 + comprehension 1개 정답
    answers = [
        {"book_id": "b1", "quiz_type": "vocab", "correct": True, "term": "사과"},
        {"book_id": "b1", "quiz_type": "vocab", "correct": True, "term": "바나나"},
        {"book_id": "b1", "quiz_type": "vocab", "correct": False, "term": "포도"},
        {"book_id": "b1", "quiz_type": "comprehension", "correct": True},
    ]
    for a in answers:
        r = await client.post("/v1/growth/answers", json=a, headers=H)
        assert r.status_code == 200, r.text
        assert r.json()["recorded"] is True

    data = (await client.get("/v1/growth", headers=H)).json()
    assert data["quiz_total"] == 4
    assert data["quiz_correct"] == 3
    assert data["quiz_accuracy"] == 0.75
    assert data["vocab_learned"] == 2  # 정답 vocab의 distinct term
    assert data["reading_level"]["level"] >= 1


@pytest.mark.asyncio
async def test_books_read_counts_distinct(db_session):
    uk = "reader-1"
    db_session.add_all(
        [
            ReadingLog(user_key=uk, book_id="bookA", read_date=utcnow()),
            ReadingLog(user_key=uk, book_id="bookA", read_date=utcnow()),  # 중복 책
            ReadingLog(user_key=uk, book_id="bookB", read_date=utcnow()),
        ]
    )
    await db_session.commit()

    report = await growth_service.get_growth_report(db_session, uk)
    assert report["books_read"] == 2  # distinct


def test_estimate_reading_level_monotonic():
    low = estimate_reading_level(0, 0.0, 0)["level"]
    high = estimate_reading_level(60, 1.0, 200)["level"]
    assert low == 1
    assert high == 10
    assert high > low
