"""Synthetic opaque media scopes never expose the account credential."""

import hashlib
import os

import pytest

from src.core.config import settings
from src.services.account_scope import AccountScopeUnavailable, derive_account_scope

pytestmark = pytest.mark.asyncio


def configure(monkeypatch, tmp_path, *, key=b'k' * 32):
    path = tmp_path / 'scope.key'
    path.write_bytes(key)
    path.chmod(0o600)
    monkeypatch.setattr(settings, 'account_scope_key_file', str(path))
    monkeypatch.setattr(settings, 'account_scope_key_sha256', hashlib.sha256(key).hexdigest())
    monkeypatch.setattr(settings, 'account_scope_namespace', 'synthetic-pilot')
    return path


async def test_scope_is_stable_across_device_recovery_and_denied_after_deletion(client, headers, monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    async def deleted(_):
        return []
    monkeypatch.setattr('src.services.purge_queue._execute_task', deleted)
    original = await client.get('/v1/account/media-scope', headers=headers)
    assert original.status_code == 200 and original.headers['cache-control'] == 'private, no-store'
    scope = original.json()['scope_id']
    assert original.json()['version'] == 1 and len(scope) == 64
    assert headers['X-User-Key'] not in original.text and 'kkkk' not in original.text
    code = (await client.post('/v1/account/recovery-code', headers=headers)).json()['recovery_code']
    device = 'asb_device_' + 'D' * 43
    assert (await client.post('/v1/account/recover', json={'recovery_code': code, 'new_user_key': device})).status_code == 200
    assert (await client.get('/v1/account/media-scope', headers=headers)).status_code == 401
    recovered = {'X-User-Key': device}
    assert (await client.get('/v1/account/media-scope', headers=recovered)).json()['scope_id'] == scope
    other = {'X-User-Key': '00000000-0000-4000-8000-000000000099'}
    assert (await client.get('/v1/account/media-scope', headers=other)).json()['scope_id'] != scope
    assert (await client.delete('/v1/users/me', headers=recovered)).status_code == 200
    assert (await client.get('/v1/account/media-scope', headers=recovered)).status_code == 401


async def test_absent_or_changed_scope_key_does_not_block_existing_session(client, headers, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'account_scope_key_file', '')
    monkeypatch.setattr(settings, 'account_scope_key_sha256', '')
    monkeypatch.setattr(settings, 'account_scope_namespace', '')
    assert (await client.get('/v1/account/media-scope', headers=headers)).status_code == 503
    assert (await client.get('/v1/account/session', headers=headers)).status_code == 200
    key = configure(monkeypatch, tmp_path)
    key.write_bytes(b'x' * 32)
    failure = await client.get('/v1/account/media-scope', headers=headers)
    assert failure.status_code == 503 and 'xxxxxxxx' not in failure.text
    assert (await client.get('/v1/account/session', headers=headers)).status_code == 200


async def test_scope_rejects_insecure_or_symlinked_key_and_invalid_namespace(client, headers, monkeypatch, tmp_path):
    path = configure(monkeypatch, tmp_path)
    path.chmod(0o644)
    assert (await client.get('/v1/account/media-scope', headers=headers)).status_code == 503
    path.chmod(0o600)
    link = tmp_path / 'link'
    link.symlink_to(path)
    monkeypatch.setattr(settings, 'account_scope_key_file', str(link))
    assert (await client.get('/v1/account/media-scope', headers=headers)).status_code == 503
    monkeypatch.setattr(settings, 'account_scope_key_file', str(path))
    monkeypatch.setattr(settings, 'account_scope_namespace', 'invalid namespace')
    assert (await client.get('/v1/account/media-scope', headers=headers)).status_code == 503


async def test_scope_rejects_non_regular_key_without_waiting(client, headers, monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    fifo = tmp_path / 'scope-pipe'
    os.mkfifo(fifo, 0o600)
    monkeypatch.setattr(settings, 'account_scope_key_file', str(fifo))
    import asyncio
    result = await asyncio.wait_for(client.get('/v1/account/media-scope', headers=headers), timeout=2)
    assert result.status_code == 503


async def test_scope_is_deployment_separated_and_repeatable(monkeypatch, tmp_path):
    path = configure(monkeypatch, tmp_path)
    owner = '00000000-0000-4000-8000-000000000011'
    pin = hashlib.sha256(b'k' * 32).hexdigest()
    kwargs = {'owner': owner, 'key_path': str(path), 'expected_sha256': pin}
    first = derive_account_scope(namespace='server-a', **kwargs)
    assert first == derive_account_scope(namespace='server-a', **kwargs)
    assert first != derive_account_scope(namespace='server-b', **kwargs)
    with pytest.raises(AccountScopeUnavailable):
        derive_account_scope(namespace='server-a', **{**kwargs, 'expected_sha256': '0' * 64})
