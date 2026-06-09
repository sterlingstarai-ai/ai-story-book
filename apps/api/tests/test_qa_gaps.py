"""QA 하드닝 — 리포지셔닝 신규코드의 미검증 critical 경로 회귀 테스트.

라이브 E2E(scripts/e2e_journey.py)가 통합을 검증하고, 본 파일은 단위/엣지를 메운다:
KST 날짜경계, 연령밴드 파생, 또래비교 엣지, 오디오 게이트 티어, IDOR, 동의 독립성.
"""

from datetime import date, datetime, timedelta

import pytest

from src.core.config import settings
from src.core.utils import (
    derive_age_band,
    local_day_bounds_utc,
    local_month_bounds_utc,
    to_local_date,
)
from src.models.db import Book, ChildProfile, Job
from src.services.growth import growth_service

H = {"X-User-Key": "33333333-3333-4333-8333-333333333333"}
H2 = {"X-User-Key": "44444444-4444-4444-8444-444444444444"}


# ── KST 날짜 경계(저장은 naive UTC, 판정은 KST=UTC+9) ──
def test_to_local_date_kst_boundary():
    # KST 자정 경계 = UTC 15:00. 14:59:59Z는 같은 KST일, 15:00:00Z는 다음 KST일.
    assert to_local_date(datetime(2026, 6, 9, 14, 59, 59)) == date(2026, 6, 9)
    assert to_local_date(datetime(2026, 6, 9, 15, 0, 0)) == date(2026, 6, 10)
    assert to_local_date(datetime(2026, 6, 9, 0, 0, 0)) == date(2026, 6, 9)  # KST 09:00


def test_local_day_bounds_utc_window():
    # UTC 16:00(=KST 다음날 01:00)의 KST 하루 = [전날 15:00Z, 당일 15:00Z)
    start, end = local_day_bounds_utc(datetime(2026, 6, 9, 16, 0, 0))
    assert start == datetime(2026, 6, 9, 15, 0, 0)
    assert end == datetime(2026, 6, 10, 15, 0, 0)
    # 경계 직전/직후 읽기가 서로 다른 KST일에 속함
    assert to_local_date(datetime(2026, 6, 9, 14, 0, 0)) != to_local_date(
        datetime(2026, 6, 9, 16, 0, 0)
    )


def test_local_month_bounds_utc():
    # 6월 어느 시점 → KST 6월 = [5/31 15:00Z, 6/30 15:00Z)
    start, end = local_month_bounds_utc(datetime(2026, 6, 15, 3, 0, 0))
    assert start == datetime(2026, 5, 31, 15, 0, 0)
    assert end == datetime(2026, 6, 30, 15, 0, 0)


# ── 연령밴드 파생 엣지 ──
def test_derive_age_band_edges():
    ref = date(2026, 6, 9)
    assert derive_age_band(2020, 12, ref) == "5-7"  # 만 5세 6개월
    assert derive_age_band(2021, 6, ref) == "5-7"   # 정확히 만 5세(경계 포함)
    assert derive_age_band(2019, 6, ref) == "7-9"   # 정확히 만 7세(경계)
    assert derive_age_band(2010, 1, ref) == "7-9"   # 만 16세도 아동 상한 7-9(adult 자동 아님)
    assert isinstance(derive_age_band(2020, 6), str)  # ref=None → local_today 사용, 크래시 없음


# ── 일일 책 생성 한도: KST 경계(스트릭과 일관) ──
@pytest.mark.asyncio
async def test_daily_limit_uses_kst_boundary(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)
    monkeypatch.setattr(settings, "daily_job_limit_per_user", 2)

    uk = H["X-User-Key"]
    today_start, _ = local_day_bounds_utc()
    # KST '오늘' 안의 잡 2개(한도 도달)
    for i in range(2):
        db_session.add(Job(id=f"job_today_{i}", status="done", user_key=uk,
                           created_at=today_start))
    # KST '어제'(today_start 1초 전) 잡 1개 — 오늘 한도에 포함되면 안 됨
    db_session.add(Job(id="job_yest", status="done", user_key=uk,
                       created_at=today_start - timedelta(seconds=1)))
    await db_session.commit()

    # 오늘 2개(한도 2) → 3번째 생성은 429(어제 잡은 미포함이어야 정확히 2로 카운트)
    res = await client.post(
        "/v1/books",
        json={"topic": "한도 테스트", "language": "ko", "target_age": "5-7",
              "style": "watercolor"},
        headers=H,
    )
    assert res.status_code == 429, res.text
    assert res.json()["error"]["code"] in ("DAILY_LIMIT_EXCEEDED", "daily_limit_exceeded") \
        or "daily" in str(res.json()).lower()


# ── 또래비교: 프로필 없으면 등수 미노출(fail-safe) ──
@pytest.mark.asyncio
async def test_peer_comparison_no_profile_hides_ranking(db_session):
    # 프로필 미생성 유저 → age_band 기본 '5-7'로 폴백되지만 등수는 노출 안 함.
    res = await growth_service.get_peer_comparison(db_session, "no-profile-user")
    assert res["show_ranking"] is False


@pytest.mark.asyncio
async def test_peer_comparison_many_ties_midrank(db_session):
    # 본인+또래 5명 전부 동일 → 4명 동점. midrank로 중앙값(상위 50% 부근), 금메달 아님.
    def prof(uk):
        return ChildProfile(id=f"t-{uk}", user_key=uk, name=f"a{uk}",
                            age_band="5-7", is_default=True)
    from src.models.db import ReadingLog
    from src.core.utils import utcnow
    for uk in ["tie_self", "t0", "t1", "t2", "t3", "t4"]:
        db_session.add(prof(uk))
        db_session.add_all([
            ReadingLog(user_key=uk, book_id=f"{uk}-b{j}", read_date=utcnow(), completed=True)
            for j in range(3)
        ])
    await db_session.commit()
    res = await growth_service.get_peer_comparison(db_session, "tie_self")
    assert res["peer_count"] == 5
    assert 30 <= res["top_percent"] <= 70
    assert res["medal"] != "gold"


# ── 무료 오디오 게이트: 7-9·adult 신규 합성 차단, 3-5 허용 ──
@pytest.mark.asyncio
@pytest.mark.parametrize("band,expect_blocked", [
    ("3-5", False), ("5-7", True), ("7-9", True), ("adult", True),
])
async def test_free_audio_gate_by_band(client, db_session, monkeypatch, band, expect_blocked):
    monkeypatch.setattr(settings, "free_plan_enforcement_enabled", True)
    monkeypatch.setattr(settings, "free_plan_enforce_in_testing", True)

    async def _tts(*a, **k):
        return b"audio"

    async def _upload(*a, **k):
        return "https://cdn.example.com/a.mp3"

    monkeypatch.setattr("src.routers.books.tts_service.synthesize_page", _tts)
    monkeypatch.setattr("src.routers.books.storage_service.upload_bytes", _upload)

    uk = H["X-User-Key"]
    bid = f"book-band-{band}"
    db_session.add(Job(id=f"job-{band}", status="done", user_key=uk))
    await db_session.flush()
    db_session.add(Book(id=bid, job_id=f"job-{band}", title="t", language="ko",
                        target_age=band, style="watercolor", user_key=uk,
                        cover_image_url="https://e/c.png"))
    await db_session.flush()
    from src.models.db import Page
    db_session.add(Page(book_id=bid, page_number=1, text="첫 페이지",
                        image_url="https://e/p.png", image_prompt="p"))
    await db_session.commit()

    res = await client.get(f"/v1/books/{bid}/pages/1/audio",
                           headers=H, params={"language": "ko"})
    if expect_blocked:
        assert res.status_code == 402, f"{band}: {res.status_code} {res.text[:120]}"
    else:
        assert res.status_code == 200, f"{band}: {res.status_code} {res.text[:120]}"


# ── IDOR: 타 유저 프로필 수정/삭제 차단 ──
@pytest.mark.asyncio
async def test_profile_idor_update_delete_blocked(client, db_session):
    db_session.add(ChildProfile(id="prof-owned", user_key=H["X-User-Key"],
                                name="내아이", age_band="5-7", is_default=True))
    await db_session.commit()

    # 다른 유저가 수정 시도 → 404(소유 아님)
    r = await client.patch("/v1/profiles/prof-owned", json={"name": "해킹"}, headers=H2)
    assert r.status_code in (403, 404), r.text
    # 다른 유저가 삭제 시도 → 404
    r = await client.delete("/v1/profiles/prof-owned", headers=H2)
    assert r.status_code in (403, 404), r.text
    # 원소유자는 정상 조회됨(변조 안 됨)
    r = await client.get("/v1/profiles", headers=H)
    names = [p["name"] for p in r.json()["profiles"]]
    assert "내아이" in names and "해킹" not in names


# ── 동의: photos는 granted(필수동의)와 독립 ──
@pytest.mark.asyncio
async def test_consent_photos_independent_of_granted(client):
    # 사진만 동의(필수 미동의) → granted=False지만 photos 게이트는 열려야(독립 평가).
    r = await client.post("/v1/consent", headers=H,
                          json={"privacy": False, "photos": True, "data_processing": False})
    assert r.status_code == 200, r.text
    r = await client.get("/v1/consent", headers=H)
    assert r.json()["photos"] is True  # photos는 granted와 무관하게 활성
