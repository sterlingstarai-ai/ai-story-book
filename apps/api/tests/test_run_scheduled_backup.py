"""Local fail-closed checks for the uninstalled scheduler runner."""

import importlib
import configparser
from collections import namedtuple
import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('run_scheduled_backup')


def test_dry_run_does_not_create_state_or_stop_services(module, tmp_path):
    state = tmp_path / 'state'
    assert module.main(['--state-dir', str(state)]) == 0
    assert not state.exists()


def test_mirrored_backup_source_is_bound_to_image_and_contents(module, monkeypatch, tmp_path):
    root = tmp_path / 'sources'
    monkeypatch.setattr(module, 'BACKUP_API_SOURCES', root)
    digest = 'a' * 64
    image = 'local-image@sha256:' + digest
    directory = root / digest
    source = directory / 'src' / 'fixture.py'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'fixture = True\n')
    hashes = {'src/fixture.py': hashlib.sha256(source.read_bytes()).hexdigest()}
    source_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for name, value in (('image-id', image), ('source-sha256', source_hash)):
        marker = directory / name
        marker.write_text(value + '\n')
        marker.chmod(0o600)
    assert module.backup_api_source(image, mirrored=True) == directory
    source.write_bytes(b'fixture = False\n')
    with pytest.raises(module.ScheduledBackupError, match='has changed'):
        module.backup_api_source(image, mirrored=True)


def test_private_file_refuses_loose_permissions_and_symlinks(module, tmp_path):
    path = tmp_path / 'key'
    path.write_bytes(b'k' * 32)
    path.chmod(0o644)
    with pytest.raises(module.ScheduledBackupError):
        module.private_file(path, max_bytes=32)
    path.chmod(0o600)
    assert module.private_file(path, max_bytes=32) == b'k' * 32
    link = tmp_path / 'link'
    link.symlink_to(path)
    with pytest.raises(OSError):
        module.private_file(link, max_bytes=32)


def test_backup_disk_headroom_checked_before_creating_destination(module, tmp_path, monkeypatch):
    destination = tmp_path / 'new' / 'backups'
    usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda path: usage(2000, 1000, 1000))
    module.require_backup_disk_headroom(destination, minimum_bytes=1000)
    assert not destination.exists()
    with pytest.raises(module.ScheduledBackupError, match='headroom'):
        module.require_backup_disk_headroom(destination, minimum_bytes=1001)
    with pytest.raises(module.ScheduledBackupError, match='absolute'):
        module.require_backup_disk_headroom(Path('relative'))
    dangling = tmp_path / 'dangling'
    dangling.symlink_to(tmp_path / 'missing')
    with pytest.raises(module.ScheduledBackupError):
        module.require_backup_disk_headroom(dangling / 'backups', minimum_bytes=1)


def test_low_disk_fails_before_stopping_services(module, tmp_path, monkeypatch):
    calls = []
    class Runtime:
        def __init__(self):
            calls.append('created')
        def stop(self, name):
            calls.append('stopped')
    monkeypatch.setattr(module, 'DockerRuntime', Runtime)
    def insufficient(_path):
        raise module.ScheduledBackupError('Insufficient backup disk headroom')
    monkeypatch.setattr(module, 'require_backup_disk_headroom', insufficient)
    result = module.main(['--execute', '--state-dir', str(tmp_path / 'state'),
        '--env-file', str(tmp_path / 'env'), '--ca-file', str(tmp_path / 'ca'),
        '--journal-key-file', str(tmp_path / 'key'), '--journal-bucket', 'journal',
        '--backup-bucket', 'backup', '--output-dir', str(tmp_path / 'backup')])
    assert result == 1
    assert calls == ['created']


def test_worker_drain_requires_one_consistent_idle_worker(module):
    class Runtime:
        def __init__(self, replies):
            self.replies = iter(replies)
        def _run(self, command, *, timeout):
            return next(self.replies)
    module.assert_idle_worker(Runtime(['{"worker-a":[]}', '{"worker-a":[]}', '{"worker-a":[]}']))
    for replies in (
        ['{"worker-a":[{}]}'],
        ['{}'],
        ['{"worker-a":[]}', '{"worker-b":[]}'],
        ['provider error'],
    ):
        with pytest.raises(module.ScheduledBackupError):
            module.assert_idle_worker(Runtime(replies))


def test_backup_requires_both_live_writers_to_match_journal_buckets(module):
    class Runtime:
        def __init__(self, replies):
            self.replies = iter(replies)
        def _run(self, command, *, timeout):
            return json.dumps(next(self.replies))

    primary = ['PRIVACY_JOURNAL_ENABLED=true', 'PRIVACY_JOURNAL_BUCKET=primary', 'SECRET=not-logged']
    mirrored = primary + ['PRIVACY_JOURNAL_WITNESS_BUCKET=witness']
    module.assert_runtime_journal_binding(Runtime([primary, primary]), 'primary', '')
    module.assert_runtime_journal_binding(Runtime([mirrored, mirrored]), 'primary', 'witness')
    for replies, witness in (([primary, mirrored], ''), ([mirrored, mirrored], ''),
                             ([primary + ['PRIVACY_JOURNAL_BUCKET=other'], primary], ''),
                             ([['PRIVACY_JOURNAL_ENABLED=false'], primary], '')):
        with pytest.raises(module.ScheduledBackupError):
            module.assert_runtime_journal_binding(Runtime(replies), 'primary', witness)

    for field in ('ENDPOINT', 'BUCKET', 'REGION', 'ACCESS_KEY', 'SECRET_KEY'):
        configured = primary + [f'PRIVACY_JOURNAL_WITNESS_S3_{field}=synthetic-secret']
        with pytest.raises(module.ScheduledBackupError) as failure:
            module.assert_runtime_journal_binding(Runtime([configured, configured]), 'primary', '')
        assert 'synthetic-secret' not in str(failure.value)


def test_backup_requires_both_writers_to_match_media(module):
    class Runtime:
        def __init__(self, replies):
            self.replies = iter(replies)

        def _run(self, command, *, timeout):
            return json.dumps(next(self.replies))

    values = {'S3_ENDPOINT': 'https://storage.googleapis.com', 'S3_BUCKET': 'test-bucket',
              'S3_REGION': 'test-region', 'S3_ACCESS_KEY': 'fixture-access', 'S3_SECRET_KEY': 'fixture-secret'}
    exact = [f'{key}={value}' for key, value in values.items()]
    module.assert_runtime_media_binding(Runtime([exact, exact]), values)
    for invalid in (exact[:-1], exact + ['S3_BUCKET=wrong'], exact[:-1] + ['S3_SECRET_KEY=different']):
        with pytest.raises(module.ScheduledBackupError) as failure:
            module.assert_runtime_media_binding(Runtime([exact, invalid]), values)
        assert 'fixture-secret' not in str(failure.value)


def test_backup_requires_s3_witness_and_credentials_to_match_both_writers(module):
    class Runtime:
        def __init__(self, replies):
            self.replies = iter(replies)
        def _run(self, command, *, timeout):
            return json.dumps(next(self.replies))

    primary = ['PRIVACY_JOURNAL_ENABLED=true', 'PRIVACY_JOURNAL_BUCKET=primary']
    values = {'PRIVACY_JOURNAL_WITNESS_S3_ENDPOINT': 'https://synthetic.invalid',
              'PRIVACY_JOURNAL_WITNESS_S3_BUCKET': 'witness', 'PRIVACY_JOURNAL_WITNESS_S3_REGION': 'us-east-1',
              'PRIVACY_JOURNAL_WITNESS_S3_ACCESS_KEY': 'fixture-access',
              'PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY': 'fixture-secret'}
    env = primary + [f'{key}={value}' for key, value in values.items()]
    module.assert_runtime_journal_binding(Runtime([env, env]), 'primary', '', values)
    bad = env.copy()
    bad[-1] = 'PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY=other-secret'
    with pytest.raises(module.ScheduledBackupError) as error:
        module.assert_runtime_journal_binding(Runtime([env, bad]), 'primary', '', values)
    assert 'secret' not in str(error.value)


def test_backup_builds_s3_witness_and_rejects_conflicting_configuration(module, monkeypatch):
    from src.services import privacy_journal_gcs, privacy_journal_runtime
    from src.services.privacy_journal_mirror import MirroredJournalStore
    from src.services.privacy_journal_s3 import S3ImmutableJournalStore
    class Primary:
        def close(self):
            pass
    class Client:
        def close(self):
            pass
    monkeypatch.setattr(privacy_journal_gcs, 'GCSImmutableStore', lambda _bucket: Primary())
    monkeypatch.setattr(privacy_journal_runtime.boto3, 'client', lambda *_args, **_kwargs: Client())
    values = {'PRIVACY_JOURNAL_WITNESS_S3_ENDPOINT': 'https://synthetic.invalid',
              'PRIVACY_JOURNAL_WITNESS_S3_BUCKET': 'witness-bucket',
              'PRIVACY_JOURNAL_WITNESS_S3_REGION': 'us-east-1',
              'PRIVACY_JOURNAL_WITNESS_S3_ACCESS_KEY': 'fixture-access',
              'PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY': 'fixture-secret'}
    app = {'S3_ENDPOINT': 'https://app.invalid', 'S3_BUCKET': 'app-bucket',
           'S3_ACCESS_KEY': 'app-access', 'S3_SECRET_KEY': 'app-secret'}
    journal, store = module.build_backup_journal('primary-bucket', '', values, app, b'k' * 32)
    assert isinstance(store, MirroredJournalStore) and isinstance(store._witness, S3ImmutableJournalStore)
    assert journal._store is store
    store.close()
    with pytest.raises(ValueError):
        module.build_backup_journal('primary-bucket', 'gcs-witness', values, app, b'k' * 32)
    with pytest.raises(ValueError):
        module.build_backup_journal('primary-bucket', '', dict(values,
            PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY=''), app, b'k' * 32)


def test_timer_and_service_provide_boot_and_stop_recovery():
    root = Path(__file__).resolve().parents[3] / 'infra' / 'gcp-pilot'
    def read(name):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(root / name)
        return parser
    timer = read('asb-backup.timer')
    service = read('asb-backup.service')
    recovery = read('asb-backup-recover.service')
    assert timer['Timer']['Persistent'] == 'true'
    assert timer['Timer']['Unit'] == 'asb-backup.service'
    assert '--recover' in service['Service']['ExecStopPost']
    assert 'asb-backup-recover.service' in service['Unit']['Requires']
    assert '--recover' in recovery['Service']['ExecStart']
