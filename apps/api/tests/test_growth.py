"""읽기 성장 측정(growth) — 복합점수·tiered 어휘·또래 비교 테스트."""

from datetime import date

import pytest

from src.core.utils import derive_age_band, utcnow
from src.models.db import Book, ChildProfile, Job, QuizAnswer, ReadingLog
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
async def test_record_answers_and_vocab_count(client):
    # 학습 어휘 = 정답 1회 이상인 distinct term. 포도는 오답뿐 → 미카운트.
    answers = [
        {"book_id": "b1", "quiz_type": "vocab", "correct": True, "term": "사과"},
        {"book_id": "b1", "quiz_type": "vocab", "correct": True, "term": "바나나"},
        {"book_id": "b1", "quiz_type": "vocab", "correct": False, "term": "포도"},
        {"book_id": "b1", "quiz_type": "comprehension", "correct": False},
    ]
    for a in answers:
        r = await client.post("/v1/growth/answers", json=a, headers=H)
        assert r.status_code == 200, r.text

    data = (await client.get("/v1/growth", headers=H)).json()
    # 정확도(quiz_total/correct)는 vocab 제외 = 독해 1건만. vocab은 vocab_learned로만 집계.
    assert data["quiz_total"] == 1
    assert data["quiz_correct"] == 0
    assert data["vocab_learned"] == 2  # 사과·바나나(포도는 정답 0회 → 제외)
    assert data["reading_level"]["level"] >= 1


@pytest.mark.asyncio
async def test_record_answer_rejects_foreign_book(client, db_session):
    # 남의 책으로 내 성장 지표를 부풀리는 조작 차단(IDOR). 미존재 id는 허용.
    db_session.add(Job(id="job-foreign", status="done", user_key="owner-x"))
    await db_session.flush()
    db_session.add(
        Book(id="book-foreign", job_id="job-foreign", title="t", language="ko",
             target_age="5-7", style="watercolor", user_key="owner-x",
             cover_image_url="https://e/c.png")
    )
    await db_session.commit()

    foreign = await client.post(
        "/v1/growth/answers",
        json={"book_id": "book-foreign", "quiz_type": "comprehension", "correct": True},
        headers=H,
    )
    assert foreign.status_code == 403, foreign.text  # 타 유저 책 → 차단

    unknown = await client.post(
        "/v1/growth/answers",
        json={"book_id": "no-such-book", "quiz_type": "comprehension", "correct": True},
        headers=H,
    )
    assert unknown.status_code == 200, unknown.text  # 미존재 id(데일리/레거시) → 허용


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


def test_derive_age_band_boundaries():
    # 반열린 구간으로 5/7세 경계중복 제거. 기준일 고정(2026-06-09).
    ref = date(2026, 6, 9)
    assert derive_age_band(2024, 6, ref) == "3-5"  # 만 2세(3미만 floor)
    assert derive_age_band(2022, 6, ref) == "3-5"  # 만 4세
    assert derive_age_band(2021, 6, ref) == "5-7"  # 만 5세(경계)
    assert derive_age_band(2020, 6, ref) == "5-7"  # 만 6세
    assert derive_age_band(2019, 7, ref) == "5-7"  # 만 6세 11개월(생일 전)
    assert derive_age_band(2019, 6, ref) == "7-9"  # 만 7세(경계)
    assert derive_age_band(2017, 6, ref) == "7-9"  # 만 9세(아동 상한, adult 아님)


@pytest.mark.asyncio
async def test_create_profile_derives_age_band_from_birth(client):
    # 생년월을 주면 age_band가 자동 파생 — 부모가 보낸(틀린) age_band는 무시.
    r = await client.post(
        "/v1/profiles",
        json={
            "name": "민지", "age_band": "3-5",
            "birth_year": 2019, "birth_month": 3,
        },
        headers=FRESH,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["age_band"] == "7-9"  # 2019-03생(만 7세) → DOB 우선
    assert body["birth_year"] == 2019 and body["birth_month"] == 3


def test_estimate_reading_level_monotonic():
    low = estimate_reading_level(0, 0.0, 0)["level"]
    high = estimate_reading_level(60, 1.0, 200)["level"]
    assert low == 1 and high == 10 and high > low


def test_composite_score_missing_axis_not_penalized():
    # 퀴즈/완독 데이터가 없으면(None) 0점 처벌이 아니라 축을 빼고 재분배(missing≠zero).
    # 같은 책·어휘인데 정확도를 0.0으로 받은 아동보다 '미응시(None)' 아동이 더 높아야 한다.
    none_acc = composite_reading_score(8, 40, None, 1.0, "5-7")["score"]
    zero_acc = composite_reading_score(8, 40, 0.0, 1.0, "5-7")["score"]
    assert none_acc > zero_acc
    # 모든 비율 축이 None이어도 books·vocab만으로 산출되어야 한다(크래시 없음).
    only_counts = composite_reading_score(8, 40, None, None, "5-7")
    assert 0 <= only_counts["score"] <= 100


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
async def test_growth_report_is_profile_scoped_for_multichild(db_session):
    # 한 계정 두 자녀: 성장 리포트의 책수·스트릭이 형제 합산이 아니라 프로필 단위여야 한다.
    uk = "multi-1"
    db_session.add(
        ChildProfile(id="prof-A", user_key=uk, name="형", age_band="7-9", is_default=True)
    )
    db_session.add(
        ChildProfile(id="prof-B", user_key=uk, name="동생", age_band="3-5", is_default=False)
    )
    for j in range(3):
        db_session.add(
            ReadingLog(user_key=uk, profile_id="prof-A", book_id=f"a{j}",
                       read_date=utcnow(), completed=True)
        )
    db_session.add(
        ReadingLog(user_key=uk, profile_id="prof-B", book_id="b0",
                   read_date=utcnow(), completed=True)
    )
    await db_session.commit()

    rep_a = await growth_service.get_growth_report(db_session, uk, "prof-A")
    rep_b = await growth_service.get_growth_report(db_session, uk, "prof-B")
    assert rep_a["books_read"] == 3  # 형제 합산(4) 아님
    assert rep_b["books_read"] == 1
    assert rep_a["total_reading_days"] >= 1  # 프로필 단위 스트릭(ReadingLog.profile_id 기반)
    assert rep_b["total_reading_days"] >= 1


@pytest.mark.asyncio
async def test_peer_comparison_baseline_when_sparse(db_session):
    uk = "solo-79"
    db_session.add(_profile(uk, "7-9", 0))
    db_session.add_all(_reads(uk, 20, completed=True))
    await db_session.commit()

    res = await growth_service.get_peer_comparison(db_session, uk)
    assert res["is_baseline"] is True  # 또래(본인 제외) < 5명 → 기준선
    assert res["age_band"] == "7-9"
    # 또래가 부족하면 7-9세라도 등수/메달을 '또래 비교'로 노출하지 않음(자기성장만).
    assert res["show_ranking"] is False
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
async def test_peer_comparison_midrank_no_gold_for_median(db_session):
    # 본인+또래 5명이 모두 동일 활동(책 2권 완독) → 전부 동점.
    # midrank(동점 절반)로 중앙값 아동이 '상위 1%·금메달'로 부풀려지면 안 됨.
    for i, uk in enumerate(["m_self", "m0", "m1", "m2", "m3", "m4"]):
        db_session.add(_profile(uk, "5-7", 300 + i))
        db_session.add_all(_reads(uk, 2, completed=True))
    await db_session.commit()

    res = await growth_service.get_peer_comparison(db_session, "m_self")
    assert res["peer_count"] == 5
    assert 30 <= res["top_percent"] <= 70  # 동점 → 중앙값(상위 50% 근처)
    assert res["medal"] != "gold"


@pytest.mark.asyncio
async def test_peer_comparison_median_robust_to_outlier(db_session):
    # 또래 books=[2,3,3,4,100] — 평균 22.4 vs 중앙값 3. 대표값은 중앙값이어야(이상치 내성).
    db_session.add(_profile("self-med", "5-7", 0))
    db_session.add_all(_reads("self-med", 3, completed=True))
    for i, n in enumerate([2, 3, 3, 4]):
        db_session.add(_profile(f"pn{i}", "5-7", 10 + i))
        db_session.add_all(_reads(f"pn{i}", n, completed=True))
    db_session.add(_profile("p-outlier", "5-7", 99))
    db_session.add_all(_reads("p-outlier", 100, completed=True))
    await db_session.commit()

    res = await growth_service.get_peer_comparison(db_session, "self-med")
    assert res["peer_count"] == 5
    assert res["peer_avg"]["books_read"] == 3.0  # 중앙값(평균 22.4 아님)


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
