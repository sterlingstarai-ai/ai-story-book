"""Growth Service: '읽기 성장' 측정 집계.

'AI 동화 생성기'→'측정되는 읽기성장 부모 동반자' 리포지셔닝의 핵심 데이터.
읽은 책·스트릭·학습 어휘·퀴즈 정확도를 집계하고 *추정* 읽기레벨을 산출한다.
(추정치이며 공인 척도가 아님 — 응답 데이터(QuizAnswer)에 근거.)
"""

from typing import Optional

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import ChildProfile, DailyStreak, QuizAnswer, ReadingLog

# 연령대별 기준선 — 또래 표본이 희소할 때(또래 < MIN_PEERS_FOR_REAL) 폴백.
# 한국 유아 읽기 습관의 보수적 추정치이며, 실제 또래 데이터가 쌓이면 그쪽을 쓴다.
AGE_BASELINES = {
    "3-5": {"books_read": 3.0, "vocab_learned": 12.0, "quiz_accuracy": 0.60},
    "5-7": {"books_read": 8.0, "vocab_learned": 45.0, "quiz_accuracy": 0.72},
    "7-9": {"books_read": 15.0, "vocab_learned": 80.0, "quiz_accuracy": 0.78},
    "adult": {"books_read": 25.0, "vocab_learned": 140.0, "quiz_accuracy": 0.85},
}
MIN_PEERS_FOR_REAL = 5


def _medal_for(top_percent: int) -> str:
    if top_percent <= 10:
        return "gold"
    if top_percent <= 30:
        return "silver"
    if top_percent <= 60:
        return "bronze"
    return "none"


def _top_percent_vs_avg(mine: float, avg: float) -> int:
    """또래 표본이 희소할 때, 내 값/기준선 비율로 상위% 근사."""
    if avg <= 0:
        return 50
    ratio = mine / avg
    if ratio >= 1.5:
        return 5
    if ratio >= 1.2:
        return 15
    if ratio >= 1.0:
        return 30
    if ratio >= 0.7:
        return 55
    return 80


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

    async def _resolve_age_band(
        self, db: AsyncSession, user_key: str, profile_id: Optional[str]
    ) -> str:
        """비교 기준 연령대 — 지정 프로필 우선, 없으면 기본 프로필, 그래도 없으면 5-7."""
        q = select(ChildProfile.age_band).where(ChildProfile.user_key == user_key)
        if profile_id:
            q = q.where(ChildProfile.id == profile_id)
        else:
            q = q.order_by(
                ChildProfile.is_default.desc(), ChildProfile.created_at.asc()
            )
        band = (await db.execute(q.limit(1))).scalar_one_or_none()
        return band or "5-7"

    async def get_peer_comparison(
        self,
        db: AsyncSession,
        user_key: str,
        profile_id: Optional[str] = None,
    ) -> dict:
        """같은 연령대(age_band) 또래 대비 비교 — 평균·상위%·메달.

        또래 표본이 적으면(< MIN_PEERS_FOR_REAL) 연령대 기준선으로 폴백(is_baseline=True).
        '사람은 경쟁의 동물' — 부모에게 또래 대비 위치를 보여 동기·전환을 끌어올린다(참고용 추정).
        """
        age_band = await self._resolve_age_band(db, user_key, profile_id)
        # 또래 분포는 user_key 단위로 집계하므로, 비교 기준인 '나'도 user_key 전체로 산출해
        # 동일 스코프를 유지한다(다중 프로필에서 '나 vs 나 포함 또래'가 어긋나는 것 방지).
        my = await self.get_growth_report(db, user_key, profile_id=None)
        my_metrics = {
            "books_read": my["books_read"],
            "vocab_learned": my["vocab_learned"],
            "quiz_accuracy": my["quiz_accuracy"],
        }
        baseline = AGE_BASELINES.get(age_band, AGE_BASELINES["5-7"])

        peer_keys = (
            await db.execute(
                select(distinct(ChildProfile.user_key)).where(
                    ChildProfile.age_band == age_band
                )
            )
        ).scalars().all()
        peer_count = len(peer_keys)

        if peer_count < MIN_PEERS_FOR_REAL:
            peer_avg = {
                "books_read": baseline["books_read"],
                "vocab_learned": baseline["vocab_learned"],
                "quiz_accuracy": baseline["quiz_accuracy"],
            }
            top_percent = _top_percent_vs_avg(
                my_metrics["books_read"], baseline["books_read"]
            )
            return {
                "age_band": age_band,
                "peer_count": peer_count,
                "is_baseline": True,
                "my": my_metrics,
                "peer_avg": peer_avg,
                "top_percent": top_percent,
                "medal": _medal_for(top_percent),
            }

        # 또래 표본 충분 — 실제 분포로 평균·백분위 산출
        book_rows = (
            await db.execute(
                select(
                    ReadingLog.user_key,
                    func.count(distinct(ReadingLog.book_id)),
                )
                .where(ReadingLog.user_key.in_(peer_keys))
                .group_by(ReadingLog.user_key)
            )
        ).all()
        books_by_user = {k: int(c) for k, c in book_rows}
        book_list = [books_by_user.get(k, 0) for k in peer_keys]
        avg_books = sum(book_list) / peer_count

        vocab_rows = (
            await db.execute(
                select(
                    QuizAnswer.user_key,
                    func.count(distinct(QuizAnswer.term)),
                )
                .where(
                    QuizAnswer.user_key.in_(peer_keys),
                    QuizAnswer.quiz_type == "vocab",
                    QuizAnswer.correct.is_(True),
                    QuizAnswer.term.isnot(None),
                )
                .group_by(QuizAnswer.user_key)
            )
        ).all()
        vocab_by_user = {k: int(c) for k, c in vocab_rows}
        avg_vocab = sum(vocab_by_user.get(k, 0) for k in peer_keys) / peer_count

        acc_rows = (
            await db.execute(
                select(
                    QuizAnswer.user_key,
                    func.count(QuizAnswer.id),
                    func.sum(case((QuizAnswer.correct.is_(True), 1), else_=0)),
                )
                .where(QuizAnswer.user_key.in_(peer_keys))
                .group_by(QuizAnswer.user_key)
            )
        ).all()
        # pooled 정확도 = Σ정답 / Σ응답 (개인별 평균의 평균이 아닌 전역 비율 —
        # 개별 quiz_accuracy 정의와 일치, 소표본 사용자 과대가중/Simpson 편향 방지)
        total_answers = sum(int(t or 0) for _k, t, _c in acc_rows)
        total_correct = sum(int(c or 0) for _k, _t, c in acc_rows)
        avg_acc = (
            total_correct / total_answers
            if total_answers > 0
            else baseline["quiz_accuracy"]
        )

        # 상위% = 또래 중 내 읽은 책 수가 상위 몇 %인지(동률 포함)
        at_or_below = sum(1 for b in book_list if b <= my_metrics["books_read"])
        percentile = at_or_below / peer_count * 100  # 클수록 상위
        top_percent = max(1, round(100 - percentile))

        return {
            "age_band": age_band,
            "peer_count": peer_count,
            "is_baseline": False,
            "my": my_metrics,
            "peer_avg": {
                "books_read": round(avg_books, 1),
                "vocab_learned": round(avg_vocab, 1),
                "quiz_accuracy": round(avg_acc, 3),
            },
            "top_percent": top_percent,
            "medal": _medal_for(top_percent),
        }


growth_service = GrowthService()
