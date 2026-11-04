"""External backup authorization, private output, and failure cleanup with inert providers."""

import importlib.util
import io
import json
from pathlib import Path
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
