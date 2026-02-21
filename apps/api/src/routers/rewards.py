"""
Rewards Router
리워드 광고 보상 처리
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import ValidationError
from src.core.utils import utcnow
from src.models.db import AdRewardLog
from src.services.credits import credits_service

router = APIRouter()


class AdCompleteRequest(BaseModel):
    ad_network: Optional[str] = Field(default=None, max_length=40)
    ad_unit_id: Optional[str] = Field(default=None, max_length=120)


@router.post("/ad-complete")
async def complete_ad_reward(
    request: AdCompleteRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    광고 시청 완료 보상.
    정책: 일일 최대 3회, 회당 1 크레딧.
    """
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    count_result = await db.execute(
        select(func.count(AdRewardLog.id)).where(
            AdRewardLog.user_key == user_key,
            AdRewardLog.created_at >= today_start,
            AdRewardLog.created_at < tomorrow_start,
        )
    )
    today_count = count_result.scalar() or 0
    if today_count >= 3:
        raise ValidationError(
            "오늘의 무료 크레딧 횟수를 모두 사용했습니다.",
            details={"daily_limit": 3, "used": today_count},
        )

    new_balance = await credits_service.add_credits(
        db=db,
        user_key=user_key,
        amount=1,
        transaction_type="reward_ad",
        description="리워드 광고 시청 보상",
    )

    log = AdRewardLog(
        user_key=user_key,
        reward_type="credit",
        reward_amount=1,
        ad_network=request.ad_network,
        ad_unit_id=request.ad_unit_id,
    )
    db.add(log)
    await db.commit()

    return {
        "status": "success",
        "reward": 1,
        "today_used": today_count + 1,
        "today_limit": 3,
        "new_balance": new_balance,
    }
