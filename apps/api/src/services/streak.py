"""
Streak Service
오늘의 동화 스트릭 시스템
"""

from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..models.db import DailyStreak, DailyStory, ReadingLog


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)

# 오늘의 동화 테마 목록
DAILY_THEMES = [
    {
        "theme": "friendship",
        "name": "우정",
        "topics": [
            "새 친구 사귀기",
            "친구와 화해하기",
            "함께 나누는 기쁨",
            "서로 도와주기",
        ],
    },
    {
        "theme": "courage",
        "name": "용기",
        "topics": [
            "두려움 극복하기",
            "새로운 도전",
            "실수해도 괜찮아",
            "처음 해보는 일",
        ],
    },
    {
        "theme": "kindness",
        "name": "친절",
        "topics": [
            "작은 친절의 힘",
            "도움이 필요한 친구",
            "감사한 마음",
            "배려하는 마음",
        ],
    },
    {
        "theme": "family",
        "name": "가족",
        "topics": [
            "엄마 아빠 사랑해요",
            "동생과 함께",
            "할머니 할아버지 댁",
            "가족 여행",
        ],
    },
    {
        "theme": "nature",
        "name": "자연",
        "topics": [
            "숲속 탐험",
            "바다 이야기",
            "봄이 왔어요",
            "별빛 가득한 밤",
        ],
    },
    {
        "theme": "growth",
        "name": "성장",
        "topics": [
            "혼자서도 할 수 있어요",
            "새로운 것 배우기",
            "실패해도 다시 도전",
            "꿈을 향해",
        ],
    },
    {
        "theme": "imagination",
        "name": "상상",
        "topics": [
            "마법의 세계",
            "구름 위 나라",
            "동물 친구들의 학교",
            "장난감의 비밀",
        ],
    },
]


class StreakService:
    """스트릭 관리 서비스"""

    async def get_or_create_streak(
        self,
        db: AsyncSession,
        user_key: str,
    ) -> DailyStreak:
        """사용자 스트릭 정보 조회 또는 생성"""
        result = await db.execute(
            select(DailyStreak).where(DailyStreak.user_key == user_key)
        )
        streak = result.scalar_one_or_none()

        if not streak:
            streak = DailyStreak(
                user_key=user_key,
                current_streak=0,
                longest_streak=0,
                total_days=0,
            )
            db.add(streak)
            await db.commit()
            await db.refresh(streak)

        return streak

    async def get_streak_info(
        self,
        db: AsyncSession,
        user_key: str,
    ) -> dict:
        """스트릭 정보 조회"""
        streak = await self.get_or_create_streak(db, user_key)
        today = utcnow().date()

        # 오늘 읽었는지 확인
        read_today = False
        if streak.last_read_date:
            read_today = streak.last_read_date.date() == today

        # 스트릭이 끊어졌는지 확인
        streak_broken = False
        if streak.last_read_date and not read_today:
            days_since = (today - streak.last_read_date.date()).days
            if days_since > 1:
                streak_broken = True

        return {
            "current_streak": 0 if streak_broken else streak.current_streak,
            "longest_streak": streak.longest_streak,
            "total_days": streak.total_days,
            "last_read_date": streak.last_read_date.isoformat()
            if streak.last_read_date
            else None,
            "read_today": read_today,
            "streak_broken": streak_broken,
        }

    async def record_reading(
        self,
        db: AsyncSession,
        user_key: str,
        book_id: str,
        reading_time: int = 0,
        completed: bool = False,
    ) -> dict:
        """읽기 기록 및 스트릭 업데이트"""
        streak = await self.get_or_create_streak(db, user_key)
        today = utcnow().date()
        today_dt = utcnow()

        # 오늘 이미 읽었는지 확인
        already_read_today = False
        if streak.last_read_date:
            already_read_today = streak.last_read_date.date() == today

        # 읽기 기록 추가
        reading_log = ReadingLog(
            user_key=user_key,
            book_id=book_id,
            read_date=today_dt,
            reading_time=reading_time,
            completed=completed,
        )
        db.add(reading_log)

        # 스트릭 업데이트 (오늘 처음 읽는 경우)
        if not already_read_today:
            # 연속 스트릭 확인
            if streak.last_read_date:
                days_since = (today - streak.last_read_date.date()).days
                if days_since == 1:
                    # 연속 성공
                    streak.current_streak += 1
                elif days_since > 1:
                    # 스트릭 끊김 - 1부터 다시
                    streak.current_streak = 1
            else:
                # 첫 읽기
                streak.current_streak = 1

            # 최장 스트릭 갱신
            if streak.current_streak > streak.longest_streak:
                streak.longest_streak = streak.current_streak

            # 총 일수 증가
            streak.total_days += 1

            # 마지막 읽은 날짜 업데이트
            streak.last_read_date = today_dt

        await db.commit()

        # 달성한 마일스톤 확인
        milestones = self._check_milestones(streak.current_streak, streak.total_days)

        return {
            "current_streak": streak.current_streak,
            "longest_streak": streak.longest_streak,
            "total_days": streak.total_days,
            "new_streak_day": not already_read_today,
            "milestones": milestones,
        }

    def _check_milestones(self, current_streak: int, total_days: int) -> list[dict]:
        """달성한 마일스톤 확인"""
        milestones = []

        streak_milestones = [
            (3, "🔥 3일 연속!", "3일 연속으로 동화를 읽었어요!"),
            (7, "🌟 일주일 달성!", "7일 연속으로 동화를 읽었어요!"),
            (14, "⭐ 2주 달성!", "14일 연속으로 동화를 읽었어요!"),
            (30, "🏆 한 달 마스터!", "30일 연속으로 동화를 읽었어요!"),
            (100, "👑 100일 달성!", "100일 연속으로 동화를 읽었어요!"),
        ]

        for days, title, description in streak_milestones:
            if current_streak == days:
                milestones.append(
                    {
                        "type": "streak",
                        "days": days,
                        "title": title,
                        "description": description,
                    }
                )

        total_milestones = [
            (10, "📚 10권 완독!", "총 10일 동화를 읽었어요!"),
            (50, "📖 50권 완독!", "총 50일 동화를 읽었어요!"),
            (100, "🎉 100권 완독!", "총 100일 동화를 읽었어요!"),
        ]

        for days, title, description in total_milestones:
            if total_days == days:
                milestones.append(
                    {
                        "type": "total",
                        "days": days,
                        "title": title,
                        "description": description,
                    }
                )

        return milestones

    async def get_today_story(self, db: AsyncSession) -> dict:
        """오늘의 동화 정보 조회"""
        today = utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())

        # 오늘 이미 생성된 스토리가 있는지 확인
        result = await db.execute(
            select(DailyStory).where(func.date(DailyStory.date) == today)
        )
        daily_story = result.scalar_one_or_none()

        if daily_story:
            return {
                "date": daily_story.date.isoformat(),
                "theme": daily_story.theme,
                "topic": daily_story.topic,
                "book_id": daily_story.book_id,
            }

        # 없으면 오늘의 테마/주제 생성
        day_of_year = today.timetuple().tm_yday
        theme_index = day_of_year % len(DAILY_THEMES)
        theme_data = DAILY_THEMES[theme_index]

        topic_index = day_of_year % len(theme_data["topics"])
        topic = theme_data["topics"][topic_index]

        # 새 오늘의 동화 생성
        daily_story = DailyStory(
            date=today_start,
            theme=theme_data["theme"],
            topic=topic,
        )
        db.add(daily_story)
        await db.commit()

        return {
            "date": today_start.isoformat(),
            "theme": theme_data["theme"],
            "theme_name": theme_data["name"],
            "topic": topic,
            "book_id": None,
        }

    async def get_reading_history(
        self,
        db: AsyncSession,
        user_key: str,
        days: int = 30,
    ) -> list[dict]:
        """최근 읽기 기록 조회"""
        since = utcnow() - timedelta(days=days)

        result = await db.execute(
            select(ReadingLog)
            .where(
                ReadingLog.user_key == user_key,
                ReadingLog.read_date >= since,
            )
            .order_by(ReadingLog.read_date.desc())
        )
        logs = result.scalars().all()

        # 날짜별로 그룹화
        by_date = {}
        for log in logs:
            date_key = log.read_date.date().isoformat()
            if date_key not in by_date:
                by_date[date_key] = {
                    "date": date_key,
                    "books_read": 0,
                    "total_time": 0,
                    "completed_count": 0,
                }
            by_date[date_key]["books_read"] += 1
            by_date[date_key]["total_time"] += log.reading_time
            if log.completed:
                by_date[date_key]["completed_count"] += 1

        return list(by_date.values())


# 싱글톤 인스턴스
streak_service = StreakService()
