"""읽기 성장 측정(growth) — 복합점수·tiered 어휘·또래 비교 테스트."""

import pytest

from src.core.utils import utcnow
from src.models.db import ChildProfile, QuizAnswer, ReadingLog
from src.services.growth import (
    composite_reading_score,
    estimate_reading_level,
    growth_service,
)

H = {"X-User-Key": "11111111-1111-4111-8111-111111111111"}
FRESH = {"X-User-Key": "22222222-2222-4222-8222-222222222222"}


def _profile(user_key: str, age_band: str, idx: int) -> ChildProfile:
    return ChildProfile(
        id=f"p-{user_key}",
        user_key=user_key,
        name=f"아이{idx}",
        age_band=age_band,
        is_default=True,
    )


def _reads(user_key: str, n: int, *, completed: bool = False, prefix: str = ""):
    return [
        ReadingLog(
            user_key=user_key,
            book_id=f"{prefix}{user_key}-bk{j}",
            read_date=utcnow(),
            completed=completed,
        )
        for j in range(n)
    ]


def _vocab(user_key: str, term: str, times: int, *, correct: bool = True):
    return [
        QuizAnswer(
            user_key=user_key,
            book_id="bk",
            quiz_type="vocab",
            term=term,
            correct=correct,
        )
        for _ in range(times)
    ]


@pytest.mark.asyncio
async def test_growth_empty_returns_zeros(client):
    res = await client.get("/v1/growth", headers=FRESH)
    assert res.status_code == 200
    data = res.json()
    assert data["books_read"] == 0
    assert data["quiz_total"] == 0
    assert data["vocab_learned"] == 0
    assert data["quiz_accuracy"] == 0.0
    assert data["completion"] == 0.0
    assert data["reading_level"]["level"] == 1
    assert data["reading_level"]["estimated"] is True


@pytest.mark.asyncio
async def test_record_answers_and_tiered_vocab(client):
    # tiered: '습득'은 정답 ≥2회. 사과·바나나는 2회씩 → 습득, 포도는 1회 → 미습득
    answers = (
        [{"book_id": "b1", "quiz_type": "vocab", "correct": True, "term": "사과"}] * 2
        + [{"book_id": "b1", "quiz_type": "vocab", "correct": True, "term": "바나나"}] * 2
        + [{"book_id": "b1", "quiz_type": "vocab", "correct": True, "term": "포도"}]  # 1회
        + [{"book_id": "b1", "quiz_type": "comprehension", "correct": False}]
    )
    for a in answers:
        r = await client.post("/v1/growth/answers", json=a, headers=H)
        assert r.status_code == 200, r.text

    data = (await client.get("/v1/growth", headers=H)).json()
    assert data["quiz_total"] == 6
    assert data["quiz_correct"] == 5
    assert data["vocab_learned"] == 2  # 사과·바나나만(포도 1회는 거짓양성 차단)
    assert data["reading_level"]["level"] >= 1


@pytest.mark.asyncio
async def test_books_read_counts_distinct(db_session):
    uk = "reader-1"
    db_session.add_all(
        [
            ReadingLog(user_key=uk, book_id="bookA", read_date=utcnow()),
            ReadingLog(user_key=uk, book_id="bookA", read_date=utcnow()),  # 중복
            ReadingLog(user_key=uk, book_id="bookB", read_date=utcnow()),
        ]
    )
    await db_session.commit()
    report = await growth_service.get_growth_report(db_session, uk)
    assert report["books_read"] == 2


def test_estimate_reading_level_monotonic():
    low = estimate_reading_level(0, 0.0, 0)["level"]
    high = estimate_reading_level(60, 1.0, 200)["level"]
    assert low == 1 and high == 10 and high > low


def test_composite_score_is_multiaxis_and_monotonic():
    zero = composite_reading_score(0, 0, 0.0, 0.0, "5-7")
    full = composite_reading_score(20, 80, 1.0, 1.0, "5-7")
    assert zero["level"] == 1
    assert full["level"] > zero["level"]
    assert 0 <= zero["score"] <= 100 and 0 <= full["score"] <= 100
    # 다축: 책 수가 같아도 정확도·완독이 높으면 점수가 더 높다(단일축 아님)
    books_only = composite_reading_score(8, 0, 0.0, 0.0, "5-7")["score"]
    books_plus = composite_reading_score(8, 0, 1.0, 1.0, "5-7")["score"]
    assert books_plus > books_only


@pytest.mark.asyncio
async def test_peer_comparison_baseline_when_sparse(db_session):
    uk = "solo-79"
    db_session.add(_profile(uk, "7-9", 0))
    db_session.add_all(_reads(uk, 20, completed=True))
    await db_session.commit()

    res = await growth_service.get_peer_comparison(db_session, uk)
    assert res["is_baseline"] is True  # 또래(본인 제외) < 5명 → 기준선
    assert res["age_band"] == "7-9"
    assert res["show_ranking"] is True  # 7-9세는 등수 노출 가능
    assert "score" in res["my"] and "score" in res["peer_avg"]
    assert res["my"]["books_read"] == 20


@pytest.mark.asyncio
async def test_peer_comparison_real_cohort_composite_ranks(db_session):
    # 최상위 계정: 책10(완독) + 어휘3(각2회) + 정확도 100%
    db_session.add(_profile("u_top", "5-7", 0))
    db_session.add_all(_reads("u_top", 10, completed=True))
    for t in ("가", "나", "다"):
        db_session.add_all(_vocab("u_top", t, 2, correct=True))
    # 또래 5명(활성): 책만 1~5권, 미완독·퀴즈 없음 → 낮은 복합점수
    for i, n in enumerate([1, 2, 3, 4, 5]):
        db_session.add(_profile(f"p{i}", "5-7", 10 + i))
        db_session.add_all(_reads(f"p{i}", n))
    await db_session.commit()

    top = await growth_service.get_peer_comparison(db_session, "u_top")
    assert top["is_baseline"] is False
    assert top["peer_count"] == 5  # 본인 제외 활성 또래
    assert "score" in top["my"]
    assert top["medal"] in ("gold", "silver")

    bottom = await growth_service.get_peer_comparison(db_session, "p0")
    assert bottom["top_percent"] > top["top_percent"]  # 최하위가 상위% 더 큼


@pytest.mark.asyncio
async def test_peer_comparison_excludes_self_and_inactive(db_session):
    db_session.add(_profile("ux", "5-7", 0))
    db_session.add_all(_reads("ux", 3, completed=True))
    # 활성 또래 5
    for i in range(5):
        db_session.add(_profile(f"act{i}", "5-7", 20 + i))
        db_session.add_all(_reads(f"act{i}", 2))
    # 비활성 가입자 3(프로필만, 활동 0) — 코호트에서 제외돼야
    for i in range(3):
        db_session.add(_profile(f"idle{i}", "5-7", 40 + i))
    await db_session.commit()

    res = await growth_service.get_peer_comparison(db_session, "ux")
    assert res["peer_count"] == 5  # 본인·비활성 3 제외(8 후보 중 활성 5)
    assert res["is_baseline"] is False


@pytest.mark.asyncio
async def test_peer_comparison_show_ranking_false_for_young(db_session):
    db_session.add(_profile("young", "3-5", 0))
    db_session.add_all(_reads("young", 2, completed=True))
    await db_session.commit()

    res = await growth_service.get_peer_comparison(db_session, "young")
    assert res["age_band"] == "3-5"
    assert res["show_ranking"] is False  # 전조작기: 등수 무의미 → UI는 자기성장만


@pytest.mark.asyncio
async def test_peer_comparison_endpoint(client, db_session):
    uk = "55555555-5555-4555-8555-555555555555"
    db_session.add(_profile(uk, "5-7", 9))
    await db_session.commit()

    res = await client.get("/v1/growth/peers", headers={"X-User-Key": uk})
    assert res.status_code == 200, res.text
    body = res.json()
    for k in (
        "age_band", "peer_count", "is_baseline", "show_ranking",
        "my", "peer_avg", "top_percent", "medal",
    ):
        assert k in body
