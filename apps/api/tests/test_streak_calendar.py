"""L7: 스트릭 캘린더가 요청 월의 절대 경계로 조회(과거 달도 정확)."""

from datetime import timedelta

import pytest

from src.core.utils import local_month_range_utc, utcnow
from src.models.db import ReadingLog
from tests.factories import make_book_rows

H = {"X-User-Key": "77777777-7777-4777-8777-777777777777"}


async def _seed_read(db_session, book_id, read_dt):
    db_session.add_all(make_book_rows([(book_id, H["X-User-Key"])]))
    db_session.add(
        ReadingLog(user_key=H["X-User-Key"], book_id=book_id, read_date=read_dt)
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_calendar_returns_old_month_reads(client, db_session):
    """3개월 전 날짜의 읽기가 그 달 캘린더에 read:true로 나온다(상대 윈도우 밖 회귀)."""
    # 약 90일 전(확실히 상대 60~90일 윈도우 밖) 시각.
    old = utcnow() - timedelta(days=90)
    await _seed_read(db_session, "old-book", old)

    res = await client.get(
        f"/v1/streak/calendar?year={old.year}&month={old.month}", headers=H
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_read_days"] >= 1
    assert any(d["read"] and d["books_count"] >= 1 for d in data["days"])


@pytest.mark.asyncio
async def test_calendar_empty_month_all_false(client, db_session):
    """읽기 없는 달은 전부 read:false·0(오탐 없음)."""
    res = await client.get("/v1/streak/calendar?year=2021&month=3", headers=H)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total_read_days"] == 0
    assert all(not d["read"] for d in data["days"])


def test_local_month_range_utc_boundaries():
    """임의 달 절대 경계: 12월은 익년 1월로 넘어가고, [시작,끝) 반열림."""
    start, end = local_month_range_utc(2024, 12, "Asia/Seoul")
    assert start < end
    # 2024-12 KST 시작은 UTC로 2024-11-30 15:00
    assert start.year == 2024 and start.month == 11
    # 익월 시작(2025-01 KST) → UTC 2024-12-31 15:00
    assert end.year == 2024 and end.month == 12
