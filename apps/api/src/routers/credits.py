"""
Credits Router
크레딧 및 구독 관련 API
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from src.core.database import get_db
from src.services.credits import credits_service, SUBSCRIPTION_PLANS

router = APIRouter()


def get_user_key(x_user_key: str = Header(..., description="User identification key")) -> str:
    """Extract user key from header"""
    if not x_user_key or len(x_user_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid X-User-Key header")
    return x_user_key


# ==================== Response Models ====================

class CreditsResponse(BaseModel):
    credits: int
    total_purchased: int
    total_used: int


class SubscriptionResponse(BaseModel):
    plan: str
    plan_name: str
    status: str
    credits_per_month: int
    current_period_end: datetime
    features: list[str]


class SubscriptionPlan(BaseModel):
    id: str
    name: str
    price: int
    credits_per_month: int
    features: list[str]


class TransactionResponse(BaseModel):
    id: int
    amount: int
    balance_after: int
    transaction_type: str
    description: Optional[str]
    created_at: datetime


class CreditsStatusResponse(BaseModel):
    credits: CreditsResponse
    subscription: Optional[SubscriptionResponse]
    available_plans: list[SubscriptionPlan]


# ==================== Request Models ====================

class SubscribeRequest(BaseModel):
    plan: str


class AddCreditsRequest(BaseModel):
    amount: int
    transaction_id: Optional[str] = None  # 외부 결제 ID


# ==================== Endpoints ====================

@router.get("/status", response_model=CreditsStatusResponse)
async def get_credits_status(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    크레딧 및 구독 상태 조회

    - 현재 크레딧 잔액
    - 구독 정보
    - 사용 가능한 플랜
    """
    # 크레딧 정보
    user_credits = await credits_service.get_or_create_credits(db, user_key)

    # 구독 정보
    subscription = await credits_service.get_active_subscription(db, user_key)
    subscription_response = None
    if subscription:
        plan_info = SUBSCRIPTION_PLANS.get(subscription.plan, {})
        subscription_response = SubscriptionResponse(
            plan=subscription.plan,
            plan_name=plan_info.get("name", subscription.plan),
            status=subscription.status,
            credits_per_month=subscription.credits_per_month,
            current_period_end=subscription.current_period_end,
            features=plan_info.get("features", []),
        )

    # 사용 가능한 플랜
    available_plans = [
        SubscriptionPlan(
            id=plan_id,
            name=plan_info["name"],
            price=plan_info["price"],
            credits_per_month=plan_info["credits_per_month"],
            features=plan_info["features"],
        )
        for plan_id, plan_info in SUBSCRIPTION_PLANS.items()
    ]

    return CreditsStatusResponse(
        credits=CreditsResponse(
            credits=user_credits.credits,
            total_purchased=user_credits.total_purchased,
            total_used=user_credits.total_used,
        ),
        subscription=subscription_response,
        available_plans=available_plans,
    )


@router.get("/balance")
async def get_credits_balance(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """현재 크레딧 잔액 조회"""
    credits = await credits_service.get_credits(db, user_key)
    return {"credits": credits}


@router.get("/transactions", response_model=list[TransactionResponse])
async def get_transactions(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """거래 내역 조회"""
    transactions = await credits_service.get_transaction_history(
        db, user_key, limit=limit, offset=offset
    )
    return [
        TransactionResponse(
            id=t.id,
            amount=t.amount,
            balance_after=t.balance_after,
            transaction_type=t.transaction_type,
            description=t.description,
            created_at=t.created_at,
        )
        for t in transactions
    ]


@router.post("/subscribe")
async def subscribe(
    request: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    구독 시작

    - plan: free, basic, premium
    - 실제 결제 로직은 클라이언트에서 처리 후 호출
    """
    if request.plan not in SUBSCRIPTION_PLANS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid plan. Available: {list(SUBSCRIPTION_PLANS.keys())}"
        )

    try:
        subscription = await credits_service.create_subscription(
            db, user_key, request.plan
        )
        plan_info = SUBSCRIPTION_PLANS[request.plan]

        return {
            "status": "success",
            "message": f"{plan_info['name']} 구독이 시작되었습니다.",
            "subscription": {
                "plan": subscription.plan,
                "credits_per_month": subscription.credits_per_month,
                "current_period_end": subscription.current_period_end.isoformat(),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel-subscription")
async def cancel_subscription(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """구독 취소"""
    success = await credits_service.cancel_subscription(db, user_key)

    if not success:
        raise HTTPException(status_code=404, detail="활성 구독이 없습니다.")

    return {
        "status": "success",
        "message": "구독이 취소되었습니다. 현재 기간이 끝날 때까지 사용 가능합니다.",
    }


@router.post("/add")
async def add_credits(
    request: AddCreditsRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    크레딧 추가 (구매)

    - 실제 결제 로직은 클라이언트에서 처리 후 호출
    - transaction_id: 외부 결제 시스템의 거래 ID
    """
    if request.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    new_balance = await credits_service.add_credits(
        db=db,
        user_key=user_key,
        amount=request.amount,
        transaction_type="purchase",
        description=f"크레딧 {request.amount}개 구매",
        reference_id=request.transaction_id,
    )

    return {
        "status": "success",
        "message": f"{request.amount} 크레딧이 추가되었습니다.",
        "new_balance": new_balance,
    }


@router.get("/check")
async def check_credits(
    required: int = 1,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """크레딧 충분 여부 확인"""
    has_credits = await credits_service.has_credits(db, user_key, required)
    current_credits = await credits_service.get_credits(db, user_key)

    return {
        "has_credits": has_credits,
        "current_credits": current_credits,
        "required": required,
    }
