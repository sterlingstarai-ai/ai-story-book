"""Growth Service: '읽기 성장' 측정 집계.

'AI 동화 생성기'→'측정되는 읽기성장 부모 동반자' 리포지셔닝의 핵심 데이터.
읽은 책·스트릭·학습 어휘·퀴즈 정확도를 집계하고 *추정* 읽기레벨을 산출한다.
(추정치이며 공인 척도가 아님 — 응답 데이터(QuizAnswer)에 근거.)
"""

from typing import Optional

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import DailyStreak, QuizAnswer, ReadingLog


def estimate_reading_level(
    books_read: int, quiz_accuracy: float, vocab_learned: int
) -> dict:
    """간단한 추정 읽기 레벨(1~10). 공인 척도가 아닌 *추정*임을 명시한다."""
    score = 0.0
    score += min(books_read, 60) * 0.08  # 읽은 책 (최대 ~4.8)
    score += min(vocab_learned, 200) * 0.015  # 학습 어휘 (최대 3.0)
    score += quiz_accuracy * 2.0  # 정확도 (최대 2.0)
    level = max(1, min(10, int(round(1 + score))))
    labels = {
        1: "첫 걸음", 2: "첫 걸음", 3: "기초 다지기", 4: "기초 다지기",
        5: "꾸준히 성장", 6: "꾸준히 성장", 7: "읽기 도약", 8: "읽기 도약",
        9: "능숙한 독서가", 10: "능숙한 독서가",
    }
    return {
        "level": level,
        "label": labels.get(level, "성장 중"),
        "scale_max": 10,
        "estimated": True,
    }


class GrowthService:
    """읽기 성장 측정 서비스."""

    async def record_answer(
        self,
        db: AsyncSession,
        user_key: str,
        *,
        book_id: str,
        quiz_type: str,
        correct: bool,
        page_number: Optional[int] = None,
        question_index: Optional[int] = None,
        term: Optional[str] = None,
        user_answer: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> QuizAnswer:
        answer = QuizAnswer(
            user_key=user_key,
            profile_id=profile_id,
            book_id=book_id,
            page_number=page_number,
            quiz_type=quiz_type,
            question_index=question_index,
            term=term,
            user_answer=user_answer,
            correct=bool(correct),
        )
        db.add(answer)
        await db.commit()
        await db.refresh(answer)
        return answer

    async def get_growth_report(
        self,
        db: AsyncSession,
        user_key: str,
        profile_id: Optional[str] = None,
    ) -> dict:
        # 읽은 책 수 (distinct)
        rl_where = [ReadingLog.user_key == user_key]
        if profile_id:
            rl_where.append(ReadingLog.profile_id == profile_id)
        books_read = (
            await db.execute(
                select(func.count(distinct(ReadingLog.book_id))).where(*rl_where)
            )
        ).scalar() or 0

        # 스트릭
        streak = (
            await db.execute(
                select(DailyStreak).where(DailyStreak.user_key == user_key)
            )
        ).scalar_one_or_none()
        current_streak = streak.current_streak if streak else 0
        longest_streak = streak.longest_streak if streak else 0
        total_reading_days = streak.total_days if streak else 0

        # 퀴즈 응답
        qa_where = [QuizAnswer.user_key == user_key]
        if profile_id:
            qa_where.append(QuizAnswer.profile_id == profile_id)
        quiz_total = (
            await db.execute(select(func.count(QuizAnswer.id)).where(*qa_where))
        ).scalar() or 0
        quiz_correct = (
            await db.execute(
                select(func.count(QuizAnswer.id)).where(
                    *qa_where, QuizAnswer.correct.is_(True)
                )
            )
        ).scalar() or 0
        quiz_accuracy = round(quiz_correct / quiz_total, 3) if quiz_total else 0.0

        # 학습 어휘 = 정답 처리된 vocab 문항의 distinct term
        vocab_learned = (
            await db.execute(
                select(func.count(distinct(QuizAnswer.term))).where(
                    *qa_where,
                    QuizAnswer.quiz_type == "vocab",
                    QuizAnswer.correct.is_(True),
                    QuizAnswer.term.isnot(None),
                )
            )
        ).scalar() or 0

        return {
            "books_read": int(books_read),
            "current_streak": int(current_streak),
            "longest_streak": int(longest_streak),
            "total_reading_days": int(total_reading_days),
            "vocab_learned": int(vocab_learned),
            "quiz_total": int(quiz_total),
            "quiz_correct": int(quiz_correct),
            "quiz_accuracy": quiz_accuracy,
            "reading_level": estimate_reading_level(
                int(books_read), quiz_accuracy, int(vocab_learned)
            ),
        }


growth_service = GrowthService()
