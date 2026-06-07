from datetime import datetime, timedelta, timezone

from src.services.job_monitor import _db_timestamp


def test_db_timestamp_keeps_naive_values_unchanged():
    naive = datetime(2026, 3, 15, 9, 30, 0)

    assert _db_timestamp(naive) == naive


def test_db_timestamp_normalizes_to_naive_utc():
    seoul_time = datetime(2026, 3, 15, 18, 30, 0, tzinfo=timezone(timedelta(hours=9)))

    assert _db_timestamp(seoul_time) == datetime(2026, 3, 15, 9, 30, 0)
