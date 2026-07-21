"""H2 — 하루/월 경계를 사용자별 IANA 타임존으로 판정(비KST 사용자 스트릭/한도 정상)."""

from datetime import datetime

import pytest

from src.core.utils import local_day_bounds_utc, to_local_date
from src.models.db import UserSettings
from src.services.streak import streak_service
from tests.factories import make_book_rows


def test_to_local_date_respects_user_tz():
    # 2026-07-06 16:00 UTC: LA는 09:00(07-06), KST는 01:00(07-07) — 날짜가 갈리는 시각.
    dt = datetime(2026, 7, 6, 16, 0, 0)
    assert to_local_date(dt, "America/Los_Angeles").isoformat() == "2026-07-06"
    assert to_local_date(dt, "Asia/Seoul").isoformat() == "2026-07-07"


def test_local_day_bounds_differ_by_tz():
    dt = datetime(2026, 7, 6, 16, 0, 0)
    la_start, la_end = local_day_bounds_utc(dt, tz="America/Los_Angeles")
    kst_start, kst_end = local_day_bounds_utc(dt, tz="Asia/Seoul")
    # LA 하루(07-06)는 07-06 07:00Z 시작(PDT 자정), KST 하루(07-07)는 07-06 15:00Z 시작.
    assert la_start == datetime(2026, 7, 6, 7, 0, 0)
    assert kst_start == datetime(2026, 7, 6, 15, 0, 0)


@pytest.mark.asyncio
async def test_streak_not_broken_across_utc_midnight_for_us_user(db_session, monkeypatch):
    """LA 사용자가 월 07:00·화 09:00(PDT)에 읽으면 스트릭 2 — UTC 자정으론 KST 기준 리셋(수정 전)."""
    from src.core import utils as utils_module
    from src.services import streak as streak_module

    uk = "tz-us-user"
    db_session.add(UserSettings(user_key=uk, language="en", timezone="America/Los_Angeles"))
    db_session.add_all(make_book_rows([("tz-book", uk)]))
    await db_session.commit()

    holder = {"now": datetime(2026, 7, 6, 14, 0, 0)}  # 월 07:00 PDT

    def fake_now():
        return holder["now"]

    # record_reading의 read_date(streak 바인딩)와 local_today(core.utils 바인딩) 둘 다 고정.
    monkeypatch.setattr(streak_module, "utcnow", fake_now)
    monkeypatch.setattr(utils_module, "utcnow", fake_now)

    r1 = await streak_service.record_reading(db_session, uk, "tz-book")
    assert r1["current_streak"] == 1

    holder["now"] = datetime(2026, 7, 7, 16, 0, 0)  # 화 09:00 PDT(익일 UTC)
    r2 = await streak_service.record_reading(db_session, uk, "tz-book")
    assert r2["current_streak"] == 2  # 연속 유지(수정 전 KST 기준 days_since=2로 리셋)
