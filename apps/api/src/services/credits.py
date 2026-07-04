"""
Credits Service
크레딧 관리 및 구독 시스템
"""

from datetime import timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, case
from sqlalchemy.exc import IntegrityError

from ..models.db import UserCredits, Subscription, CreditTransaction
from ..core.utils import utcnow


# 구독 플랜 정의
SUBSCRIPTION_PLANS = {
    "free": {
        "name": "무료",
        "price": 0,
        "credits_per_month": 2,
        "features": ["월 2권 생성", "watercolor/cartoon 스타일", "오디오/PDF 미지원"],
    },
    "basic": {
        "name": "베이직",
        "price": 6900,  # 원
        "credits_per_month": 10,
        "features": ["월 10권 생성", "모든 스타일", "PDF", "기본 TTS"],
    },
    "premium": {
        "name": "프리미엄",
        "price": 14900,  # 원
        "credits_per_month": 30,
        "features": ["월 30권 생성", "모든 기능", "프리미엄 TTS", "우선 처리"],
    },
}


class CreditsService:
    """크레딧 관리 서비스"""

    async def get_or_create_credits(
        self,
        db: AsyncSession,
        user_key: str,
        commit: bool = True,
    ) -> UserCredits:
        """사용자 크레딧 정보 조회 또는 생성"""
        result = await db.execute(
            select(UserCredits).where(UserCredits.user_key == user_key)
        )
        user_credits = result.scalar_one_or_none()

        if not user_credits:
            # 새 사용자에게 기본 크레딧 제공
            user_credits = UserCredits(
                user_key=user_key,
                credits=3,
                total_purchased=0,
                total_used=0,
            )
            db.add(user_credits)

            # 보너스 크레딧 기록
            await self._record_transaction(
                db=db,
                user_key=user_key,
                amount=3,
                balance_after=3,
                transaction_type="bonus",
                description="신규 가입 보너스 크레딧",
                commit=False,
            )

            if commit:
                await db.commit()
                await db.refresh(user_credits)
            else:
                await db.flush()

        return user_credits

    async def get_credits(
        self,
        db: AsyncSession,
        user_key: str,
    ) -> int:
        """현재 크레딧 잔액 조회"""
        user_credits = await self.get_or_create_credits(db, user_key)
        return user_credits.credits

    async def has_credits(
        self,
        db: AsyncSession,
        user_key: str,
        required: int = 1,
    ) -> bool:
        """크레딧이 충분한지 확인"""
        credits = await self.get_credits(db, user_key)
        return credits >= required

    async def use_credit(
        self,
        db: AsyncSession,
        user_key: str,
        amount: int = 1,
        description: str = "책 생성",
        reference_id: Optional[str] = None,
    ) -> bool:
        """
        크레딧 사용 (DB 독립적 원자적 차감)

        - SQLite는 SELECT ... FOR UPDATE 미지원 → 테스트에서 즉시 실패 가능
        - 조건부 UPDATE(credits >= amount)로 원자성 확보
        """
        try:
            # ensure user exists (creates row if missing)
            await self.get_or_create_credits(db, user_key, commit=False)

            # 원자적 UPDATE: credits >= amount 조건으로 차감
            stmt = (
                update(UserCredits)
                .where(
                    UserCredits.user_key == user_key,
                    UserCredits.credits >= amount,
                )
                .values(
                    credits=UserCredits.credits - amount,
                    total_used=UserCredits.total_used + amount,
                )
            )

            result = await db.execute(stmt)
            affected = result.rowcount if hasattr(result, "rowcount") else 0

            if affected <= 0:
                await db.rollback()
                return False

            balance_result = await db.execute(
                select(UserCredits.credits).where(UserCredits.user_key == user_key)
            )
            new_balance = balance_result.scalar_one()

            # 거래 기록
            await self._record_transaction(
                db=db,
                user_key=user_key,
                amount=-amount,
                balance_after=new_balance,
                transaction_type="usage",
                description=description,
                reference_id=reference_id,
                commit=False,
            )

            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise

    async def add_credits(
        self,
        db: AsyncSession,
        user_key: str,
        amount: int,
        transaction_type: str = "purchase",
        description: str = "크레딧 구매",
        reference_id: Optional[str] = None,
        commit: bool = True,
    ) -> int:
        """크레딧 충전 (원자적 UPDATE)"""
        try:
            # ensure user exists
            await self.get_or_create_credits(db, user_key, commit=False)

            # 원자적 UPDATE
            values = {
                "credits": UserCredits.credits + amount,
            }
            if transaction_type == "purchase":
                values["total_purchased"] = UserCredits.total_purchased + amount

            stmt = (
                update(UserCredits)
                .where(UserCredits.user_key == user_key)
                .values(**values)
            )
            await db.execute(stmt)

            balance_result = await db.execute(
                select(UserCredits.credits).where(UserCredits.user_key == user_key)
            )
            new_balance = balance_result.scalar_one()

            # 거래 기록
            await self._record_transaction(
                db=db,
                user_key=user_key,
                amount=amount,
                balance_after=new_balance,
                transaction_type=transaction_type,
                description=description,
                reference_id=reference_id,
                commit=False,
            )

            if commit:
                await db.commit()
            else:
                await db.flush()

            return new_balance
        except Exception:
            await db.rollback()
            raise

    async def add_milestone_credits_once(
        self,
        db: AsyncSession,
        user_key: str,
        amount: int,
        reference_id: str,
        description: str,
    ) -> bool:
        """같은 사용자·마일스톤 보상은 DB 제약으로 한 번만 지급한다."""
        try:
            await self.add_credits(
                db=db,
                user_key=user_key,
                amount=amount,
                transaction_type="bonus",
                description=description,
                reference_id=reference_id,
            )
        except IntegrityError:
            existing_reward = await db.scalar(
                select(CreditTransaction.id).where(
                    CreditTransaction.user_key == user_key,
                    CreditTransaction.transaction_type == "bonus",
                    CreditTransaction.reference_id == reference_id,
                )
            )
            if existing_reward is None:
                raise
            return False
        return True

    async def refund_for_job(
        self,
        db: AsyncSession,
        user_key: str,
        job_id: str,
        description: str = "생성 실패 환불",
        commit: bool = True,
    ) -> bool:
        """잡이 크레딧을 소모(usage)했고 아직 환불되지 않은 경우에만 1 크레딧 환불.

        멱등(중복 호출·재스캔에도 1회만)하며 과금된 적 없는 잡(예: 재생성)은 환불하지 않는다.
        job_monitor가 스턱 잡을 최종 실패 처리할 때의 silent 크레딧 손실을 막는다.
        반환: 실제 환불 여부.
        """
        used = await db.execute(
            select(CreditTransaction.id)
            .where(
                CreditTransaction.reference_id == job_id,
                CreditTransaction.transaction_type == "usage",
            )
            .limit(1)
        )
        if used.first() is None:
            return False  # 과금된 적 없음 → 환불 안 함

        already = await db.execute(
            select(CreditTransaction.id)
            .where(
                CreditTransaction.reference_id == job_id,
                CreditTransaction.transaction_type == "refund",
            )
            .limit(1)
        )
        if already.first() is not None:
            return False  # 이미 환불됨 → 이중환불 방지

        await self.add_credits(
            db,
            user_key,
            amount=1,
            transaction_type="refund",
            description=description,
            reference_id=job_id,
            commit=commit,
        )
        return True

    async def clawback_credits(
        self,
        db: AsyncSession,
        user_key: str,
        amount: int,
        reference_id: str,
        description: str = "환불 회수",
        commit: bool = True,
    ) -> bool:
        """환불/취소 시 지급했던 크레딧을 회수한다(잔액은 0 미만으로 내려가지 않음).

        멱등: 같은 reference_id로 이미 회수했으면 재회수하지 않는다(중복 웹훅 방어).
        반환: 실제 회수 수행 여부.
        """
        if amount <= 0:
            return False

        already = await db.execute(
            select(CreditTransaction.id)
            .where(
                CreditTransaction.reference_id == reference_id,
                CreditTransaction.transaction_type == "clawback",
            )
            .limit(1)
        )
        if already.first() is not None:
            return False  # 이미 회수됨

        try:
            await self.get_or_create_credits(db, user_key, commit=False)
            # 원자적 차감 후 음수 클램프(두 문장 모두 같은 트랜잭션 내 → SQLite/PG 공통).
            await db.execute(
                update(UserCredits)
                .where(UserCredits.user_key == user_key)
                .values(credits=UserCredits.credits - amount)
            )
            await db.execute(
                update(UserCredits)
                .where(UserCredits.user_key == user_key, UserCredits.credits < 0)
                .values(credits=0)
            )
            balance_result = await db.execute(
                select(UserCredits.credits).where(UserCredits.user_key == user_key)
            )
            new_balance = balance_result.scalar_one()
            await self._record_transaction(
                db=db,
                user_key=user_key,
                amount=-amount,
                balance_after=new_balance,
                transaction_type="clawback",
                description=description,
                reference_id=reference_id,
                commit=False,
            )
            if commit:
                await db.commit()
            else:
                await db.flush()
            return True
        except Exception:
            if commit:
                await db.rollback()
            raise

    async def get_active_subscription(
        self,
        db: AsyncSession,
        user_key: str,
    ) -> Optional[Subscription]:
        """현재 사용 권한이 있는 구독 조회 (active/cancelled + 기간 내)."""
        result = await db.execute(
            select(Subscription)
            .where(
                Subscription.user_key == user_key,
                Subscription.status.in_(["active", "cancelled"]),
                Subscription.current_period_end > utcnow(),
            )
            .order_by(
                case((Subscription.status == "active", 0), else_=1),
                Subscription.current_period_end.desc(),
                Subscription.created_at.desc(),
            )
        )
        return result.scalars().first()

    async def create_subscription(
        self,
        db: AsyncSession,
        user_key: str,
        plan: str,
        commit: bool = True,
    ) -> Subscription:
        """구독 생성.

        commit=False면 커밋하지 않고 flush만 한다 — 호출부가 보상 지급과 영수증
        기록을 한 트랜잭션으로 묶어 단일 커밋하도록(IAP 더블그랜트 방지).
        """
        if plan not in SUBSCRIPTION_PLANS:
            raise ValueError(f"Invalid plan: {plan}")

        plan_info = SUBSCRIPTION_PLANS[plan]
        now = utcnow()

        # 기존 활성 구독 취소
        existing = await self.get_active_subscription(db, user_key)
        if existing:
            existing.status = "cancelled"
            existing.current_period_end = now

        # 새 구독 생성
        try:
            subscription = Subscription(
                user_key=user_key,
                plan=plan,
                status="active",
                credits_per_month=plan_info["credits_per_month"],
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
            db.add(subscription)
            await db.flush()

            # 월간 크레딧 지급
            await self.add_credits(
                db=db,
                user_key=user_key,
                amount=plan_info["credits_per_month"],
                transaction_type="subscription",
                description=f"{plan_info['name']} 구독 크레딧",
                reference_id=str(subscription.id),
                commit=False,
            )

            if commit:
                await db.commit()
                await db.refresh(subscription)
            else:
                await db.flush()
            return subscription
        except Exception:
            if commit:
                await db.rollback()
            raise

    async def cancel_subscription(
        self,
        db: AsyncSession,
        user_key: str,
    ) -> bool:
        """구독 취소"""
        subscription = await self.get_active_subscription(db, user_key)
        if not subscription:
            return False

        subscription.status = "cancelled"
        await db.commit()
        return True

    async def get_transaction_history(
        self,
        db: AsyncSession,
        user_key: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[CreditTransaction]:
        """거래 내역 조회"""
        result = await db.execute(
            select(CreditTransaction)
            .where(CreditTransaction.user_key == user_key)
            .order_by(CreditTransaction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def _record_transaction(
        self,
        db: AsyncSession,
        user_key: str,
        amount: int,
        balance_after: int,
        transaction_type: str,
        description: str,
        reference_id: Optional[str] = None,
        commit: bool = True,
    ):
        """거래 기록 생성"""
        transaction = CreditTransaction(
            user_key=user_key,
            amount=amount,
            balance_after=balance_after,
            transaction_type=transaction_type,
            description=description,
            reference_id=reference_id,
        )
        db.add(transaction)
        if commit:
            await db.commit()


# 싱글톤 인스턴스
credits_service = CreditsService()
