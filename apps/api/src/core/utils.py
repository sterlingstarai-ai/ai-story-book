"""공통 유틸리티 함수"""

from datetime import date as _date
from datetime import datetime, timedelta, timezone

# 서비스 표시·날짜경계 기준 타임존. 한국(KST=UTC+9) 사용자에게 스트릭/오늘읽음/주간추이가
# UTC 자정(KST 오전 9시)에 어긋나지 않게 '하루' 판정은 KST 로컬 날짜로 한다.
# (저장은 naive UTC 유지 — Postgres 호환 보존.)
LOCAL_TZ_OFFSET = timedelta(hours=9)


def utcnow() -> datetime:
    """현재 UTC 시각을 *naive*(tz 정보 없는) datetime으로 반환.

    DB 컬럼이 모두 TIMESTAMP WITHOUT TIME ZONE(naive)이라, tz-aware 값을 쓰면
    Postgres(asyncpg)가 'can't subtract offset-naive and offset-aware datetimes'로
    거부한다(SQLite는 관대해 통과 → 잠복). naive UTC로 통일해 양쪽 모두 호환.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local_date(dt: datetime) -> _date:
    """naive UTC datetime → KST(UTC+9) 로컬 날짜. 스트릭/오늘 판정용."""
    return (dt + LOCAL_TZ_OFFSET).date()


def local_today() -> _date:
    """현재 KST 로컬 날짜."""
    return to_local_date(utcnow())


def local_day_bounds_utc(dt=None) -> tuple:
    """주어진 시각(naive UTC, 기본=현재)이 속한 KST 로컬 '하루'의 [시작, 끝) UTC 경계.

    DB의 read_date(naive UTC) 범위 쿼리에 그대로 쓸 수 있다(KST 자정 기준 하루).
    """
    local_d = to_local_date(dt if dt is not None else utcnow())
    start_local = datetime(local_d.year, local_d.month, local_d.day)
    start_utc = start_local - LOCAL_TZ_OFFSET
    return start_utc, start_utc + timedelta(days=1)


def derive_age_band(birth_year: int, birth_month: int, ref=None) -> str:
    """생년월 → 연령대(age_band). 부모 임의선택 대신 실제 나이로 1:1 결정.

    반열린 구간으로 5/7세 경계중복을 제거: [<5)→'3-5'(3미만 floor 포함), [5,7)→'5-7',
    [7,9)→'7-9', ≥9→'7-9'(아동 제품 상한 — DOB로 'adult' 자동배정하지 않음).
    """
    today = ref if ref is not None else local_today()
    months = (today.year - birth_year) * 12 + (today.month - birth_month)
    age = months // 12
    if age < 5:
        return "3-5"
    if age < 7:
        return "5-7"
    return "7-9"
