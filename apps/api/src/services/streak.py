"""
Streak Service
오늘의 동화 스트릭 시스템
"""

from collections import defaultdict
from datetime import timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..models.db import (
    Book,
    CreditTransaction,
    DailyStreak,
    DailyStory,
    Job,
    ReadingLog,
    UserSettings,
)
from ..core.utils import (
    DEFAULT_TZ,
    local_day_bounds_utc,
    local_today,
    to_local_date,
    utcnow,
)


async def load_user_tz(db: AsyncSession, user_key: str) -> str:
    """사용자의 IANA 타임존(user_settings.timezone). 미설정/미존재는 기본 Asia/Seoul(H2)."""
    tz = (
        await db.execute(
            select(UserSettings.timezone).where(UserSettings.user_key == user_key)
        )
    ).scalar_one_or_none()
    return tz or DEFAULT_TZ


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
            # 신규 사용자 동시 첫 요청은 PK(user_key) 충돌 → IntegrityError를 흡수하고
            # 재조회해 500·이중 행을 막는다(L8).
            streak = DailyStreak(
                user_key=user_key,
                current_streak=0,
                longest_streak=0,
                total_days=0,
            )
            db.add(streak)
            try:
                await db.commit()
                await db.refresh(streak)
            except IntegrityError:
                await db.rollback()
                streak = (
                    await db.execute(
                        select(DailyStreak).where(DailyStreak.user_key == user_key)
                    )
                ).scalar_one()

        return streak

    async def get_streak_info(
        self,
        db: AsyncSession,
        user_key: str,
        profile_id: Optional[str] = None,
    ) -> dict:
        """스트릭 정보 조회"""
        if profile_id:
            return await self._get_profile_streak_info(db, user_key, profile_id)

        tz = await load_user_tz(db, user_key)
        streak = await self.get_or_create_streak(db, user_key)
        today = local_today(tz)

        # 오늘 읽었는지 확인(사용자 tz 로컬 날짜 기준)
        read_today = False
        if streak.last_read_date:
            read_today = to_local_date(streak.last_read_date, tz) == today

        # 스트릭이 끊어졌는지 확인
        streak_broken = False
        if streak.last_read_date and not read_today:
            days_since = (today - to_local_date(streak.last_read_date, tz)).days
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

    async def _get_profile_streak_info(
        self,
        db: AsyncSession,
        user_key: str,
        profile_id: str,
    ) -> dict:
        result = await db.execute(
            select(ReadingLog.read_date)
            .where(
                ReadingLog.user_key == user_key,
                ReadingLog.profile_id == profile_id,
            )
            .order_by(ReadingLog.read_date.asc())
        )
        rows = result.all()
        if not rows:
            return {
                "current_streak": 0,
                "longest_streak": 0,
                "total_days": 0,
                "last_read_date": None,
                "read_today": False,
                "streak_broken": False,
            }

        tz = await load_user_tz(db, user_key)
        datetimes = [read_date for (read_date,) in rows if read_date is not None]
        unique_dates = sorted({to_local_date(dt, tz) for dt in datetimes})
        last_date = unique_dates[-1]
        today = local_today(tz)
        days_since = (today - last_date).days

        read_today = last_date == today
        streak_broken = (not read_today) and days_since > 1

        if days_since > 1:
            current_streak = 0
        else:
            current_streak = 1
            pointer = len(unique_dates) - 1
            cursor = unique_dates[pointer]
            while pointer > 0:
                prev = unique_dates[pointer - 1]
                diff = (cursor - prev).days
                if diff == 1:
                    current_streak += 1
                    cursor = prev
                    pointer -= 1
                    continue
                if diff == 0:
                    pointer -= 1
                    continue
                break

        longest_streak = 1
        running = 1
        for idx in range(1, len(unique_dates)):
            diff = (unique_dates[idx] - unique_dates[idx - 1]).days
            if diff == 1:
                running += 1
                if running > longest_streak:
                    longest_streak = running
            elif diff > 1:
                running = 1

        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "total_days": len(unique_dates),
            "last_read_date": datetimes[-1].isoformat(),
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
        profile_id: Optional[str] = None,
    ) -> dict:
        """읽기 기록 및 스트릭 업데이트 (원자적)"""
        # '오늘' 경계는 사용자 tz 기준(H2) — 비KST 사용자가 UTC 자정에 스트릭이 끊기지 않게.
        tz = await load_user_tz(db, user_key)
        if profile_id:
            today_start, tomorrow_start = local_day_bounds_utc(tz=tz)

            today_result = await db.execute(
                select(ReadingLog.id).where(
                    ReadingLog.user_key == user_key,
                    ReadingLog.profile_id == profile_id,
                    ReadingLog.read_date >= today_start,
                    ReadingLog.read_date < tomorrow_start,
                )
            )
            already_read_today = len(today_result.all()) > 0

            reading_log = ReadingLog(
                user_key=user_key,
                profile_id=profile_id,
                book_id=book_id,
                read_date=utcnow(),
                reading_time=reading_time,
                completed=completed,
            )
            db.add(reading_log)
            await db.commit()

            profile_streak = await self._get_profile_streak_info(db, user_key, profile_id)
            # 마일스톤은 '하루 첫 읽기'에서만 계산(같은 날 중복·보상 중복 방지)
            milestones = (
                self._check_milestones(
                    profile_streak["current_streak"],
                    profile_streak["total_days"],
                )
                if not already_read_today
                else []
            )
            if milestones:
                await self._grant_milestone_rewards(db, user_key, milestones)
            return {
                "current_streak": profile_streak["current_streak"],
                "longest_streak": profile_streak["longest_streak"],
                "total_days": profile_streak["total_days"],
                "new_streak_day": not already_read_today,
                "milestones": milestones,
            }

        streak = await self.get_or_create_streak(db, user_key)
        today = local_today(tz)
        today_dt = utcnow()

        # 오늘 이미 읽었는지 확인(사용자 tz 로컬 날짜)
        already_read_today = False
        if streak.last_read_date:
            already_read_today = to_local_date(streak.last_read_date, tz) == today

        # 읽기 기록 추가
        reading_log = ReadingLog(
            user_key=user_key,
            profile_id=None,
            book_id=book_id,
            read_date=today_dt,
            reading_time=reading_time,
            completed=completed,
        )
        db.add(reading_log)

        # 스트릭 업데이트 (오늘 처음 읽는 경우만, 원자적 조건부 UPDATE)
        if not already_read_today:
            # 새 스트릭 값 계산
            if streak.last_read_date:
                days_since = (today - to_local_date(streak.last_read_date, tz)).days
                if days_since == 1:
                    new_streak = streak.current_streak + 1
                elif days_since > 1:
                    new_streak = 1
                else:
                    new_streak = streak.current_streak
            else:
                new_streak = 1

            new_longest = max(new_streak, streak.longest_streak)
            new_total = streak.total_days + 1

            # 조건부 UPDATE: last_read_date가 변경되지 않은 경우만 업데이트 (동시성 보호)
            if streak.last_read_date:
                condition = DailyStreak.last_read_date == streak.last_read_date
            else:
                condition = DailyStreak.last_read_date.is_(None)

            stmt = (
                update(DailyStreak)
                .where(
                    DailyStreak.user_key == user_key,
                    condition,
                )
                .values(
                    current_streak=new_streak,
                    longest_streak=new_longest,
                    total_days=new_total,
                    last_read_date=today_dt,
                )
            )
            result = await db.execute(stmt)
            affected = result.rowcount if hasattr(result, "rowcount") else 0

            if affected > 0:
                streak.current_streak = new_streak
                streak.longest_streak = new_longest
                streak.total_days = new_total
            else:
                # 다른 요청이 먼저 업데이트함 - 최신 값 재조회
                already_read_today = True
                await db.refresh(streak)

        await db.commit()

        # 달성한 마일스톤 확인
        # 마일스톤은 '하루 첫 읽기'에서만 계산(같은 날 중복·보상 중복 방지)
        milestones = (
            self._check_milestones(streak.current_streak, streak.total_days)
            if not already_read_today
            else []
        )

        if milestones:
            await self._grant_milestone_rewards(db, user_key, milestones)
        return {
            "current_streak": streak.current_streak,
            "longest_streak": streak.longest_streak,
            "total_days": streak.total_days,
            "new_streak_day": not already_read_today,
            "milestones": milestones,
        }

    # 보상 마일스톤별 지급 크레딧(누적 total_days 임계는 1회 발화라 지급도 1회·멱등)
    _REWARD_CREDITS = {"free_pdf": 1, "free_print_credit": 2, "premium_pack": 3}

    async def _grant_milestone_rewards(
        self, db: AsyncSession, user_key: str, milestones: list[dict]
    ) -> int:
        """보상 토큰이 붙은 마일스톤에 크레딧을 지급. 지급한 총 크레딧 수를 반환."""
        from src.services.credits import credits_service

        granted = 0
        for m in milestones:
            amount = self._REWARD_CREDITS.get(m.get("reward") or "", 0)
            if amount > 0:
                was_granted = await credits_service.add_milestone_credits_once(
                    db=db,
                    user_key=user_key,
                    amount=amount,
                    reference_id=f"milestone_{m.get('type')}_{m.get('days')}",
                    description=f"마일스톤 보상: {m.get('title', '')}",
                )
                if was_granted:
                    granted += amount
        return granted

    def _check_milestones(self, current_streak: int, total_days: int) -> list[dict]:
        """달성한 마일스톤 확인"""
        milestones = []

        # 스트릭 마일스톤은 '축하'(보상 없음). current_streak == days는 스트릭이
        # 깨졌다 재축적되면 재발화할 수 있으나 보상이 없어 악용 위험이 없다.
        # (호출부가 '하루 첫 읽기'에서만 계산하므로 같은 날 중복도 차단된다.)
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
                        "reward": None,
                    }
                )

        # 보상은 '누적 읽은 일수'(total_days)에 붙인다. total_days는 단조 증가라
        # 스트릭을 깼다 다시 쌓아도 줄지 않아 임계값마다 정확히 한 번만 발화한다
        # (보상 재지급 악용 불가). reward 토큰은 클라이언트 표시/후속 지급용.
        total_milestones = [
            (10, "📚 10일 완독!", "총 10일 동화를 읽었어요!", "free_pdf"),
            (50, "📖 50일 완독!", "총 50일 동화를 읽었어요!", "free_print_credit"),
            (100, "🎉 100일 완독!", "총 100일 동화를 읽었어요!", "premium_pack"),
        ]

        for days, title, description, reward in total_milestones:
            if total_days == days:
                milestones.append(
                    {
                        "type": "total",
                        "days": days,
                        "title": title,
                        "description": description,
                        "reward": reward,
                    }
                )

        return milestones

    # M22: 라우터가 '오늘의 동화 생성' 잡의 크레딧 차감 시 남기는 불변 마커. Job에 컬럼을
    # 추가하지 않고 이 마커로 사용자의 오늘의 동화 잡을 식별한다(routers/streak.py와 정합).
    TODAY_STORY_CREDIT_DESC = "오늘의 동화 생성"

    async def _user_today_book_id(
        self,
        db: AsyncSession,
        user_key: str,
        today_start,
        tomorrow_start,
    ) -> Optional[str]:
        """user_key가 '오늘'(로컬 하루) 생성 완료한 오늘의 동화 책 id(M22).

        DailyStory는 전역 테이블(user_key 없음)이라 특정 사용자 book_id를 직접 쓰면
        타 사용자에게 오귀속된다. 대신 '오늘의 동화 생성' 크레딧 마커가 붙은 done Job의
        결과 Book을 사용자 단위로 조회(방어적 최근 1건 first(); 완료 전이면 None).
        """
        stmt = (
            select(Book.id)
            .join(Job, Book.job_id == Job.id)
            .join(
                CreditTransaction,
                (CreditTransaction.reference_id == Job.id)
                & (CreditTransaction.user_key == user_key)
                & (CreditTransaction.description == self.TODAY_STORY_CREDIT_DESC)
                & (CreditTransaction.transaction_type == "usage"),
            )
            .where(
                Book.user_key == user_key,
                Job.status == "done",
                Job.created_at >= today_start,
                Job.created_at < tomorrow_start,
            )
            .order_by(Book.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_today_story(
        self, db: AsyncSession, user_key: Optional[str] = None
    ) -> dict:
        """오늘의 동화 정보 조회. 전역 회전이라 기본 tz(H2 결정). 하루 1행을 DB 유니크로 보장(H14).

        M22: 테마/토픽은 전역 DailyStory에서, book_id는 user_key가 주어졌을 때만 '해당
        사용자가 오늘 생성 완료한 오늘의 동화 책'으로 채운다(전역 오귀속 방지).
        """
        # 전역 엔드포인트라 사용자 컨텍스트 없음 — 기본 tz로 하루 경계 판정(G10 결정).
        today = local_today()
        today_start, tomorrow_start = local_day_bounds_utc()

        # M22: book_id는 사용자 단위(user_key 없으면 익명 → None 유지).
        user_book_id = (
            await self._user_today_book_id(db, user_key, today_start, tomorrow_start)
            if user_key
            else None
        )

        async def _find_today():
            # 방어적 first(): 마이그레이션 이전 잔존 중복이 있어도 500 대신 첫 행 반환.
            res = await db.execute(
                select(DailyStory)
                .where(
                    DailyStory.date >= today_start,
                    DailyStory.date < tomorrow_start,
                )
                .order_by(DailyStory.id)
                .limit(1)
            )
            return res.scalars().first()

        daily_story = await _find_today()
        if daily_story:
            return {
                "date": daily_story.date.isoformat(),
                "theme": daily_story.theme,
                "topic": daily_story.topic,
                "book_id": user_book_id,  # M22
            }

        # 없으면 오늘의 테마/주제 생성
        day_of_year = today.timetuple().tm_yday
        theme_index = day_of_year % len(DAILY_THEMES)
        theme_data = DAILY_THEMES[theme_index]

        topic_index = day_of_year % len(theme_data["topics"])
        topic = theme_data["topics"][topic_index]

        # 새 오늘의 동화 생성. 동시 요청/멀티 레플리카가 같은 date로 이중 INSERT하면
        # uq_daily_stories_date가 차단 → IntegrityError를 rollback 후 재조회해 다른 세션이
        # 먼저 넣은 행을 반환(성공으로 삼키지 않고 멱등 반환, H14).
        daily_story = DailyStory(
            date=today_start,
            theme=theme_data["theme"],
            topic=topic,
        )
        db.add(daily_story)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await _find_today()
            if existing is not None:
                return {
                    "date": existing.date.isoformat(),
                    "theme": existing.theme,
                    "topic": existing.topic,
                    "book_id": user_book_id,  # M22
                }
            raise

        return {
            "date": today_start.isoformat(),
            "theme": theme_data["theme"],
            "theme_name": theme_data["name"],
            "topic": topic,
            "book_id": user_book_id,  # M22
        }

    async def get_reading_history(
        self,
        db: AsyncSession,
        user_key: str,
        days: int = 30,
        profile_id: Optional[str] = None,
    ) -> list[dict]:
        """최근 읽기 기록 조회"""
        since = utcnow() - timedelta(days=days)

        result = await db.execute(
            select(ReadingLog)
            .where(
                ReadingLog.user_key == user_key,
                ReadingLog.read_date >= since,
                ReadingLog.profile_id == profile_id if profile_id else ReadingLog.profile_id.is_(None),
            )
            .order_by(ReadingLog.read_date.desc())
        )
        logs = result.scalars().all()

        # 날짜별로 그룹화
        by_date = {}
        for log in logs:
            date_key = to_local_date(log.read_date).isoformat()
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

    async def get_reading_report(
        self,
        db: AsyncSession,
        user_key: str,
        days: int = 7,
        profile_id: Optional[str] = None,
    ) -> dict:
        """읽기 통계 리포트 (주간/월간 대시보드용)"""
        report_days = max(1, min(days, 365))
        # 주간/월간 추이도 KST 로컬 하루 경계로(한국 부모 기준 '오늘'이 맞도록).
        today_start, _ = local_day_bounds_utc()
        since = today_start - timedelta(days=report_days - 1)

        logs_result = await db.execute(
            select(ReadingLog)
            .where(
                ReadingLog.user_key == user_key,
                ReadingLog.read_date >= since,
                ReadingLog.profile_id == profile_id if profile_id else ReadingLog.profile_id.is_(None),
            )
            .order_by(ReadingLog.read_date.asc())
        )
        logs = logs_result.scalars().all()

        daily_map = {}
        for day_index in range(report_days):
            day = to_local_date(since + timedelta(days=day_index))
            key = day.isoformat()
            daily_map[key] = {
                "date": key,
                "sessions": 0,
                "minutes": 0,
                "completed": 0,
            }

        total_read_seconds = 0
        completed_sessions = 0
        unique_books = set()
        for log in logs:
            key = to_local_date(log.read_date).isoformat()
            if key not in daily_map:
                continue
            minutes = max(0, int(round((log.reading_time or 0) / 60)))
            daily_map[key]["sessions"] += 1
            daily_map[key]["minutes"] += minutes
            if log.completed:
                daily_map[key]["completed"] += 1
                completed_sessions += 1
            total_read_seconds += max(0, log.reading_time or 0)
            unique_books.add(log.book_id)

        theme_counts = defaultdict(int)
        if unique_books:
            books_result = await db.execute(
                select(Book.id, Book.theme).where(Book.id.in_(unique_books))
            )
            theme_by_book = {book_id: theme for book_id, theme in books_result.all()}
            for log in logs:
                theme = theme_by_book.get(log.book_id)
                if theme:
                    theme_counts[theme] += 1

        preferred_theme = None
        if theme_counts:
            preferred_theme = max(theme_counts.items(), key=lambda item: item[1])[0]

        total_sessions = len(logs)
        avg_reading_minutes = (
            round((total_read_seconds / 60) / total_sessions, 1)
            if total_sessions > 0
            else 0.0
        )
        completion_rate = (
            round((completed_sessions / total_sessions) * 100, 1)
            if total_sessions > 0
            else 0.0
        )

        streak_info = await self.get_streak_info(
            db,
            user_key,
            profile_id=profile_id,
        )

        return {
            "period_days": report_days,
            "from_date": to_local_date(since).isoformat(),
            "to_date": local_today().isoformat(),
            "total_books_read": len(unique_books),
            "total_sessions": total_sessions,
            "total_reading_minutes": int(round(total_read_seconds / 60)),
            "average_reading_minutes": avg_reading_minutes,
            "preferred_theme": preferred_theme,
            "streak": {
                "current": streak_info["current_streak"],
                "longest": streak_info["longest_streak"],
                "total_days": streak_info["total_days"],
                "read_today": streak_info["read_today"],
            },
            "learning_progress": {
                "sessions": total_sessions,
                "completed_sessions": completed_sessions,
                "completion_rate": completion_rate,
            },
            "daily_breakdown": list(daily_map.values()),
        }


# 싱글톤 인스턴스
streak_service = StreakService()
