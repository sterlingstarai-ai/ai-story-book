"""External backup authorization, private output, and failure cleanup with inert providers."""

import importlib.util
import io
import json
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def backup(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('external_backup_test_module', ROOT / 'scripts/backup_external.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def values():
    return {'DATABASE_URL': 'postgresql+asyncpg://postgres.project:private%40secret@aws-0.pooler.supabase.com:5432/postgres',
            'DATABASE_SSL_MODE': 'verify-full', 'DATABASE_SSL_ROOT_CERT': '/container/provider.crt',
            'S3_ENDPOINT': 'https://project.storage.supabase.co/storage/v1/s3', 'S3_REGION': 'ap-northeast-2',
            'S3_ADDRESSING_STYLE': 'path', 'S3_AUTO_CREATE_BUCKET': 'false', 'S3_BUCKET': 'storybook',
            'S3_ACCESS_KEY': 'synthetic-access', 'S3_SECRET_KEY': 'synthetic-secret',
            'API_IMAGE': 'ghcr.io/repo/api:' + 'a' * 40, 'WORKER_IMAGE': 'ghcr.io/repo/worker:' + 'a' * 40}


def env_file(tmp_path, values):
    path = tmp_path / 'private.env'
    path.write_text('\n'.join(f"{key}='{value}'" for key, value in values.items()))
    return path


def test_default_dry_run_never_connects_writes_or_executes_dotenv(backup, monkeypatch, tmp_path, values, capsys):
    marker = tmp_path / 'must-not-exist'
    values['S3_SECRET_KEY'] = f'$(touch {marker})'
    create = Mock(side_effect=AssertionError('Dry run must not execute'))
    monkeypatch.setattr(backup, 'create_backup', create)
    assert backup.main(['--env-file', str(env_file(tmp_path, values)), '--output-dir', str(tmp_path / 'output')]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)['status'] == 'DRY_RUN'
    assert 'private%40secret' not in output and '$(touch' not in output
    assert not marker.exists() and not (tmp_path / 'output').exists()
    create.assert_not_called()


def test_execute_requires_quiescence_encrypted_destination_and_ca(backup, monkeypatch, tmp_path, values):
    create = Mock()
    monkeypatch.setattr(backup, 'create_backup', create)
    assert backup.main(['--env-file', str(env_file(tmp_path, values)), '--output-dir', str(tmp_path / 'output'), '--execute']) == 1
    create.assert_not_called()
    assert not (tmp_path / 'output').exists()


def test_database_password_is_only_in_child_environment(backup, monkeypatch, values, tmp_path):
    env = backup.database_environment(values, tmp_path / 'provider.crt')
    assert env['PGPASSWORD'] == 'private@secret'
    assert env['PGSSLMODE'] == 'verify-full'
    assert 'DATABASE_URL' not in env
    process = Mock(return_value=Mock(stdout=b'0'))
    monkeypatch.setattr(backup.subprocess, 'run', process)
    backup.run_pg(['pg_dump', '--format=custom'], env)
    assert 'secret' not in str(process.call_args.args)
    assert process.call_args.kwargs['env']['PGPASSWORD'] == 'private@secret'
    assert process.call_args.kwargs['stderr'] == backup.subprocess.PIPE


def test_required_channel_binding_reaches_libpq(backup, values, tmp_path):
    values['DATABASE_URL'] = 'postgresql+psycopg://user:pass@db.invalid/storybook?sslmode=verify-full&channel_binding=require'
    env = backup.database_environment(values, tmp_path / 'ca.crt')
    assert env['PGCHANNELBINDING'] == 'require'
    values['DATABASE_URL'] += '&channel_binding=disable'
    with pytest.raises(backup.BackupError):
        backup.database_environment(values, tmp_path / 'ca.crt')


def test_fenced_backup_rejects_db_endpoint_overrides_and_unrelated_fence(backup, values, tmp_path, monkeypatch):
    ca = tmp_path / 'ca.crt'
    ca.touch()
    fence = Mock(environment={'PGHOST': 'other.example'})
    run_pg = Mock()
    monkeypatch.setattr(backup, 'run_pg', run_pg)
    with pytest.raises(backup.BackupError, match='identities differ'):
        backup.create_backup(values, tmp_path / 'backup', ca, fence=fence)
    values['DATABASE_URL'] += '?hostaddr=192.0.2.1'
    with pytest.raises(backup.BackupError, match='connection options'):
        backup.database_environment(values, ca)
    run_pg.assert_not_called()


@pytest.fixture
def inert_backup(backup, monkeypatch, values, tmp_path):
    commands = []
    def run(command, environment, *, destination=None):
        commands.append(command)
        assert 'private@secret' not in str(command)
        if command[0] == 'pg_dump':
            if '--version' in command:
                return b'pg_dump (PostgreSQL) 16.11\n'
            destination.write(b'synthetic-db-dump')
        if command[:2] == ['pg_restore', '--version']:
            return b'pg_restore (PostgreSQL) 16.11\n'
        if 'server_version_num' in command[-1]:
            return b'160009\n'
        if 'txid_current_snapshot' in command[-1]:
            return b'100:100:\n'
        if 'SELECT CASE' in command[-1]:
            return b'idle\n'
        if 'version_num' in command[-1]:
            return b'fixture_revision\n'
        return b''
    monkeypatch.setattr(backup, 'run_pg', run)
    client = Mock()
    client.get_paginator.return_value.paginate.return_value = [{'IsTruncated': False, 'Contents': [
        {'Key': '../../escape.png', 'ETag': 'etag', 'Size': 5, 'LastModified': '2026-11-03T13:15:06Z'}]}]
    client.get_object.side_effect = lambda **kwargs: {'Body': io.BytesIO(b'image'), 'ContentLength': 5,
        'ETag': 'etag', 'LastModified': '2026-11-03T13:15:06Z',
        'ContentType': 'image/png', 'Metadata': {'fixture': 'yes'}}
    monkeypatch.setattr(backup, 'storage_client', lambda _: client)
    ca = tmp_path / 'ca.crt'
    ca.write_text('mock certificate, never used for an actual connection')
    return backup, values, tmp_path / 'backup', ca, client, commands


def test_complete_set_preserves_media_metadata_and_never_traverses_remote_keys(inert_backup):
    backup, values, destination, ca, client, commands = inert_backup
    result = backup.create_backup(values, destination, ca)
    assert result['status'] == 'BACKUP_CREATED_NOT_RESTORE_VERIFIED'
    folder = destination / result['backup_set']
    manifest = json.loads((folder / 'manifest.json').read_text())
    obj = manifest['objects'][0]
    assert obj['key'] == '../../escape.png'
    assert (folder / obj['file']).read_bytes() == b'image'
    assert obj['metadata'] == {'fixture': 'yes'}
    assert obj['content_type'] == 'image/png'
    assert len(obj['sha256']) == 64
    assert manifest['restore_verified'] is False
    assert manifest['requires_latest_deletion_and_identity_revocations'] is True
    assert manifest['alembic_revision'] == 'fixture_revision'
    assert all(p.stat().st_mode & 0o077 == 0 for p in folder.rglob('*'))
    assert not (destination.parent / 'escape.png').exists()
    assert any('--schema=public' in command for command in commands)
    assert any(command[:2] == ['pg_restore', '--list'] for command in commands)
    client.get_object.assert_called_once_with(Bucket='storybook', Key='../../escape.png', IfMatch='etag')
    client.close.assert_called_once_with()


@pytest.mark.parametrize('truncated', [False, True])
def test_parallel_downloads_preserve_order_and_finish_before_cleanup(inert_backup, truncated):
    backup, values, destination, ca, client, _ = inert_backup
    stamp = '2026-11-03T13:15:06Z'
    client.get_paginator.return_value.paginate.return_value = [{'IsTruncated': False, 'Contents': [
        {'Key': key, 'ETag': key + '-etag', 'Size': 5, 'LastModified': stamp}
        for key in ('c', 'b', 'a')]}]
    first_pair = Barrier(2, timeout=5)
    closed = []

    class Body(io.BytesIO):
        def __init__(self, key):
            self.key = key
            super().__init__(b'i' if truncated and key == 'a' else b'image')

        def close(self):
            if not self.closed:
                closed.append(self.key)
            super().close()

    def get_object(*, Bucket, Key, IfMatch):
        assert Bucket == 'storybook' and IfMatch == Key + '-etag'
        if Key in ('a', 'b'):
            first_pair.wait()
        return {'Body': Body(Key), 'ContentLength': 5, 'ETag': IfMatch, 'LastModified': stamp}

    client.get_object.side_effect = get_object
    expected_keys = ['a', 'b'] if truncated else ['a', 'b', 'c']

    def close_client():
        assert sorted(closed) == expected_keys

    client.close.side_effect = close_client
    if truncated:
        with pytest.raises(backup.BackupError, match='truncated'):
            backup.create_backup(values, destination, ca, media_download_workers=2)
        assert not list(destination.iterdir())
    else:
        result = backup.create_backup(values, destination, ca, media_download_workers=2)
        manifest = json.loads((destination / result['backup_set'] / 'manifest.json').read_text())
        assert [entry['key'] for entry in manifest['objects']] == expected_keys
    client.close.assert_called_once_with()


@pytest.mark.parametrize('workers', [0, 3, True])
def test_invalid_worker_count_fails_before_source_reads(inert_backup, workers):
    backup, values, destination, ca, client, commands = inert_backup
    with pytest.raises(backup.BackupError, match='worker count'):
        backup.create_backup(values, destination, ca, media_download_workers=workers)
    assert not commands and not client.method_calls and not destination.exists()


@pytest.mark.parametrize('failure', ['download', 'changed_inventory', 'truncated', 'changed_download_identity'])
def test_failed_backup_removes_partial_set_and_keeps_old_backup(inert_backup, monkeypatch, failure):
    backup, values, destination, ca, client, _ = inert_backup
    destination.mkdir(mode=0o700)
    old = destination / 'old.dump'
    old.write_bytes(b'keep me')
    if failure == 'download':
        client.get_object.side_effect = RuntimeError('secret-provider-body')
    elif failure == 'truncated':
        client.get_object.side_effect = lambda **_: {'Body': io.BytesIO(b'x'), 'ContentLength': 5,
                                                     'ETag': 'etag', 'LastModified': '2026-11-03T13:15:06Z'}
    elif failure == 'changed_download_identity':
        client.get_object.side_effect = lambda **_: {'Body': io.BytesIO(b'image'), 'ContentLength': 5,
                                                     'ETag': 'new-etag', 'LastModified': '2026-11-03T13:15:06Z'}
    else:
        original = backup.inventory
        inventories = [original(client, values['S3_BUCKET']), {}]
        monkeypatch.setattr(backup, 'inventory', lambda *_: inventories.pop(0))
    with pytest.raises(Exception):
        backup.create_backup(values, destination, ca)
    assert list(destination.iterdir()) == [old]
    assert old.read_bytes() == b'keep me'


def test_active_jobs_block_before_object_reads(inert_backup, monkeypatch):
    backup, values, destination, ca, client, _ = inert_backup
    original = backup.run_pg
    monkeypatch.setattr(backup, 'run_pg', lambda cmd, env, **kwargs:
                        b'active_jobs\n' if 'SELECT CASE' in cmd[-1] else original(cmd, env, **kwargs))
    with pytest.raises(backup.BackupError, match='generation jobs remain'):
        backup.create_backup(values, destination, ca)
    client.get_paginator.assert_not_called()
    assert not destination.exists()


def test_unfinished_deletion_blocks_backup_before_storage_read(inert_backup, monkeypatch):
    backup, values, destination, ca, client, _ = inert_backup
    original = backup.run_pg
    monkeypatch.setattr(backup, 'run_pg', lambda cmd, env, **kwargs:
                        b'pending_purges\n' if 'SELECT CASE' in cmd[-1] else original(cmd, env, **kwargs))
    with pytest.raises(backup.BackupError, match='storage deletion tasks'):
        backup.create_backup(values, destination, ca)
    assert not destination.exists()
    client.get_paginator.assert_not_called()


def test_unpublished_privacy_event_blocks_before_storage_read(inert_backup, monkeypatch):
    backup, values, destination, ca, client, _ = inert_backup
    original = backup.run_pg
    monkeypatch.setattr(backup, 'run_pg', lambda cmd, env, **kwargs:
                        b'pending_journal\n' if 'SELECT CASE' in cmd[-1] else original(cmd, env, **kwargs))
    with pytest.raises(backup.BackupError, match='Unpublished privacy events'):
        backup.create_backup(values, destination, ca)
    assert not destination.exists()
    client.get_paginator.assert_not_called()


def test_deletion_arriving_during_backup_discards_partial_set(inert_backup, monkeypatch):
    backup, values, destination, ca, _, _ = inert_backup
    original = backup.run_pg
    calls = 0

    def run(command, environment, **kwargs):
        nonlocal calls
        if 'public.storage_purge_tasks' in command[-1]:
            calls += 1
            if calls == 2:
                return b'pending_purges\n'
        return original(command, environment, **kwargs)

    monkeypatch.setattr(backup, 'run_pg', run)
    with pytest.raises(backup.BackupError, match='storage deletion tasks'):
        backup.create_backup(values, destination, ca)
    assert list(destination.iterdir()) == []


def test_job_arriving_during_backup_discards_partial_set(inert_backup, monkeypatch):
    backup, values, destination, ca, _, _ = inert_backup
    original = backup.run_pg
    calls = 0

    def run(command, environment, **kwargs):
        nonlocal calls
        if 'public.jobs' in command[-1]:
            calls += 1
            if calls == 2:
                return b'active_jobs\n'
        return original(command, environment, **kwargs)

    monkeypatch.setattr(backup, 'run_pg', run)
    with pytest.raises(backup.BackupError, match='generation jobs remain'):
        backup.create_backup(values, destination, ca)
    assert list(destination.iterdir()) == []


def test_completed_transaction_during_backup_discards_partial_set(inert_backup, monkeypatch):
    backup, values, destination, ca, _, _ = inert_backup
    original = backup.run_pg
    snapshots = iter((b'100:100:\n', b'101:101:\n'))

    def run(command, environment, **kwargs):
        if 'txid_current_snapshot' in command[-1]:
            return next(snapshots)
        return original(command, environment, **kwargs)

    monkeypatch.setattr(backup, 'run_pg', run)
    with pytest.raises(backup.BackupError, match='transaction state changed'):
        backup.create_backup(values, destination, ca)
    assert list(destination.iterdir()) == []


def test_unreadable_transaction_snapshot_blocks_before_storage(inert_backup, monkeypatch):
    backup, values, destination, ca, client, _ = inert_backup
    original = backup.run_pg
    monkeypatch.setattr(backup, 'run_pg', lambda cmd, env, **kwargs:
                        b'' if 'txid_current_snapshot' in cmd[-1] else original(cmd, env, **kwargs))
    with pytest.raises(backup.BackupError, match='snapshot could not be verified'):
        backup.create_backup(values, destination, ca)
    client.get_paginator.assert_not_called()
    assert not destination.exists()


def test_backup_blocks_mismatched_pg_major_before_backup_or_storage(inert_backup, monkeypatch):
    backup, values, destination, ca, client, _ = inert_backup
    original = backup.run_pg
    monkeypatch.setattr(backup, 'run_pg', lambda cmd, env, **kwargs:
                        b'pg_dump (PostgreSQL) 18.3\n' if cmd == ['pg_dump', '--version']
                        else original(cmd, env, **kwargs))
    with pytest.raises(backup.BackupError, match='match the server major'):
        backup.create_backup(values, destination, ca)
    assert not destination.exists()
    client.get_paginator.assert_not_called()


@pytest.fixture
def online_inputs(inert_backup):
    backup, values, destination, ca, client, commands = inert_backup
    snapshot = Mock(environment=backup.database_environment(values, ca),
                    cut_released=True, cut_elapsed_ms=25, snapshot_id='00000001-00000003-1')
    frozen = {'../../escape.png': {'ETag': 'etag', 'Size': '5',
                                  'LastModified': '2026-11-03T13:15:06Z'}}
    return backup, values, destination, ca, client, commands, snapshot, frozen


def test_online_backup_uses_the_released_snapshot_and_frozen_objects_only(online_inputs, monkeypatch):
    backup, values, destination, ca, client, commands, snapshot, frozen = online_inputs
    live_inventory = Mock(side_effect=AssertionError('A live inventory cannot replace the cut'))
    idle = Mock(side_effect=AssertionError('Post-cut writers must be allowed'))
    monkeypatch.setattr(backup, 'inventory', live_inventory)
    monkeypatch.setattr(backup, 'assert_quiescent', idle)
    result = backup.create_online_backup(values, destination, ca, snapshot=snapshot,
                                         frozen_inventory=frozen, frozen_revision='cut_revision')
    manifest = json.loads((destination / result['backup_set'] / 'manifest.json').read_text())
    assert manifest['format_version'] == 1 and manifest['capture_mode'] == 'online_snapshot'
    assert manifest['alembic_revision'] == 'cut_revision'
    assert manifest['requires_latest_deletion_and_identity_revocations'] is True
    assert result['capture_mode'] == 'online_snapshot'
    assert result['snapshot'] == manifest['snapshot']
    assert result['snapshot']['cut_elapsed_ms'] == 25 and result['snapshot']['cut_released'] is True
    assert snapshot.snapshot_id not in json.dumps(manifest)
    assert result['media_inventory_sha256'] == backup.inventory_fingerprint(frozen)
    dump = next(command for command in commands if command[0] == 'pg_dump' and '--version' not in command)
    assert dump[-2:] == ['--snapshot', snapshot.snapshot_id]
    assert snapshot.verify.call_count == 3
    client.get_paginator.assert_not_called()
    live_inventory.assert_not_called()
    idle.assert_not_called()
    assert not any('txid_current_snapshot' in command[-1] or 'version_num FROM' in command[-1]
                   for command in commands)


@pytest.mark.parametrize('failure', ['deleted', 'changed_identity', 'truncated', 'lost_snapshot'])
def test_online_capture_failure_removes_only_its_partial_set(online_inputs, failure):
    backup, values, destination, ca, client, _commands, snapshot, frozen = online_inputs
    destination.mkdir(mode=0o700)
    original = destination / 'existing-backup'
    original.write_bytes(b'preserve previous verified backup')
    if failure == 'deleted':
        client.get_object.side_effect = RuntimeError('private provider detail')
    elif failure == 'changed_identity':
        client.get_object.side_effect = lambda **_: {'Body': io.BytesIO(b'image'), 'ContentLength': 5,
            'ETag': 'different', 'LastModified': '2026-11-03T13:15:06Z'}
    elif failure == 'truncated':
        client.get_object.side_effect = lambda **_: {'Body': io.BytesIO(b'i'), 'ContentLength': 5,
            'ETag': 'etag', 'LastModified': '2026-11-03T13:15:06Z'}
    else:
        snapshot.verify.side_effect = [None, None, RuntimeError('fixture snapshot connection lost')]
    with pytest.raises(Exception):
        backup.create_online_backup(values, destination, ca, snapshot=snapshot,
                                    frozen_inventory=frozen, frozen_revision='cut_revision')
    assert list(destination.iterdir()) == [original]
    assert original.read_bytes() == b'preserve previous verified backup'
    client.get_paginator.assert_not_called()


@pytest.mark.parametrize('attribute,value', [('cut_released', False), ('cut_elapsed_ms', True),
                                          ('cut_elapsed_ms', -1), ('cut_elapsed_ms', 2001),
                                          ('snapshot_id', 'invalid snapshot'),
                                          ('environment', {'PGHOST': 'different.invalid'})])
def test_online_backup_rejects_an_unbound_or_unreleased_snapshot_before_reads(online_inputs, attribute, value):
    backup, values, destination, ca, client, commands, snapshot, frozen = online_inputs
    setattr(snapshot, attribute, value)
    with pytest.raises(backup.BackupError, match='released database cut'):
        backup.create_online_backup(values, destination, ca, snapshot=snapshot,
                                    frozen_inventory=frozen, frozen_revision='cut_revision')
    assert not destination.exists() and not commands and not client.method_calls


@pytest.mark.parametrize('bad_inventory', [None, {'key': {}}, {'key': {'ETag': '', 'Size': '1', 'LastModified': 'bad'}},
    {'key': {'ETag': 'e', 'Size': '-1', 'LastModified': '2026-11-03T13:15:06Z'}},
    {'key': {'ETag': 'e', 'Size': '1', 'LastModified': '2026-11-03T13:15:06Z', 'unknown': 'x'}}])
def test_online_backup_requires_a_complete_frozen_inventory(online_inputs, bad_inventory):
    backup, values, destination, ca, client, commands, snapshot, _frozen = online_inputs
    with pytest.raises(backup.BackupError, match='inventory'):
        backup.create_online_backup(values, destination, ca, snapshot=snapshot,
                                    frozen_inventory=bad_inventory, frozen_revision='cut_revision')
    assert not destination.exists() and not commands and not client.method_calls


@pytest.mark.parametrize('version_matches', [True, False])
def test_online_native_media_pins_generation_and_keeps_client_ownership(online_inputs, version_matches):
    backup, values, destination, ca, client, _commands, snapshot, frozen = online_inputs
    expected = frozen['../../escape.png']
    expected.update(generation='1000', metageneration='2')
    closed = []

    class Body(io.BytesIO):
        def close(self):
            closed.append(True)
            super().close()

    client.get_object.side_effect = lambda **_: {
        'Body': Body(b'image'), 'ContentLength': 5, 'ETag': 'etag',
        'LastModified': expected['LastModified'], 'Generation': '1000',
        'Metageneration': '2' if version_matches else '3'}
    arguments = dict(snapshot=snapshot, frozen_inventory=frozen, frozen_revision='cut_revision',
                     media_client=client)
    if version_matches:
        backup.create_online_backup(values, destination, ca, **arguments)
    else:
        with pytest.raises(backup.BackupError, match='version changed'):
            backup.create_online_backup(values, destination, ca, **arguments)
        assert not list(destination.iterdir())
    client.get_object.assert_called_once_with(Bucket='storybook', Key='../../escape.png', IfMatch='etag',
                                               Generation='1000', Metageneration='2')
    assert closed == [True]
    client.close.assert_not_called()


@pytest.mark.parametrize('cut_timeout', [None, 2.0])
def test_storage_client_keeps_default_limits_and_bounds_cut_requests(backup, monkeypatch, values, cut_timeout):
    import boto3

    factory = Mock()
    monkeypatch.setattr(boto3, 'client', factory)
    backup.storage_client(values, cut_timeout_seconds=cut_timeout)
    configuration = factory.call_args.kwargs['config']
    if cut_timeout is None:
        assert configuration.connect_timeout == 15 and configuration.read_timeout == 60
        assert configuration.retries == {'max_attempts': 2, 'mode': 'standard'}
    else:
        assert configuration.connect_timeout < cut_timeout / 2
        assert configuration.read_timeout < cut_timeout / 2
        assert configuration.retries == {'total_max_attempts': 1, 'mode': 'standard'}
