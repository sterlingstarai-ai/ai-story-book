"""
Streak Router
오늘의 동화 및 스트릭 관련 API
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Literal, Optional

from src.core.database import get_db
from src.core.dependencies import get_profile_id, get_user_key
from src.core.exceptions import ValidationError
from src.models.db import ChildProfile
from src.services.streak import streak_service, DAILY_THEMES

router = APIRouter()


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
