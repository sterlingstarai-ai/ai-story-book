"""
Credits Service
크레딧 관리 및 구독 시스템
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..models.db import UserCredits, Subscription, CreditTransaction


def utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


# 구독 플랜 정의
SUBSCRIPTION_PLANS = {
    "free": {
        "name": "무료",
        "price": 0,
        "credits_per_month": 3,
        "features": ["월 3권 생성", "기본 스타일"],
    },
    "basic": {
        "name": "베이직",
        "price": 9900,  # 원
        "credits_per_month": 15,
        "features": ["월 15권 생성", "모든 스타일", "PDF 내보내기"],
    },
    "premium": {
        "name": "프리미엄",
        "price": 19900,  # 원
        "credits_per_month": 50,
        "features": ["월 50권 생성", "모든 기능", "우선 처리", "TTS 오디오"],
    },
}


class CreditsService:
    """크레딧 관리 서비스"""

    async def get_or_create_credits(
        self,
        db: AsyncSession,
        user_key: str,
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
                credits=10,  # 무료 크레딧 (테스트용 10개)
                total_purchased=0,
                total_used=0,
            )
            db.add(user_credits)
            await db.commit()
            await db.refresh(user_credits)

            # 보너스 크레딧 기록
            await self._record_transaction(
                db=db,
                user_key=user_key,
                amount=10,
                balance_after=10,
                transaction_type="bonus",
                description="신규 가입 보너스 크레딧",
            )

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
        # ensure user exists (creates row if missing)
        await self.get_or_create_credits(db, user_key)

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

        await db.commit()

        # 새 잔액 조회
        new_balance = await self.get_credits(db, user_key)

        # 거래 기록
        await self._record_transaction(
            db=db,
            user_key=user_key,
            amount=-amount,
            balance_after=new_balance,
            transaction_type="usage",
            description=description,
            reference_id=reference_id,
        )

        return True

    async def add_credits(
        self,
        db: AsyncSession,
        user_key: str,
        amount: int,
        transaction_type: str = "purchase",
        description: str = "크레딧 구매",
        reference_id: Optional[str] = None,
    ) -> int:
        """크레딧 충전"""
        user_credits = await self.get_or_create_credits(db, user_key)

        user_credits.credits += amount
        if transaction_type == "purchase":
            user_credits.total_purchased += amount

        await db.commit()

        # 거래 기록
        await self._record_transaction(
            db=db,
            user_key=user_key,
            amount=amount,
            balance_after=user_credits.credits,
            transaction_type=transaction_type,
            description=description,
            reference_id=reference_id,
        )

        return user_credits.credits

    async def get_active_subscription(
        self,
        db: AsyncSession,
        user_key: str,
    ) -> Optional[Subscription]:
        """활성 구독 조회"""
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_key == user_key,
                Subscription.status == "active",
                Subscription.current_period_end > utcnow(),
            )
        )
        return result.scalar_one_or_none()

    async def create_subscription(
        self,
        db: AsyncSession,
        user_key: str,
        plan: str,
    ) -> Subscription:
        """구독 생성"""
        if plan not in SUBSCRIPTION_PLANS:
            raise ValueError(f"Invalid plan: {plan}")

        plan_info = SUBSCRIPTION_PLANS[plan]

        # 기존 활성 구독 취소
        existing = await self.get_active_subscription(db, user_key)
        if existing:
            existing.status = "cancelled"

        # 새 구독 생성
        now = utcnow()
        subscription = Subscription(
            user_key=user_key,
            plan=plan,
            status="active",
            credits_per_month=plan_info["credits_per_month"],
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        db.add(subscription)
        await db.commit()

        # 월간 크레딧 지급
        await self.add_credits(
            db=db,
            user_key=user_key,
            amount=plan_info["credits_per_month"],
            transaction_type="subscription",
            description=f"{plan_info['name']} 구독 크레딧",
            reference_id=str(subscription.id),
        )

        return subscription

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
        await db.commit()


# 싱글톤 인스턴스
credits_service = CreditsService()
