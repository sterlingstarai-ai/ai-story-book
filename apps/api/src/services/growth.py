"""Growth Service: '읽기 성장' 측정 집계.

'AI 동화 생성기'→'측정되는 읽기성장 부모 동반자' 리포지셔닝의 핵심 데이터.
읽은 책·완독·학습 어휘·퀴즈 정확도를 *복합 점수*로 종합해 추정 읽기레벨을 산출한다.
(추정치이며 공인 척도가 아님 — 응답 데이터(QuizAnswer)·읽기로그(ReadingLog)에 근거.)

설계 근거(시장 조사): Lexile/F&P/DRA·Raz/Reading Eggs 모두 단일 지표가 아닌 *가중 복합*을
연령층별로 정규화해 레벨/백분위를 낸다. 또래 비교도 단일축(읽은 책 수) 대신 복합 점수 기준.
"""

from typing import Optional

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import ChildProfile, DailyStreak, QuizAnswer, ReadingLog

# 연령대별 기준선 — 정규화 타깃 + 또래 표본 희소 시(또래 < MIN_PEERS_FOR_REAL) 폴백.
# 한국 유아 읽기 습관의 보수적 추정치이며, 실제 또래 데이터가 쌓이면 그쪽을 쓴다.
AGE_BASELINES = {
    "3-5": {"books_read": 3.0, "vocab_learned": 12.0, "quiz_accuracy": 0.60, "completion": 0.60},
    "5-7": {"books_read": 8.0, "vocab_learned": 45.0, "quiz_accuracy": 0.72, "completion": 0.65},
    "7-9": {"books_read": 15.0, "vocab_learned": 80.0, "quiz_accuracy": 0.78, "completion": 0.70},
    "adult": {"books_read": 25.0, "vocab_learned": 140.0, "quiz_accuracy": 0.85, "completion": 0.75},
}

# 연령층별 복합 점수 가중치(합=1.0). 저연령일수록 완독·정확도, 고연령일수록 어휘 비중↑
# (읽기발달: 해독→유창성→독해, Lexile/F&P 가중 설계 반영).
AGE_WEIGHTS = {
    "3-5": {"books": 0.20, "vocab": 0.10, "accuracy": 0.30, "completion": 0.40},
    "5-7": {"books": 0.25, "vocab": 0.25, "accuracy": 0.30, "completion": 0.20},
    "7-9": {"books": 0.20, "vocab": 0.30, "accuracy": 0.30, "completion": 0.20},
    "adult": {"books": 0.20, "vocab": 0.30, "accuracy": 0.30, "completion": 0.20},
}

MIN_PEERS_FOR_REAL = 5
# 어휘 '습득'으로 인정하는 최소 정답 횟수(distinct term).
# 4지선다 어휘 게임에서 정답 1회 = 한 번의 '인식' 신호로 인정한다(추정). 자유 탭이 아니라
# 4지선다라 무지성 양성은 아니며, 1회로 둬야 단권 읽기에서도 '학습 어휘'가 실제로 쌓인다.
VOCAB_MASTERY_MIN_CORRECT = 1

_LEVEL_LABELS = {
    1: "첫 걸음", 2: "첫 걸음", 3: "기초 다지기", 4: "기초 다지기",
    5: "꾸준히 성장", 6: "꾸준히 성장", 7: "읽기 도약", 8: "읽기 도약",
    9: "능숙한 독서가", 10: "능숙한 독서가",
}


def _level_label(level: int) -> str:
    return _LEVEL_LABELS.get(level, "성장 중")


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _medal_for(top_percent: int) -> str:
    if top_percent <= 10:
        return "gold"
    if top_percent <= 30:
        return "silver"
    if top_percent <= 60:
        return "bronze"
    return "none"


def _top_percent_vs_ref(mine: float, ref: float) -> int:
    """또래 표본이 희소할 때, 내 값/기준선 비율로 상위% 근사."""
    if ref <= 0:
        return 50
    ratio = mine / ref
    if ratio >= 1.5:
        return 5
    if ratio >= 1.2:
        return 15
    if ratio >= 1.0:
        return 30
    if ratio >= 0.7:
        return 55
    return 80


def composite_reading_score(
    books_read: float,
    vocab_learned: float,
    quiz_accuracy: Optional[float],
    completion: Optional[float],
    age_band: str,
) -> dict:
    """다축 복합 읽기 점수(0~100) + 레벨(1~10). 연령층별 가중·정규화.

    단일 지표(읽은 책 수)가 아니라 읽은 책·어휘·정확도·완독을 종합한다.
    공인 척도가 아닌 *추정*임을 estimated=True 로 명시.

    accuracy·completion은 '비율'이라 데이터가 없으면(None) 0점이 아니라 *해당 축을
    빼고 가중치를 남은 축에 재분배*한다(missing≠zero): 퀴즈를 안 푼 다독 아동이
    정확도 0.0으로 30% 부당 감점되는 측정 오류를 막는다. books·vocab은 카운트라
    데이터가 없으면 0이 정상.
    """
    base = AGE_BASELINES.get(age_band, AGE_BASELINES["5-7"])
    w = AGE_WEIGHTS.get(age_band, AGE_WEIGHTS["5-7"])
    n_books = _clamp01(books_read / (base["books_read"] * 1.5)) if base["books_read"] else 0.0
    n_vocab = _clamp01(vocab_learned / (base["vocab_learned"] * 1.5)) if base["vocab_learned"] else 0.0
    axes = [(w["books"], n_books), (w["vocab"], n_vocab)]
    if quiz_accuracy is not None:
        axes.append((w["accuracy"], _clamp01(quiz_accuracy)))
    if completion is not None:
        axes.append((w["completion"], _clamp01(completion)))
    total_w = sum(wt for wt, _ in axes)
    raw = _clamp01(sum(wt * v for wt, v in axes) / total_w) if total_w > 0 else 0.0
    level = max(1, min(10, int(round(1 + raw * 9))))
    return {
        "level": level,
        "label": _level_label(level),
        "score": round(raw * 100),
        "scale_max": 10,
        "estimated": True,
    }


def estimate_reading_level(
    books_read: int, quiz_accuracy: float, vocab_learned: int
) -> dict:
    """(레거시·테스트용) 단순 추정 레벨. 실제 산출은 composite_reading_score 사용."""
    score = 0.0
    score += min(books_read, 60) * 0.08
    score += min(vocab_learned, 200) * 0.015
    score += quiz_accuracy * 2.0
    level = max(1, min(10, int(round(1 + score))))
    return {
        "level": level,
        "label": _level_label(level),
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

    async def _tiered_vocab_count(
        self, db: AsyncSession, qa_where: list
    ) -> int:
        """'습득' 어휘 수 = 정답 ≥ VOCAB_MASTERY_MIN_CORRECT 인 distinct term(거짓양성 차단)."""
        sub = (
            select(QuizAnswer.term)
            .where(
                *qa_where,
                QuizAnswer.quiz_type == "vocab",
                QuizAnswer.correct.is_(True),
                QuizAnswer.term.isnot(None),
            )
            .group_by(QuizAnswer.term)
            .having(func.count(QuizAnswer.id) >= VOCAB_MASTERY_MIN_CORRECT)
            .subquery()
        )
        return (
            await db.execute(select(func.count()).select_from(sub))
        ).scalar() or 0

    async def get_growth_report(
        self,
        db: AsyncSession,
        user_key: str,
        profile_id: Optional[str] = None,
    ) -> dict:
        rl_where = [ReadingLog.user_key == user_key]
        if profile_id:
            rl_where.append(ReadingLog.profile_id == profile_id)
        books_read = (
            await db.execute(
                select(func.count(distinct(ReadingLog.book_id))).where(*rl_where)
            )
        ).scalar() or 0

        # 완독률 = 완독 로그 / 전체 로그
        rl_total = (
            await db.execute(select(func.count(ReadingLog.id)).where(*rl_where))
        ).scalar() or 0
        rl_completed = (
            await db.execute(
                select(func.count(ReadingLog.id)).where(
                    *rl_where, ReadingLog.completed.is_(True)
                )
            )
        ).scalar() or 0
        completion = round(rl_completed / rl_total, 3) if rl_total else 0.0

        # 스트릭: 프로필 지정 시 프로필 단위로(형제 합산 방지). DailyStreak 테이블은
        # 계정 단위라 profile_id 컬럼이 없으므로, 프로필별은 ReadingLog 기반 재계산에 위임.
        if profile_id:
            from src.services.streak import streak_service

            ps = await streak_service.get_streak_info(db, user_key, profile_id)
            current_streak = ps["current_streak"]
            longest_streak = ps["longest_streak"]
            total_reading_days = ps["total_days"]
        else:
            streak = (
                await db.execute(
                    select(DailyStreak).where(DailyStreak.user_key == user_key)
                )
            ).scalar_one_or_none()
            current_streak = streak.current_streak if streak else 0
            longest_streak = streak.longest_streak if streak else 0
            total_reading_days = streak.total_days if streak else 0

        qa_where = [QuizAnswer.user_key == user_key]
        if profile_id:
            qa_where.append(QuizAnswer.profile_id == profile_id)
        # 정확도(quiz_accuracy)는 '독해' 신호만 — 4지선다 어휘게임(vocab)은 소거가 쉬워
        # 추측 정답이 정확도를 부풀린다. vocab은 vocab_learned로만 집계하고 정확도에서 분리.
        qa_quiz_where = [*qa_where, QuizAnswer.quiz_type != "vocab"]
        quiz_total = (
            await db.execute(select(func.count(QuizAnswer.id)).where(*qa_quiz_where))
        ).scalar() or 0
        quiz_correct = (
            await db.execute(
                select(func.count(QuizAnswer.id)).where(
                    *qa_quiz_where, QuizAnswer.correct.is_(True)
                )
            )
        ).scalar() or 0
        quiz_accuracy = round(quiz_correct / quiz_total, 3) if quiz_total else 0.0

        # 학습 어휘 = 정답 ≥ VOCAB_MASTERY_MIN_CORRECT 인 distinct term
        vocab_learned = await self._tiered_vocab_count(db, qa_where)

        age_band = await self._resolve_age_band(db, user_key, profile_id)
        # 데이터 없는 비율 축은 None으로 — 점수에서 0점 처벌 대신 가중 재분배(missing≠zero).
        reading_level = composite_reading_score(
            int(books_read),
            int(vocab_learned),
            quiz_accuracy if quiz_total else None,
            completion if rl_total else None,
            age_band,
        )

        return {
            "books_read": int(books_read),
            "current_streak": int(current_streak),
            "longest_streak": int(longest_streak),
            "total_reading_days": int(total_reading_days),
            "vocab_learned": int(vocab_learned),
            "quiz_total": int(quiz_total),
            "quiz_correct": int(quiz_correct),
            "quiz_accuracy": quiz_accuracy,
            "completion": completion,
            "reading_level": reading_level,
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

    async def _bulk_metrics(self, db: AsyncSession, user_keys: list) -> dict:
        """여러 user_key의 지표를 한 번에 — 또래 비교용. 반환: {uk: {books,vocab,accuracy,completion}} + active set."""
        if not user_keys:
            return {"metrics": {}, "active": set()}

        book_rows = (
            await db.execute(
                select(ReadingLog.user_key, func.count(distinct(ReadingLog.book_id)))
                .where(ReadingLog.user_key.in_(user_keys))
                .group_by(ReadingLog.user_key)
            )
        ).all()
        books = {k: int(c) for k, c in book_rows}

        comp_rows = (
            await db.execute(
                select(
                    ReadingLog.user_key,
                    func.count(ReadingLog.id),
                    func.sum(case((ReadingLog.completed.is_(True), 1), else_=0)),
                )
                .where(ReadingLog.user_key.in_(user_keys))
                .group_by(ReadingLog.user_key)
            )
        ).all()
        completion = {
            k: (int(c or 0) / int(t)) if int(t or 0) > 0 else 0.0
            for k, t, c in comp_rows
        }

        # 정확도는 vocab 제외(독해 신호만) — 어휘게임 추측 정답의 정확도 오염 방지.
        acc_rows = (
            await db.execute(
                select(
                    QuizAnswer.user_key,
                    func.count(QuizAnswer.id),
                    func.sum(case((QuizAnswer.correct.is_(True), 1), else_=0)),
                )
                .where(
                    QuizAnswer.user_key.in_(user_keys),
                    QuizAnswer.quiz_type != "vocab",
                )
                .group_by(QuizAnswer.user_key)
            )
        ).all()
        # 데이터 없는 user_key는 dict에 없음 → 점수 계산에서 None(축 제외)로 처리.
        accuracy = {
            k: (int(c or 0) / int(t))
            for k, t, c in acc_rows
            if int(t or 0) > 0
        }
        # '활성'은 읽기/모든 퀴즈(vocab 포함) 활동 — 코호트 포함 판정용.
        quiz_users = set(
            (
                await db.execute(
                    select(distinct(QuizAnswer.user_key)).where(
                        QuizAnswer.user_key.in_(user_keys)
                    )
                )
            ).scalars().all()
        )

        vsub = (
            select(QuizAnswer.user_key.label("uk"))
            .where(
                QuizAnswer.user_key.in_(user_keys),
                QuizAnswer.quiz_type == "vocab",
                QuizAnswer.correct.is_(True),
                QuizAnswer.term.isnot(None),
            )
            .group_by(QuizAnswer.user_key, QuizAnswer.term)
            .having(func.count(QuizAnswer.id) >= VOCAB_MASTERY_MIN_CORRECT)
            .subquery()
        )
        vrows = (
            await db.execute(
                select(vsub.c.uk, func.count()).group_by(vsub.c.uk)
            )
        ).all()
        vocab = {k: int(c) for k, c in vrows}

        active = set(books.keys()) | quiz_users
        metrics = {}
        for uk in user_keys:
            metrics[uk] = {
                "books": books.get(uk, 0),
                "vocab": vocab.get(uk, 0),
                "accuracy": accuracy.get(uk),  # None=데이터 없음(점수에서 축 제외)
                "completion": completion.get(uk),  # None=읽기 없음
            }
        return {"metrics": metrics, "active": active}

    async def get_peer_comparison(
        self,
        db: AsyncSession,
        user_key: str,
        profile_id: Optional[str] = None,
    ) -> dict:
        """같은 연령대 또래 대비 — *복합 점수* 기준 상위%·메달.

        - 단일축(읽은 책 수) 대신 복합 점수로 순위(거짓 일관성 제거).
        - 본인·비활성 가입자는 또래 모집단에서 제외(역네트워크·디플레이트 차단).
        - 3-5세는 백분위·등수가 발달상 무의미 → show_ranking=False(UI는 자기성장만 노출).
        - 또래 < MIN_PEERS_FOR_REAL 이면 연령대 기준선 폴백(is_baseline=True, 참고용).
        """
        age_band = await self._resolve_age_band(db, user_key, profile_id)
        base = AGE_BASELINES.get(age_band, AGE_BASELINES["5-7"])
        show_ranking = age_band not in ("3-5",)

        # 같은 연령대·본인 제외 후보
        peer_keys = (
            await db.execute(
                select(distinct(ChildProfile.user_key)).where(
                    ChildProfile.age_band == age_band,
                    ChildProfile.user_key != user_key,
                )
            )
        ).scalars().all()

        # 본인 점수는 프로필 단위로 산출(형제 합산 방지 + 성장 리포트 히어로와 일치).
        my_report = await self.get_growth_report(db, user_key, profile_id)
        my_score = my_report["reading_level"]["score"]
        my_metrics = {
            "books_read": my_report["books_read"],
            "vocab_learned": my_report["vocab_learned"],
            "quiz_accuracy": my_report["quiz_accuracy"],
            "score": my_score,
        }

        # 또래는 계정(user_key) 단위 집계 — 같은 연령대 가정당 1개. 프로필 단위 코호트는
        # ReadingLog.profile_id가 nullable이라 신뢰 불가하여 보수적으로 계정 단위 유지.
        bulk = await self._bulk_metrics(db, list(peer_keys))
        metrics = bulk["metrics"]
        active = bulk["active"]

        _empty = {"books": 0, "vocab": 0, "accuracy": None, "completion": None}

        def score_of(uk: str) -> int:
            m = metrics.get(uk, _empty)
            return composite_reading_score(
                m["books"], m["vocab"], m["accuracy"], m["completion"], age_band
            )["score"]

        # 활성 또래만 코호트로
        cohort = [k for k in peer_keys if k in active]
        peer_count = len(cohort)

        if peer_count < MIN_PEERS_FOR_REAL:
            ref_score = composite_reading_score(
                base["books_read"], int(base["vocab_learned"]),
                base["quiz_accuracy"], base["completion"], age_band
            )["score"]
            top_percent = _top_percent_vs_ref(my_score, ref_score)
            return {
                "age_band": age_band,
                "peer_count": peer_count,
                # 실제 또래가 부족하면(< MIN_PEERS_FOR_REAL) 등수/메달을 '또래 비교'로
                # 노출하지 않는다 — 비교 대상이 없는데 '상위 N%·금메달'을 단정하면 거짓.
                # UI는 자기성장만 보여준다(연령 무관).
                "is_baseline": True,
                "show_ranking": False,
                "my": my_metrics,
                "peer_avg": {
                    "books_read": base["books_read"],
                    "vocab_learned": base["vocab_learned"],
                    "quiz_accuracy": base["quiz_accuracy"],
                    "score": ref_score,
                },
                "top_percent": top_percent,
                "medal": _medal_for(top_percent),
            }

        peer_scores = [score_of(k) for k in cohort]
        # 표준 백분위(midrank): 동점은 절반만 내 아래로 — '동점=내 위'(<=)로 인한
        # 중앙값 아동의 '상위 1%·금메달' 과대평가를 막는다(복합점수 정수라 동점 흔함).
        below = sum(1 for s in peer_scores if s < my_score)
        ties = sum(1 for s in peer_scores if s == my_score)
        percentile = (below + 0.5 * ties) / peer_count * 100
        top_percent = max(1, min(99, round(100 - percentile)))

        avg_books = sum(metrics[k]["books"] for k in cohort) / peer_count
        avg_vocab = sum(metrics[k]["vocab"] for k in cohort) / peer_count
        accs = [metrics[k]["accuracy"] for k in cohort if metrics[k]["accuracy"] is not None]
        avg_acc = sum(accs) / len(accs) if accs else 0.0
        avg_score = sum(peer_scores) / peer_count

        return {
            "age_band": age_band,
            "peer_count": peer_count,
            "is_baseline": False,
            "show_ranking": show_ranking,
            "my": my_metrics,
            "peer_avg": {
                "books_read": round(avg_books, 1),
                "vocab_learned": round(avg_vocab, 1),
                "quiz_accuracy": round(avg_acc, 3),
                "score": round(avg_score),
            },
            "top_percent": top_percent,
            "medal": _medal_for(top_percent),
        }


growth_service = GrowthService()
