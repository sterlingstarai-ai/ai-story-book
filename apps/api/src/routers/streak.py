"""
Streak Router
오늘의 동화 및 스트릭 관련 API
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Literal, Optional
import structlog

from src.core.database import get_db
from src.core.dependencies import get_profile_id, get_user_key
from src.core.exceptions import ValidationError
from src.core.utils import utcnow
from src.models.db import ChildProfile, Job
from src.models.dto import (
    BookSpec,
    CreateBookResponse,
    JobState,
    Language,
    Style,
    TargetAge,
    Theme,
)
from src.routers.books import (
    _create_job_with_credit,
    _enforce_free_plan_create_limits,
    get_idempotency_key,
    schedule_book_generation,
)
from src.services.growth import growth_service
from src.services.streak import streak_service, DAILY_THEMES

router = APIRouter()
logger = structlog.get_logger()


async def _validate_profile_ownership(
    db: AsyncSession,
    user_key: str,
    profile_id: Optional[str],
) -> Optional[str]:
    if not isinstance(profile_id, str):
        return None
    normalized = profile_id.strip()
    if not normalized:
        return None
    result = await db.execute(
        select(ChildProfile).where(
            ChildProfile.id == normalized,
            ChildProfile.user_key == user_key,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise ValidationError("유효하지 않은 프로필입니다.")
    return normalized


# ==================== Response Models ====================


class StreakInfoResponse(BaseModel):
    current_streak: int
    longest_streak: int
    total_days: int
    last_read_date: Optional[str]
    read_today: bool
    streak_broken: bool


class TodayStoryResponse(BaseModel):
    date: str
    theme: str
    theme_name: Optional[str]
    topic: str
    book_id: Optional[str]


class ReadingLogRequest(BaseModel):
    book_id: str
    reading_time: int = 0  # 초 단위
    completed: bool = False


class ReadingResultResponse(BaseModel):
    current_streak: int
    longest_streak: int
    total_days: int
    new_streak_day: bool
    milestones: list[dict]


class ReadingReportResponse(BaseModel):
    period: Literal["weekly", "monthly"]
    period_days: int
    from_date: str
    to_date: str
    total_books_read: int
    total_sessions: int
    total_reading_minutes: int
    average_reading_minutes: float
    preferred_theme: Optional[str]
    streak: dict
    learning_progress: dict
    daily_breakdown: list[dict]


# ==================== Endpoints ====================


@router.get("/info", response_model=StreakInfoResponse)
async def get_streak_info(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    스트릭 정보 조회

    - current_streak: 현재 연속 읽기 일수
    - longest_streak: 최장 연속 일수
    - total_days: 총 읽은 일수
    - read_today: 오늘 읽었는지 여부
    """
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)
    info = await streak_service.get_streak_info(
        db,
        user_key,
        profile_id=scoped_profile_id,
    )
    return StreakInfoResponse(**info)


@router.get("/today", response_model=TodayStoryResponse)
async def get_today_story(
    db: AsyncSession = Depends(get_db),
):
    """
    오늘의 동화 조회

    - 매일 새로운 테마와 주제 제공
    - 날짜별로 고정된 테마/주제 (모든 사용자 동일)
    """
    story = await streak_service.get_today_story(db)

    # 테마 이름 추가
    theme_name = next(
        (t["name"] for t in DAILY_THEMES if t["theme"] == story["theme"]),
        story["theme"],
    )

    return TodayStoryResponse(
        date=story["date"],
        theme=story["theme"],
        theme_name=theme_name,
        topic=story["topic"],
        book_id=story.get("book_id"),
    )


class TodayGenerateRequest(BaseModel):
    target_age: TargetAge
    style: Style
    language: Language = Language.ko
    protagonist_name: Optional[str] = Field(default=None, max_length=40)
    character_id: Optional[str] = Field(default=None, max_length=60)


@router.post("/today/generate", response_model=CreateBookResponse)
async def generate_today_story(
    request: TodayGenerateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
    idempotency_key: Optional[str] = Depends(get_idempotency_key),
):
    """오늘의 동화를 '내 아이가 주인공'인 개인화 책으로 생성한다.

    오늘의 테마/주제를 시드로 일반 책 생성과 동일 경로(크레딧·무료한도)로 처리한다.
    이전에는 오늘의 동화 book_id 가 항상 null 이라 실제로 읽을 수 없었다 — 이 엔드포인트가 그 공백을 메운다.
    무료 사용자는 *생성* 한도가 있지만 *읽기*(POST /read)는 한도와 무관하게 스트릭을 유지한다.
    """
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)

    # H18: 재시도(타임아웃 후 재탭) 이중 생성·이중 차감 방지 — 기존 잡 반환. 일별 dedup과
    # 무관한 시도-단위 멱등키(다른 키면 새 생성이 정상).
    if idempotency_key:
        existing_job = (
            await db.execute(
                select(Job).where(
                    Job.idempotency_key == idempotency_key,
                    Job.user_key == user_key,
                )
            )
        ).scalar_one_or_none()
        if existing_job:
            return CreateBookResponse(
                job_id=existing_job.id,
                status=JobState(existing_job.status),
                estimated_time_seconds=120,
            )

    today = await streak_service.get_today_story(db)

    # L17: 한국어 표시명 역매핑(Theme(name)) 대신 테마 코드를 Theme enum 멤버명으로 직접 매핑.
    # 7개 일일 테마 코드는 모두 Theme 멤버명과 일치(courage/kindness/growth/imagination 정식 추가).
    # 매핑 불가는 조용한 None 대신 로그 + 명시 기본값(emotion)으로 처리.
    theme_code = today["theme"]
    book_theme = Theme.__members__.get(theme_code)
    if book_theme is None:
        logger.warning("Unmapped daily theme code; using default", theme=theme_code)
        book_theme = Theme.emotion

    spec = BookSpec(
        topic=today["topic"],
        target_age=request.target_age,
        style=request.style,
        language=request.language,
        theme=book_theme,
        protagonist_name=request.protagonist_name,
        character_id=request.character_id,
    )

    await _enforce_free_plan_create_limits(db, user_key, spec.style)

    job_id = f"job_{utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    await _create_job_with_credit(
        db=db,
        user_key=user_key,
        job_id=job_id,
        current_step="queued",  # M32
        credit_description="오늘의 동화 생성",
        refund_description="오늘의 동화 생성 실패 환불",
        idempotency_key=idempotency_key,
        profile_id=scoped_profile_id,
    )
    await schedule_book_generation(db, background_tasks, job_id, spec, user_key)

    return CreateBookResponse(
        job_id=job_id, status=JobState.queued, estimated_time_seconds=120
    )


@router.post("/read", response_model=ReadingResultResponse)
async def record_reading(
    request: ReadingLogRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    읽기 기록

    - 책을 읽었을 때 호출
    - 오늘 처음 읽는 경우 스트릭 증가
    - 마일스톤 달성 시 알림
    """
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)
    # 남의 책으로 읽기/스트릭 지표를 부풀리는 조작 차단(IDOR).
    await growth_service.assert_book_not_foreign(db, request.book_id, user_key)
    result = await streak_service.record_reading(
        db=db,
        user_key=user_key,
        book_id=request.book_id,
        reading_time=request.reading_time,
        completed=request.completed,
        profile_id=scoped_profile_id,
    )

    return ReadingResultResponse(**result)


@router.get("/history")
async def get_reading_history(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    읽기 기록 조회

    - 최근 N일간의 읽기 기록
    - 날짜별 그룹화
    """
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)
    history = await streak_service.get_reading_history(
        db,
        user_key,
        days,
        profile_id=scoped_profile_id,
    )
    return {"history": history}


@router.get("/themes")
async def get_themes():
    """
    테마 목록 조회

    - 사용 가능한 모든 테마와 주제 목록
    """
    return {
        "themes": [
            {
                "id": t["theme"],
                "name": t["name"],
                "topics": t["topics"],
            }
            for t in DAILY_THEMES
        ]
    }


@router.get("/calendar")
async def get_streak_calendar(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    스트릭 캘린더 조회

    - 특정 월의 읽기 기록
    - 캘린더 UI용 데이터
    """
    from datetime import date
    import calendar

    # 해당 월의 시작과 끝
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    # 읽기 기록 조회
    days_diff = (last_day - first_day).days + 1
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)
    history = await streak_service.get_reading_history(
        db,
        user_key,
        days=days_diff + 30,
        profile_id=scoped_profile_id,
    )

    # 해당 월의 날짜만 필터링
    month_history = {
        h["date"]: h for h in history if h["date"].startswith(f"{year}-{month:02d}")
    }

    # 캘린더 데이터 생성
    calendar_data = []
    for day in range(1, last_day.day + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        read_data = month_history.get(date_str)
        calendar_data.append(
            {
                "date": date_str,
                "day": day,
                "read": read_data is not None,
                "books_count": read_data["books_read"] if read_data else 0,
            }
        )

    return {
        "year": year,
        "month": month,
        "days": calendar_data,
        "total_read_days": len(month_history),
    }


@router.get("/report", response_model=ReadingReportResponse)
async def get_reading_report(
    period: Literal["weekly", "monthly"] = Query(
        default="weekly",
        description="리포트 기간 (weekly|monthly)",
    ),
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """읽기 통계 리포트 (부모 대시보드용)"""
    days = 7 if period == "weekly" else 30
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)
    report = await streak_service.get_reading_report(
        db=db,
        user_key=user_key,
        days=days,
        profile_id=scoped_profile_id,
    )
    return {
        "period": period,
        **report,
    }
