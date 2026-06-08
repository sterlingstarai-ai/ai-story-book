"""읽기 성장 측정(growth) — 응답 기록 + 집계 리포트 테스트."""

import pytest

from src.core.utils import utcnow
from src.models.db import ChildProfile, ReadingLog
from src.services.growth import (
    AGE_BASELINES,
    estimate_reading_level,
    growth_service,
)


def _profile(user_key: str, age_band: str, idx: int) -> ChildProfile:
    return ChildProfile(
        id=f"p-{user_key}",
        user_key=user_key,
        name=f"아이{idx}",
        age_band=age_band,
        is_default=True,
    )

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


@pytest.mark.asyncio
async def test_peer_comparison_baseline_when_sparse(db_session):
    uk = "solo-79"
    db_session.add(_profile(uk, "7-9", 0))
    db_session.add_all(
        [ReadingLog(user_key=uk, book_id=f"bk{i}", read_date=utcnow()) for i in range(20)]
    )
    await db_session.commit()

    res = await growth_service.get_peer_comparison(db_session, uk)
    assert res["is_baseline"] is True  # 또래 < 5명 → 기준선
    assert res["age_band"] == "7-9"
    assert res["peer_avg"]["books_read"] == AGE_BASELINES["7-9"]["books_read"]
    assert res["my"]["books_read"] == 20
    # 20권 vs 기준선 15 → ratio 1.33 → 상위 15% → silver
    assert res["top_percent"] == 15
    assert res["medal"] == "silver"


@pytest.mark.asyncio
async def test_peer_comparison_real_cohort_ranks(db_session):
    counts = {"u0": 1, "u1": 2, "u2": 3, "u3": 4, "u4": 5, "u5": 10}
    for i, (uk, n) in enumerate(counts.items()):
        db_session.add(_profile(uk, "5-7", i))
        db_session.add_all(
            [
                ReadingLog(user_key=uk, book_id=f"{uk}-bk{j}", read_date=utcnow())
                for j in range(n)
            ]
        )
    await db_session.commit()

    top = await growth_service.get_peer_comparison(db_session, "u5")
    assert top["is_baseline"] is False
    assert top["peer_count"] == 6
    assert top["my"]["books_read"] == 10
    assert top["peer_avg"]["books_read"] == 4.2  # 25/6
    assert top["top_percent"] <= 10
    assert top["medal"] == "gold"

    bottom = await growth_service.get_peer_comparison(db_session, "u0")
    assert bottom["top_percent"] > 60  # 하위권
    assert bottom["medal"] == "none"


@pytest.mark.asyncio
async def test_peer_comparison_consistent_scope_multi_profile(db_session):
    # 또래 5명(5-7), 각 1권
    for i in range(5):
        uk = f"peer{i}"
        db_session.add(_profile(uk, "5-7", 100 + i))
        db_session.add(
            ReadingLog(user_key=uk, book_id=f"{uk}-b", read_date=utcnow())
        )
    # 다자녀 계정: 프로필 P1, 책 10권(절반 P1·절반 P2 스코프) = 계정 합계 10권
    db_session.add(
        ChildProfile(
            id="P1", user_key="multi", name="첫째", age_band="5-7", is_default=True
        )
    )
    for j in range(10):
        db_session.add(
            ReadingLog(
                user_key="multi",
                profile_id="P1" if j < 5 else "P2",
                book_id=f"multi-b{j}",
                read_date=utcnow(),
            )
        )
    await db_session.commit()

    # P1 프로필로 조회해도 또래 분포(user_key 단위)와 동일 스코프로 비교 → 최상위
    res = await growth_service.get_peer_comparison(db_session, "multi", profile_id="P1")
    assert res["peer_count"] == 6  # peer0~4 + multi
    assert res["my"]["books_read"] == 10  # 프로필로 5권으로 축소되지 않음(스코프 일관)
    assert res["top_percent"] <= 10
    assert res["medal"] == "gold"


@pytest.mark.asyncio
async def test_peer_comparison_endpoint(client, db_session):
    uk = "55555555-5555-4555-8555-555555555555"
    db_session.add(_profile(uk, "5-7", 9))
    await db_session.commit()

    res = await client.get("/v1/growth/peers", headers={"X-User-Key": uk})
    assert res.status_code == 200, res.text
    body = res.json()
    for k in (
        "age_band",
        "peer_count",
        "is_baseline",
        "my",
        "peer_avg",
        "top_percent",
        "medal",
    ):
        assert k in body
