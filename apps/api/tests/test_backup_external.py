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


@pytest.fixture
def inert_backup(backup, monkeypatch, values, tmp_path):
    commands = []
    def run(command, environment, *, destination=None):
        commands.append(command)
        assert 'private@secret' not in str(command)
        if command[0] == 'pg_dump':
            destination.write(b'synthetic-db-dump')
        if 'SELECT count' in command[-1]:
            return b'0\n'
        if 'version_num' in command[-1]:
            return b'fixture_revision\n'
        return b''
    monkeypatch.setattr(backup, 'run_pg', run)
    client = Mock()
    client.get_paginator.return_value.paginate.return_value = [{'Contents': [
        {'Key': '../../escape.png', 'ETag': 'etag', 'Size': 5, 'LastModified': 'fixture-time'}]}]
    client.get_object.side_effect = lambda **kwargs: {'Body': io.BytesIO(b'image'), 'ContentLength': 5,
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


@pytest.mark.parametrize('failure', ['download', 'changed_inventory', 'truncated'])
def test_failed_backup_removes_partial_set_and_keeps_old_backup(inert_backup, monkeypatch, failure):
    backup, values, destination, ca, client, _ = inert_backup
    destination.mkdir(mode=0o700)
    old = destination / 'old.dump'
    old.write_bytes(b'keep me')
    if failure == 'download':
        client.get_object.side_effect = RuntimeError('secret-provider-body')
    elif failure == 'truncated':
        client.get_object.side_effect = lambda **_: {'Body': io.BytesIO(b'x'), 'ContentLength': 5}
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
    monkeypatch.setattr(backup, 'run_pg', lambda *_: b'1\n')
    with pytest.raises(backup.BackupError, match='generation jobs remain'):
        backup.create_backup(values, destination, ca)
    client.get_paginator.assert_not_called()
    assert not destination.exists()
