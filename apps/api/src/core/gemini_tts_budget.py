"""Persistent, fail-closed request admission for paid Gemini narration.

This is an application request count, not a monetary or provider-side cap.
Every admitted outbound attempt consumes both limits, including failures.
"""
from sqlalchemy import text

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import APIError
from src.core.utils import to_local_date, utcnow
from src.models.gemini_tts_budget import GeminiTTSRequestBudget  # noqa: F401


class _LimitReached(Exception):
    pass


async def require_gemini_tts_request_budget():
    daily = settings.google_gemini_tts_daily_request_limit
    monthly = settings.google_gemini_tts_monthly_request_limit
    if daily <= 0 or monthly <= 0:
        raise APIError(status_code=503, error_code='SERVICE_UNAVAILABLE',
                       message='낭독 생성 한도를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.')
    # Billing-admission periods are always Korea-local, even if the shared
    # utility's default timezone changes for user-facing features later.
    current = to_local_date(utcnow(), tz='Asia/Seoul')
    periods = ((f'day:{current:%Y%m%d}', daily), (f'month:{current:%Y%m}', monthly))
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                for bucket, limit in periods:
                    # Single atomic statement; a failed month admission rolls the
                    # day increment back in the same transaction. Every worker
                    # connects to the same DB before making the provider call.
                    result = await db.execute(text('''
                        INSERT INTO gemini_tts_request_budget (bucket, requests)
                        VALUES (:bucket, 1)
                        ON CONFLICT (bucket) DO UPDATE
                        SET requests = gemini_tts_request_budget.requests + 1
                        WHERE gemini_tts_request_budget.requests < :request_limit
                        RETURNING requests
                    '''), {'bucket': bucket, 'request_limit': limit})
                    if result.scalar_one_or_none() is None:
                        raise _LimitReached()
    except _LimitReached:
        raise APIError(status_code=429, error_code='SERVICE_BUDGET_EXCEEDED',
                       message='낭독 생성 한도에 도달했어요. 잠시 후 다시 시도해주세요.') from None
    except Exception:
        # Missing migrations, DB unavailability or an interrupted transaction
        # must not allow a paid request through without a durable reservation.
        raise APIError(status_code=503, error_code='SERVICE_UNAVAILABLE',
                       message='낭독 생성 한도를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.') from None
