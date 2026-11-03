"""Book deletion receipts bind a committed deletion to account and profile."""

import pytest
from sqlalchemy import select

from src.models.db import Book, BookDeletionReceipt, ChildProfile
from src.services.privacy_journal import PrivacyJournal
from src.services.privacy_journal_verify import verify_current_outbox
from tests.factories import make_book_rows
from tests.test_privacy_journal_transaction import Store

pytestmark = pytest.mark.asyncio
REQUEST = 'a' * 32
OTHER_REQUEST = 'b' * 32


async def seed(db, owner, *, book='receipt-book', profile='profile-a'):
    db.add_all(make_book_rows([(book, owner)]))
    db.add(ChildProfile(id=profile, user_key=owner, name='Synthetic'))
    await db.commit()


def req_headers(headers, request=REQUEST, profile='profile-a'):
    return {**headers, 'X-Deletion-Request-Id': request, 'X-Profile-Id': profile}


async def test_receipt_confirms_only_the_same_book_account_and_profile(client, db_session, headers, monkeypatch):
    owner = headers['X-User-Key']
    await seed(db_session, owner)
    db_session.add(ChildProfile(id='profile-b', user_key=owner, name='Synthetic B'))
    db_session.add_all(make_book_rows([('other-book', owner)]))
    await db_session.commit()
    async def deleted(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', deleted)
    scoped = req_headers(headers)
    result = await client.delete('/v1/library/receipt-book', headers=scoped)
    assert result.status_code == 200 and result.json()['deletion_committed'] is True
    receipt = await client.get('/v1/library/receipt-book/deletion-receipt', headers=scoped)
    assert receipt.status_code == 200
    assert receipt.json() == {'deletion_committed': True, 'storage_purge_status': 'unknown'}
    assert receipt.headers['cache-control'] == 'private, no-store'
    retried = await client.delete('/v1/library/receipt-book', headers=scoped)
    assert retried.status_code == 200 and retried.json()['storage_purge_status'] == 'unknown'
    assert (await client.get('/v1/library/receipt-book/deletion-receipt',
                             headers=req_headers(headers, profile='profile-b'))).status_code == 404
    assert (await client.get('/v1/library/other-book/deletion-receipt', headers=scoped)).status_code == 404
    assert (await client.get('/v1/library/receipt-book/deletion-receipt', headers={
        **req_headers(headers), 'X-User-Key': '00000000-0000-4000-8000-000000000099',
        'X-Profile-Id': '',
    })).status_code == 404
    conflict = await client.delete('/v1/library/other-book', headers=scoped)
    assert conflict.status_code == 409
    assert await db_session.get(Book, 'other-book') is not None


async def test_partial_storage_purge_never_claims_storage_completion(client, db_session, headers, monkeypatch):
    await seed(db_session, headers['X-User-Key'])
    async def failed(_):
        return ['synthetic']
    monkeypatch.setattr('src.services.purge_queue._execute_task', failed)
    scoped = req_headers(headers)
    result = await client.delete('/v1/library/receipt-book', headers=scoped)
    assert result.status_code == 200 and result.json()['purge_retry_pending'] is True
    assert result.json()['deletion_committed'] is True
    lookup = await client.get('/v1/library/receipt-book/deletion-receipt', headers=scoped)
    assert lookup.json() == {'deletion_committed': True, 'storage_purge_status': 'unknown'}


async def test_receipt_cannot_confirm_if_book_id_is_present_again(client, db_session, headers, monkeypatch):
    owner = headers['X-User-Key']
    await seed(db_session, owner)
    async def deleted(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', deleted)
    scoped = req_headers(headers)
    assert (await client.delete('/v1/library/receipt-book', headers=scoped)).status_code == 200
    db_session.add(Book(id='receipt-book', job_id='job-receipt-book', user_key=owner,
                        title='new', language='ko', target_age='5-7', style='watercolor'))
    await db_session.commit()
    assert (await client.get('/v1/library/receipt-book/deletion-receipt', headers=scoped)).status_code == 404
    assert (await client.delete('/v1/library/receipt-book', headers=scoped)).status_code == 409
    assert await db_session.get(Book, 'receipt-book') is not None


async def test_invalid_or_foreign_request_cannot_create_receipt(client, db_session, headers, monkeypatch):
    await seed(db_session, headers['X-User-Key'])
    assert (await client.delete('/v1/library/receipt-book', headers=req_headers(headers, request='bad'))).status_code == 400
    foreign = req_headers(headers)
    foreign['X-User-Key'] = '00000000-0000-4000-8000-000000000099'
    foreign.pop('X-Profile-Id')
    assert (await client.delete('/v1/library/receipt-book', headers=foreign)).status_code == 403
    assert await db_session.get(Book, 'receipt-book') is not None
    assert await db_session.scalar(select(BookDeletionReceipt.request_id)) is None


async def test_deleted_profile_removes_scoped_receipt(client, db_session, headers, monkeypatch):
    await seed(db_session, headers['X-User-Key'])
    async def deleted(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', deleted)
    scoped = req_headers(headers)
    assert (await client.delete('/v1/library/receipt-book', headers=scoped)).status_code == 200
    assert (await client.delete('/v1/profiles/profile-a', headers=headers)).status_code == 200
    assert await db_session.scalar(select(BookDeletionReceipt.request_id)) is None
    assert (await client.get('/v1/library/receipt-book/deletion-receipt', headers=scoped)).status_code != 200


async def test_recovered_device_can_confirm_but_account_deletion_erases_receipt(client, db_session, headers, monkeypatch):
    await seed(db_session, headers['X-User-Key'])
    async def deleted(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', deleted)
    code = (await client.post('/v1/account/recovery-code', headers=headers)).json()['recovery_code']
    scoped = req_headers(headers)
    assert (await client.delete('/v1/library/receipt-book', headers=scoped)).status_code == 200
    device = 'asb_device_' + 'D' * 43
    assert (await client.post('/v1/account/recover', json={'recovery_code': code, 'new_user_key': device})).status_code == 200
    assert (await client.get('/v1/library/receipt-book/deletion-receipt', headers=scoped)).status_code == 401
    recovered = req_headers({'X-User-Key': device})
    assert (await client.get('/v1/library/receipt-book/deletion-receipt', headers=recovered)).status_code == 200
    assert (await client.delete('/v1/users/me', headers={'X-User-Key': device})).status_code == 200
    assert await db_session.scalar(select(BookDeletionReceipt.request_id)) is None
    assert (await client.get('/v1/library/receipt-book/deletion-receipt', headers=recovered)).status_code == 401


async def test_journal_intent_failure_cannot_commit_book_or_receipt(client, db_session, headers, monkeypatch):
    await seed(db_session, headers['X-User-Key'])
    store = Store()
    store.fail_intent = True
    db_session.info['privacy_journal'] = PrivacyJournal(store, b'k' * 32)
    result = await client.delete('/v1/library/receipt-book', headers=req_headers(headers))
    assert result.status_code == 503
    assert await db_session.get(Book, 'receipt-book') is not None
    assert await db_session.scalar(select(BookDeletionReceipt.request_id)) is None


async def test_committed_receipt_is_bound_to_encrypted_privacy_event(client, db_session, headers, monkeypatch):
    await seed(db_session, headers['X-User-Key'])
    journal = PrivacyJournal(Store(), b'k' * 32)
    db_session.info['privacy_journal'] = journal
    async def deleted(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', deleted)
    result = await client.delete('/v1/library/receipt-book', headers=req_headers(headers))
    assert result.status_code == 200
    scan = journal.scan()
    event = scan.committed[0]
    assert event.deletion_receipt.request_id == REQUEST and event.deletion_receipt.profile_id == 'profile-a'
    assert (await verify_current_outbox(db_session, scan))['event_count'] == 1
