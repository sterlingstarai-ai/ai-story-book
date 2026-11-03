"""Synthetic admission checks; no Google, Redis, or live credentials."""
import asyncio
from datetime import datetime

import pytest
from sqlalchemy import select

from src.core import gemini_tts_budget as budget
from src.core.exceptions import APIError
from src.models.gemini_tts_budget import GeminiTTSRequestBudget
from tests.conftest import TestSessionLocal


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(budget, 'AsyncSessionLocal', TestSessionLocal)
    monkeypatch.setattr(budget.settings, 'google_gemini_tts_daily_request_limit', 2)
    monkeypatch.setattr(budget.settings, 'google_gemini_tts_monthly_request_limit', 3)
    monkeypatch.setattr(budget, 'utcnow', lambda: datetime(2026, 11, 2, 0, 0))


@pytest.mark.asyncio
async def test_atomic_daily_cap_across_concurrent_workers(db_session, configured):
    results = await asyncio.gather(*(budget.require_gemini_tts_request_budget() for _ in range(8)),
                                   return_exceptions=True)
    assert sum(result is None for result in results) == 2
    assert all(result is None or isinstance(result, APIError) and result.status_code == 429 for result in results)
    async with TestSessionLocal() as check:
        rows = (await check.execute(select(GeminiTTSRequestBudget))).scalars().all()
        assert {row.bucket: row.requests for row in rows} == {'day:20261102': 2, 'month:202611': 2}


@pytest.mark.asyncio
async def test_monthly_rejection_rolls_back_daily_and_month_changes(db_session, configured, monkeypatch):
    monkeypatch.setattr(budget.settings, 'google_gemini_tts_monthly_request_limit', 1)
    await budget.require_gemini_tts_request_budget()
    monkeypatch.setattr(budget, 'utcnow', lambda: datetime(2026, 11, 3, 0, 0))
    with pytest.raises(APIError) as exc:
        await budget.require_gemini_tts_request_budget()
    assert exc.value.status_code == 429
    async with TestSessionLocal() as check:
        rows = (await check.execute(select(GeminiTTSRequestBudget))).scalars().all()
        assert {row.bucket: row.requests for row in rows} == {'day:20261102': 1, 'month:202611': 1}


@pytest.mark.asyncio
async def test_korea_day_and_month_rollover(db_session, configured, monkeypatch):
    monkeypatch.setattr(budget, 'utcnow', lambda: datetime(2026, 11, 30, 14, 59))
    await budget.require_gemini_tts_request_budget()
    monkeypatch.setattr(budget, 'utcnow', lambda: datetime(2026, 11, 30, 15, 0))
    await budget.require_gemini_tts_request_budget()
    async with TestSessionLocal() as check:
        rows = (await check.execute(select(GeminiTTSRequestBudget))).scalars().all()
        assert {row.bucket for row in rows} == {'day:20261130', 'month:202611', 'day:20261201', 'month:202612'}


@pytest.mark.asyncio
async def test_unconfigured_and_unavailable_database_fail_closed(db_session, configured, monkeypatch):
    monkeypatch.setattr(budget.settings, 'google_gemini_tts_daily_request_limit', 0)
    with pytest.raises(APIError) as exc:
        await budget.require_gemini_tts_request_budget()
    assert exc.value.status_code == 503
    monkeypatch.setattr(budget.settings, 'google_gemini_tts_daily_request_limit', 2)
    def unavailable():
        raise OSError('unavailable')
    monkeypatch.setattr(budget, 'AsyncSessionLocal', unavailable)
    with pytest.raises(APIError) as exc:
        await budget.require_gemini_tts_request_budget()
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_budget_denial_prevents_provider_network_call(monkeypatch):
    from unittest.mock import AsyncMock
    import google.auth
    import httpx
    from src.services import tts

    class Credentials:
        token = 'synthetic-token'
        def refresh(self, request):
            return None

    def no_network(*args, **kwargs):
        raise AssertionError('Provider network client must not be created')

    monkeypatch.setattr(tts.settings, 'google_gemini_tts_project', 'synthetic-project')
    monkeypatch.setattr(google.auth, 'default', lambda **kwargs: (Credentials(), None))
    monkeypatch.setattr(httpx, 'AsyncClient', no_network)
    monkeypatch.setattr(tts, 'require_gemini_tts_request_budget', AsyncMock(side_effect=APIError(
        status_code=429, error_code='SERVICE_BUDGET_EXCEEDED', message='limit')))
    with pytest.raises(APIError) as exc:
        await tts.GeminiCloudTTSProvider().synthesize('토끼가 숲을 걸었어요.', 'Kore')
    assert exc.value.status_code == 429
