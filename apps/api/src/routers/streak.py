"""
Streak Router
오늘의 동화 및 스트릭 관련 API
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.services.streak import streak_service, DAILY_THEMES

router = APIRouter()


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


# ==================== Endpoints ====================

@router.get("/info", response_model=StreakInfoResponse)
async def get_streak_info(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    스트릭 정보 조회

    - current_streak: 현재 연속 읽기 일수
    - longest_streak: 최장 연속 일수
    - total_days: 총 읽은 일수
    - read_today: 오늘 읽었는지 여부
    """
    info = await streak_service.get_streak_info(db, user_key)
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
        story["theme"]
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
):
    """
    읽기 기록

    - 책을 읽었을 때 호출
    - 오늘 처음 읽는 경우 스트릭 증가
    - 마일스톤 달성 시 알림
    """
    result = await streak_service.record_reading(
        db=db,
        user_key=user_key,
        book_id=request.book_id,
        reading_time=request.reading_time,
        completed=request.completed,
    )

    return ReadingResultResponse(**result)


@router.get("/history")
async def get_reading_history(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    읽기 기록 조회

    - 최근 N일간의 읽기 기록
    - 날짜별 그룹화
    """
    history = await streak_service.get_reading_history(db, user_key, days)
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
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
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
    history = await streak_service.get_reading_history(db, user_key, days=days_diff + 30)

    # 해당 월의 날짜만 필터링
    month_history = {
        h["date"]: h
        for h in history
        if h["date"].startswith(f"{year}-{month:02d}")
    }

    # 캘린더 데이터 생성
    calendar_data = []
    for day in range(1, last_day.day + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        read_data = month_history.get(date_str)
        calendar_data.append({
            "date": date_str,
            "day": day,
            "read": read_data is not None,
            "books_count": read_data["books_read"] if read_data else 0,
        })

    return {
        "year": year,
        "month": month,
        "days": calendar_data,
        "total_read_days": len(month_history),
    }
