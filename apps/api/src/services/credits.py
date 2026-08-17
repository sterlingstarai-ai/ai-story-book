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
            # 신규 사용자 첫 요청 2건이 동시에 오면 PK(user_key) 충돌로 한쪽이 IntegrityError.
            # SAVEPOINT로 감싸 위반 시 이 인서트만 롤백하고 재조회해 500·보너스 이중지급을
            # 막는다(L8). commit=False 호출자의 상위 트랜잭션은 보존.
            try:
                async with db.begin_nested():
                    user_credits = UserCredits(
                        user_key=user_key,
                        credits=3,
                        total_purchased=0,
                        total_used=0,
                    )
                    db.add(user_credits)
                    await self._record_transaction(
                        db=db,
                        user_key=user_key,
                        amount=3,
                        balance_after=3,
                        transaction_type="bonus",
                        description="신규 가입 보너스 크레딧",
                        commit=False,
                    )
                    await db.flush()
            except IntegrityError:
                # 동시 최초 요청 경쟁 패자 — 재조회(보너스 이중 지급 없음).
                user_credits = (
                    await db.execute(
                        select(UserCredits).where(UserCredits.user_key == user_key)
                    )
                ).scalar_one()
                return user_credits

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
            # commit=False면 상위 트랜잭션을 소유한 호출자가 롤백/세이브포인트를 책임진다.
            # 여기서 무조건 db.rollback()을 하면 호출자의 미커밋 작업(IAPReceipt 등)까지
            # 폐기된다(CTO W1 감사 포워드리스크). clawback_credits 패턴과 정렬.
            if commit:
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

        if await self._job_already_refunded(db, job_id):
            return False  # 이미 환불됨 → 이중환불 방지(앱 레벨 1차)

        # 동시 두 번째 환불(멀티 레플리카)은 앱 체크를 통과할 수 있으나 uq_credit_transactions_refund
        # 부분 유니크(M16)가 DB 레벨에서 차단한다. 세이브포인트로 감싸 IntegrityError를 흡수하면
        # 호출자(commit=False, job_monitor 등)의 미커밋 작업(job.status 등)을 폐기하지 않는다.
        try:
            async with db.begin_nested():
                await self.add_credits(
                    db,
                    user_key,
                    amount=1,
                    transaction_type="refund",
                    description=description,
                    reference_id=job_id,
                    commit=False,
                )
        except IntegrityError:
            return False  # 동시 이중 환불 차단(멱등)

        if commit:
            await db.commit()
        return True

    async def _job_already_refunded(self, db: AsyncSession, job_id: str) -> bool:
        """해당 잡에 이미 refund 트랜잭션이 있는지(동시성 흡수 테스트의 시임 지점)."""
        already = await db.execute(
            select(CreditTransaction.id)
            .where(
                CreditTransaction.reference_id == job_id,
                CreditTransaction.transaction_type == "refund",
            )
            .limit(1)
        )
        return already.first() is not None

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
                CreditTransaction.user_key == user_key,
                CreditTransaction.reference_id == reference_id,
                CreditTransaction.transaction_type == "clawback",
            )
            .limit(1)
        )
        if already.first() is not None:
            return False  # 이미 회수됨(앱 레벨 1차)

        try:
            await self.get_or_create_credits(db, user_key, commit=False)
            # M2/R2-2: 위 pre-check는 트랜잭션 **밖**의 check-then-write다 — 동시 중복
            # 환불 웹훅 두 건이 모두 '아직 회수 안 됨'을 통과할 수 있다. 정본 방어는
            # `uq_credit_transactions_clawback` 부분 유니크이며, refund_for_job과 동일하게
            # SAVEPOINT로 감싸 IntegrityError를 흡수한다(호출자의 미커밋 작업 — 영수증 상태
            # 갱신 등 — 을 폐기하지 않도록).
            async with db.begin_nested():
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
                await db.flush()
        except IntegrityError:
            # 동시 이중 회수 차단(멱등) — 차감도 SAVEPOINT와 함께 롤백된다.
            return False
        except Exception:
            if commit:
                await db.rollback()
            raise

        if commit:
            await db.commit()
        else:
            await db.flush()
        return True

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

    async def expire_active_subscription_for_plan(
        self,
        db: AsyncSession,
        user_key: str,
        plan: str,
        commit: bool = False,
    ) -> None:
        """이전 소유자의 해당 plan active 구독만 만료(권한 이전, C1/G2).

        전 구독 일괄 만료는 타인의 정당한 다른 구독을 파기하므로 금지 — cancelled(잔여기간)는
        보존하고 같은 plan의 active만 즉시 만료한다.
        """
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_key == user_key,
                Subscription.plan == plan,
                Subscription.status == "active",
            )
        )
        now = utcnow()
        for sub in result.scalars().all():
            sub.status = "expired"
            sub.current_period_end = now - timedelta(seconds=1)
        if commit:
            await db.commit()

    async def supersede_cancelled_subscription_for_plan(
        self,
        db: AsyncSession,
        user_key: str,
        plan: str,
    ) -> None:
        """같은 plan의 cancelled 잔여 구독을 새 결제로 대체(종료)한다 (H3/R2-1).

        취소 후 재결제하면 그 결제가 잔여기간을 **대체**한다. 종료하지 않으면 같은 plan에
        entitlement를 주는 행이 둘(cancelled 잔여 + 신규 active) 남아, 이후 웹훅·환불이
        어느 행을 가리키는지가 모호해진다. active 구독은 건드리지 않는다(그 경우는 애초에
        already_subscribed로 걸러진다).
        """
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_key == user_key,
                Subscription.plan == plan,
                Subscription.status == "cancelled",
            )
        )
        now = utcnow()
        for sub in result.scalars().all():
            sub.status = "expired"
            sub.current_period_end = now - timedelta(seconds=1)

    async def create_subscription(
        self,
        db: AsyncSession,
        user_key: str,
        plan: str,
        commit: bool = True,
        grant_credits: bool = True,
    ) -> Subscription:
        """구독 생성.

        commit=False면 커밋하지 않고 flush만 한다 — 호출부가 보상 지급과 영수증
        기록을 한 트랜잭션으로 묶어 단일 커밋하도록(IAP 더블그랜트 방지).
        grant_credits=False면 구독 행만 생성/재활성하고 월간 크레딧은 지급하지 않는다
        (복원 시 소비성 크레딧 무한 재지급 방지, C1/G1).
        """
        if plan not in SUBSCRIPTION_PLANS:
            raise ValueError(f"Invalid plan: {plan}")

        plan_info = SUBSCRIPTION_PLANS[plan]
        now = utcnow()

        # 동시 create의 경쟁 패자는 (user_key) WHERE status='active' 부분 유니크(M17)에서
        # IntegrityError를 맞는다. 인서트를 SAVEPOINT(begin_nested)로 감싸 위반 시 이 인서트만
        # 롤백되게 하여, commit=False(IAP verify/restore) 호출자의 미커밋 작업(IAPReceipt 등)을
        # 폐기하지 않는다(CTO W1 감사 포워드리스크). 그 뒤 재조회하여 1회 재시도.
        for attempt in range(2):
            # 기존 활성 구독 취소. M13: current_period_end를 now로 즉시 소멸시키지 않는다 —
            # cancel_subscription 의미론(기간 만료까지 유지)과 정렬해 잔여기간 entitlement 보존.
            existing = await self.get_active_subscription(db, user_key)
            if existing:
                existing.status = "cancelled"

            # 호출자(IAP)의 미커밋 작업(IAPReceipt 등)과 위 취소를 SAVEPOINT 밖(outer tx)에
            # 먼저 flush한다 — production은 autoflush=False라 flush하지 않으면 이들이
            # begin_nested 안에서 처음 flush돼 경쟁 롤백 시 함께 폐기된다(CTO 포워드리스크).
            await db.flush()

            subscription = Subscription(
                user_key=user_key,
                plan=plan,
                status="active",
                credits_per_month=plan_info["credits_per_month"],
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
            try:
                async with db.begin_nested():  # SAVEPOINT
                    db.add(subscription)
                    await db.flush()
            except IntegrityError:
                if attempt == 0:
                    continue  # 경쟁 패자 → 재조회 후 기존 active 취소하고 재시도
                # 두 번째도 충돌: 경쟁 승자의 active를 최종본으로 반환.
                existing = await self.get_active_subscription(db, user_key)
                if existing is not None:
                    return existing
                raise

            # 월간 크레딧 지급(선택). 복원 등은 grant_credits=False로 재지급하지 않는다.
            if grant_credits:
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

        # 루프는 항상 return/raise로 종료(방어적 unreachable 가드).
        raise RuntimeError("create_subscription: unreachable")

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
