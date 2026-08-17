"""공통 유틸리티 함수"""

from datetime import date as _date
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# 하루/월 경계 판정의 기본 타임존. 글로벌 제품이므로 사용자별 IANA timezone(user_settings)을
# 헬퍼에 넘겨 경계를 계산한다(H2/G10). 미전달 호출부는 기본 Asia/Seoul로 기존 동작 보존(점진 이관).
# DST는 zoneinfo로 안전 처리(고정 offset 덧셈 금지). 저장은 naive UTC 유지(Postgres 호환).
DEFAULT_TZ = "Asia/Seoul"


def utcnow() -> datetime:
    """현재 UTC 시각을 *naive*(tz 정보 없는) datetime으로 반환.

    DB 컬럼이 모두 TIMESTAMP WITHOUT TIME ZONE(naive)이라, tz-aware 값을 쓰면
    Postgres(asyncpg)가 'can't subtract offset-naive and offset-aware datetimes'로
    거부한다(SQLite는 관대해 통과 → 잠복). naive UTC로 통일해 양쪽 모두 호환.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_aware_local(dt: datetime, tz: str) -> datetime:
    """naive UTC datetime → 대상 tz의 aware datetime(DST 반영)."""
    return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz))


def _naive_utc(aware: datetime) -> datetime:
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def to_local_date(dt: datetime, tz: str = DEFAULT_TZ) -> _date:
    """naive UTC datetime → 사용자 tz의 로컬 날짜. 스트릭/오늘 판정용(DST 안전)."""
    return _to_aware_local(dt, tz).date()


def local_today(tz: str = DEFAULT_TZ) -> _date:
    """현재 사용자 tz의 로컬 날짜."""
    return to_local_date(utcnow(), tz)


def local_day_bounds_utc(dt=None, tz: str = DEFAULT_TZ) -> tuple:
    """주어진 시각(naive UTC, 기본=현재)이 속한 tz 로컬 '하루'의 [시작, 끝) UTC 경계.

    DB의 read_date(naive UTC) 범위 쿼리에 그대로 쓸 수 있다(로컬 자정 기준 하루, DST 안전).
    """
    zone = ZoneInfo(tz)
    local_d = to_local_date(dt if dt is not None else utcnow(), tz)
    next_d = local_d + timedelta(days=1)
    start_local = datetime(local_d.year, local_d.month, local_d.day, tzinfo=zone)
    # 다음 '로컬 자정'을 절대 24h 덧셈이 아니라 다음 날짜 자정으로 계산(DST 정확).
    end_local = datetime(next_d.year, next_d.month, next_d.day, tzinfo=zone)
    return _naive_utc(start_local), _naive_utc(end_local)


def local_month_bounds_utc(dt=None, tz: str = DEFAULT_TZ) -> tuple:
    """현재(또는 dt) 시각이 속한 tz 로컬 '달'의 [시작, 끝) UTC 경계(DST 안전)."""
    zone = ZoneInfo(tz)
    base = to_local_date(dt if dt is not None else utcnow(), tz)
    start_local = datetime(base.year, base.month, 1, tzinfo=zone)
    if base.month == 12:
        end_local = datetime(base.year + 1, 1, 1, tzinfo=zone)
    else:
        end_local = datetime(base.year, base.month + 1, 1, tzinfo=zone)
    return _naive_utc(start_local), _naive_utc(end_local)


def local_month_range_utc(year: int, month: int, tz: str = DEFAULT_TZ) -> tuple:
    """임의의 (year, month) tz 로컬 '달'의 [시작, 끝) UTC 경계(DST 안전, L7).

    캘린더가 '지금 기준 상대 윈도우'가 아니라 요청 월의 절대 경계로 조회하도록,
    과거·미래 임의 달의 로컬 자정 경계를 UTC로 환산한다(read_date 범위 쿼리에 사용).
    """
    zone = ZoneInfo(tz)
    start_local = datetime(year, month, 1, tzinfo=zone)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=zone)
    else:
        end_local = datetime(year, month + 1, 1, tzinfo=zone)
    return _naive_utc(start_local), _naive_utc(end_local)


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


def redact_path(path: str) -> str:
    """로그·관측에 남길 경로에서 capability URL(공유 토큰)을 가린다.

    `/share/{token}` 은 인증 없이 아동 콘텐츠를 여는 **자격증명 그 자체**다. 로그에 원문이
    남으면 로그 접근자가 무인증으로 재생할 수 있다.

    R4: 예전에는 이 함수가 `main.py` 안에 있었고 AccessLogMiddleware만 사용했다. 그 결과
    예외 핸들러 5곳(APIError/HTTPException/Validation/unhandled 2종)이 우회해 **에러가 난
    요청의 토큰은 그대로 유출**됐다 — 마스킹 규칙이 두 벌이면 한 쪽이 샌다. 정본을 여기
    한 곳에 두고 모든 로깅 경로가 이걸 쓴다.
    """
    if isinstance(path, str) and path.startswith("/share/"):
        return "/share/{token}"
    return path
