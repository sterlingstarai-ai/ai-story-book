"""공통 유틸리티 함수"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """현재 UTC 시각을 *naive*(tz 정보 없는) datetime으로 반환.

    DB 컬럼이 모두 TIMESTAMP WITHOUT TIME ZONE(naive)이라, tz-aware 값을 쓰면
    Postgres(asyncpg)가 'can't subtract offset-naive and offset-aware datetimes'로
    거부한다(SQLite는 관대해 통과 → 잠복). naive UTC로 통일해 양쪽 모두 호환.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
