"""Regression evidence for the two independent September launch audits."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import uuid
import pytest
from sqlalchemy import select, func
from src.core.config import settings
from src.core.rate_limit import RateLimiter
from src.models.db import AccountIdentity, CreditTransaction, Job, UserConsent, UserCredits
from src.models.dto import BookSpec, CharacterSpec, SeriesNextRequest
from src.services.credits import CreditsService

@pytest.mark.asyncio
async def test_default_eight_minute_polling_does_not_exhaust_writes(monkeypatch):
    from tests.fake_redis import FakeRedis
    from src.core import rate_limit
    limiter, fake = RateLimiter(), FakeRedis()
    monkeypatch.setattr(limiter, 'get_redis', AsyncMock(return_value=fake))
    clock = [datetime(2026, 9, 7)]
    monkeypatch.setattr(rate_limit, 'utcnow', lambda: clock[0])
    assert (await limiter.is_allowed('owner')).allowed
    for i in range(241):
        clock[0] = datetime(2026, 9, 7) + timedelta(seconds=i * 2)
        assert (await limiter.is_allowed('owner', bucket='read')).allowed
    assert (await limiter.is_allowed('owner')).allowed

@pytest.mark.asyncio
async def test_new_free_account_two_once_and_no_midmonth_reissue(db_session, monkeypatch):
    import src.services.credits as module
    monkeypatch.setattr(module, 'utcnow', lambda: datetime(2026, 9, 7))
    service = CreditsService()
    assert await service.get_credits(db_session, 'monthly') == 2
    assert await service.get_credits(db_session, 'monthly') == 2
    assert await service.use_credit(db_session, 'monthly', 2)
    assert await service.get_credits(db_session, 'monthly') == 0
    assert (await db_session.execute(select(func.count(CreditTransaction.id)).where(
        CreditTransaction.transaction_type == 'free_monthly'))).scalar() == 1

@pytest.mark.asyncio
async def test_free_refill_korea_boundary_preserves_paid_balance(db_session, monkeypatch):
    import src.services.credits as module
    service, clock = CreditsService(), [datetime(2026, 9, 30, 14, 59)]
    monkeypatch.setattr(module, 'utcnow', lambda: clock[0])
    assert await service.get_credits(db_session, 'boundary') == 2
    assert await service.use_credit(db_session, 'boundary', 2)
    assert await service.get_credits(db_session, 'boundary') == 0
    clock[0] = datetime(2026, 9, 30, 15)
    assert await service.get_credits(db_session, 'boundary') == 2
    assert await service.add_credits(db_session, 'boundary', 10, reference_id='paid') == 12
    clock[0] = datetime(2026, 10, 31, 15)
    assert await service.get_credits(db_session, 'boundary') == 12


@pytest.mark.asyncio
async def test_first_book_trial_does_not_refill_and_failed_book_can_retry(db_session, monkeypatch):
    import src.services.credits as module
    service, clock = CreditsService(), [datetime(2026, 9, 30, 14, 59)]
    monkeypatch.setattr(settings, 'free_plan_first_book_trial', True)
    monkeypatch.setattr(module, 'utcnow', lambda: clock[0])
    assert await service.get_credits(db_session, 'trial') == 1
    assert await service.use_credit(db_session, 'trial', reference_id='job_trial_fail')
    assert not await service.use_credit(db_session, 'trial', reference_id='job_trial_blocked')
    assert await service.refund_for_job(db_session, 'trial', 'job_trial_fail')
    assert not await service.refund_for_job(db_session, 'trial', 'job_trial_fail')
    assert await service.use_credit(db_session, 'trial', reference_id='job_trial_success')
    clock[0] += timedelta(days=32)
    assert await service.get_credits(db_session, 'trial') == 0
    assert await db_session.scalar(select(func.count(CreditTransaction.id)).where(
        CreditTransaction.user_key == 'trial', CreditTransaction.reference_id == 'first_book_trial:v1')) == 1


@pytest.mark.asyncio
async def test_first_book_trial_preserves_existing_and_restored_ledgers(db_session, monkeypatch):
    monkeypatch.setattr(settings, 'free_plan_first_book_trial', True)
    db_session.add(UserCredits(user_key='existing', credits=7, total_purchased=7, total_used=0))
    db_session.add(CreditTransaction(user_key='restored-ledger', amount=1, balance_after=1,
                                    transaction_type='bonus', reference_id='first_book_trial:v1'))
    await db_session.commit()
    service = CreditsService()
    assert await service.get_credits(db_session, 'existing') == 7
    assert await service.get_credits(db_session, 'restored-ledger') == 0


@pytest.mark.asyncio
async def test_first_book_trial_blocks_unfunded_creation_then_accepts_paid_balance(
    client, headers, valid_book_spec, db_session, monkeypatch,
):
    from src.routers import books
    monkeypatch.setattr(settings, 'free_plan_first_book_trial', True)
    monkeypatch.setattr(settings, 'free_plan_enforce_in_testing', True)
    service = CreditsService()
    monkeypatch.setattr(books, 'credits_service', service)
    spec = {**valid_book_spec, 'style': 'watercolor'}
    capability = await client.get('/v1/config/capabilities')
    assert capability.json()['free_first_book_trial'] is True
    first = await client.post('/v1/books', headers={**headers, 'X-Idempotency-Key': 'first-trial-book'}, json=spec)
    assert first.status_code == 200, first.text
    retry = await client.post('/v1/books', headers={**headers, 'X-Idempotency-Key': 'first-trial-book'}, json=spec)
    assert retry.status_code == 200 and retry.json()['job_id'] == first.json()['job_id']
    second = await client.post('/v1/books', headers={**headers, 'X-Idempotency-Key': 'second-trial-book'}, json=spec)
    assert second.status_code == 402, second.text
    status = (await client.get('/v1/credits/status', headers=headers)).json()
    assert status['credits']['credits'] == 0
    assert next(plan for plan in status['available_plans'] if plan['id'] == 'free')['credits_per_month'] == 0
    await service.add_credits(db_session, headers['X-User-Key'], 2,
                              transaction_type='purchase', reference_id='trial-test-purchase')
    for key in ('funded-book-2', 'funded-book-3'):
        response = await client.post('/v1/books', headers={**headers, 'X-Idempotency-Key': key}, json=spec)
        assert response.status_code == 200, response.text

@pytest.mark.asyncio
async def test_legacy_spending_and_explicit_free_subscription_do_not_double_grant(db_session):
    from src.core.utils import utcnow
    db_session.add(UserCredits(user_key='legacy', credits=1, total_used=2))
    db_session.add(CreditTransaction(user_key='legacy', amount=-2, balance_after=1,
                                    transaction_type='usage', created_at=utcnow()))
    await db_session.commit()
    service = CreditsService()
    assert await service.get_credits(db_session, 'legacy') == 1
    assert await service.get_credits(db_session, 'free-sub') == 2
    await service.create_subscription(db_session, 'free-sub', 'free')
    assert await service.get_credits(db_session, 'free-sub') == 2

@pytest.mark.asyncio
async def test_deleted_legacy_key_cannot_recreate_credit_or_profile(client, db_session, headers, user_key):
    await CreditsService().get_credits(db_session, user_key)
    deleted = await client.delete('/v1/users/me', headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()['account_deleted']
    for method, path in [('get', '/v1/credits/balance'), ('delete', '/v1/users/me')]:
        response = await getattr(client, method)(path, headers=headers)
        assert response.status_code == 401, response.text
        assert response.json()['error']['code'] == 'ACCOUNT_DELETED'
    identity = await db_session.get(AccountIdentity, user_key)
    assert identity.deleted and identity.device_key_hash
    assert await db_session.get(UserCredits, user_key) is None

@pytest.mark.asyncio
@pytest.mark.parametrize('path,body', [
    ('/v1/books', {'topic': '숲속 친구', 'target_age': '7-9', 'style': 'watercolor', 'page_count': 12}),
    ('/v1/profiles', {'name': '테스트'}),
])
async def test_baseline_consent_before_nonphoto_creation(client, db_session, headers, monkeypatch, path, body):
    monkeypatch.setattr(settings, 'require_parental_consent_in_testing', True)
    response = await client.post(path, headers=headers, json=body)
    assert response.status_code == 403, response.text
    assert response.json()['error']['code'] == 'PARENTAL_CONSENT_REQUIRED'
    assert (await db_session.execute(select(func.count(Job.id)))).scalar() == 0
    assert (await db_session.execute(select(func.count(CreditTransaction.id)))).scalar() == 0

@pytest.mark.asyncio
async def test_latest_denial_overrides_older_grant(db_session, monkeypatch):
    from src.core.consent import require_parental_consent
    from src.core.exceptions import APIError
    monkeypatch.setattr(settings, 'require_parental_consent_in_testing', True)
    db_session.add(UserConsent(user_key='consent', privacy=True, data_processing=True, granted=True,
                               created_at=datetime(2026, 1, 1)))
    db_session.add(UserConsent(user_key='consent', privacy=False, data_processing=False, granted=False,
                               created_at=datetime(2026, 1, 2)))
    await db_session.commit()
    with pytest.raises(APIError) as error:
        await require_parental_consent(db_session, 'consent')
    assert error.value.error_code == 'PARENTAL_CONSENT_REQUIRED'

@pytest.mark.parametrize('model,body', [
    (BookSpec, {'topic': ' \n\t ', 'target_age': '7-9', 'style': 'watercolor'}),
    (BookSpec, {'topic': 'hello', 'protagonist_name': '   ', 'target_age': '7-9', 'style': 'watercolor'}),
    (CharacterSpec, {'name': ' \t '}),
    (SeriesNextRequest, {'topic': '   ', 'character_id': 'char_1'}),
])
def test_whitespace_rejected_before_minimum_length(model, body):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        model.model_validate(body)

@pytest.mark.asyncio
async def test_validation_does_not_echo_child_payload_or_unknown_keys(client, headers):
    secret = 'PRIVATE_CHILD_PHOTO_' + 'x' * 90000
    response = await client.post('/v1/books', headers=headers, json={'topic': secret, secret: secret})
    assert response.status_code == 422
    assert 'PRIVATE_CHILD_PHOTO_' not in response.text
    assert len(response.content) < 10000
    for item in response.json()['error']['details']:
        assert set(item) == {'type', 'loc', 'msg'}

@pytest.mark.asyncio
async def test_rename_preserves_avatar_denies_other_owner(client, db_session, headers, user_key):
    from src.models.db import Character
    character = Character(id='char_rename', user_key=user_key, name='캐릭터',
                          from_photo=True, avatar_status='approved', avatar_version=2,
                          master_description='unchanged illustrated identity', appearance={}, clothing={},
                          personality_traits=['kind'], visual_style_notes='watercolor')
    db_session.add(character)
    await db_session.commit()
    response = await client.patch('/v1/characters/char_rename', headers=headers, json={'name': '  테스트  '})
    assert response.status_code == 200, response.text
    await db_session.refresh(character)
    assert character.name == '테스트' and character.avatar_version == 2 and character.avatar_status == 'approved'
    other = {'X-User-Key': str(uuid.uuid4())}
    assert (await client.patch('/v1/characters/char_rename', headers=other, json={'name': 'Other'})).status_code == 404
    assert (await client.patch('/v1/characters/char_rename', headers=headers, json={'name': '   '})).status_code == 422

@pytest.mark.asyncio
async def test_photo_content_erasure_keeps_monthly_usage_without_child_payload(db_session):
    from src.routers.books import _count_monthly_book_creations
    from src.core.utils import utcnow
    # Original Job/Book/character have already been purged; only opaque billing references remain.
    for ref in ['job_erased1', 'job_erased2', 'regen_ignored', 'job_refunded']:
        db_session.add(CreditTransaction(user_key='erased', amount=-1, balance_after=0,
            transaction_type='usage', reference_id=ref, created_at=utcnow()))
    db_session.add(CreditTransaction(user_key='erased', amount=1, balance_after=1,
        transaction_type='refund', reference_id='job_refunded'))
    await db_session.commit()
    assert await _count_monthly_book_creations(db_session, 'erased') == 2

@pytest.mark.asyncio
@pytest.mark.parametrize('ledger,expected', [([], 'not_charged'), (['usage'], 'pending'), (['usage','refund'], 'refunded')])
async def test_failed_job_refund_status_comes_from_ledger(client, db_session, headers, user_key, ledger, expected):
    db_session.add(Job(id='job_refund_status', user_key=user_key, status='failed', progress=20,
                       current_step='실패', error_code='UNKNOWN'))
    for kind in ledger:
        db_session.add(CreditTransaction(user_key=user_key, amount=-1 if kind=='usage' else 1,
            balance_after=1, transaction_type=kind, reference_id='job_refund_status'))
    await db_session.commit()
    response = await client.get('/v1/books/job_refund_status', headers=headers)
    assert response.status_code == 200
    assert response.json()['credit_refund_status'] == expected

@pytest.mark.asyncio
async def test_slow_storage_acknowledges_committed_account_deletion(client, headers, monkeypatch):
    import asyncio
    from src.routers import users
    async def slow_purge(db, tasks):
        await asyncio.sleep(10)
        return []
    monkeypatch.setattr(users, 'run_purge_tasks', slow_purge)
    monkeypatch.setattr(users, '_INLINE_PURGE_TIMEOUT_SECONDS', 0.01)
    response = await client.delete('/v1/users/me', headers=headers)
    assert response.status_code == 200
    assert response.json()['account_deleted'] is True
    # A delayed client can resolve the same deletion without guessing from 400/timeout.
    retry = await client.delete('/v1/users/me', headers=headers)
    assert retry.status_code == 401 and retry.json()['error']['code'] == 'ACCOUNT_DELETED'
