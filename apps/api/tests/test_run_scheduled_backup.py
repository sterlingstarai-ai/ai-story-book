"""Local fail-closed checks for the uninstalled scheduler runner."""

import importlib
import configparser
from collections import namedtuple
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('run_scheduled_backup')


def test_dry_run_does_not_create_state_or_stop_services(module, tmp_path):
    state = tmp_path / 'state'
    assert module.main(['--state-dir', str(state)]) == 0
    assert not state.exists()


_SCHEDULER = (
    '/opt/ai-story-book/current/apps/api/venv/bin/python '
    '/opt/ai-story-book/backup-code-pinned/scripts/run_scheduled_backup.py --execute '
    '--env-file /etc/ai-story-book/pilot/private/pilot.env '
    '--ca-file /etc/ai-story-book/pilot/private/neon-ca.pem '
    '--journal-key-file /etc/ai-story-book/pilot/private/privacy-journal.key '
    '--journal-bucket ${ASB_JOURNAL_BUCKET} --backup-bucket ${ASB_BACKUP_BUCKET} '
    '--state-dir /var/lib/ai-story-book/backup-state --output-dir /var/lib/ai-story-book/backups'
)
_WITNESS = '--journal-witness-bucket ${ASB_JOURNAL_WITNESS_BUCKET}'
_SCHEDULER_CONFIG = (
    'ASB_JOURNAL_BUCKET=primary-fixture\nASB_BACKUP_BUCKET=backup-fixture\n'
    'ASB_JOURNAL_WITNESS_BUCKET=witness-fixture\n'
)


def _loaded_scheduler(argv=_SCHEDULER):
    return (
        f'ExecStartEx={{ path={argv.split()[0]} ; argv[]={argv} ; flags= ; pid=0 }}\n'
        'NeedDaemonReload=no\n'
        'EnvironmentFiles=/etc/ai-story-book/pilot/private/backup-config.env (ignore_errors=no)\n'
    )


@pytest.mark.parametrize('already_bound', [False, True])
@pytest.mark.parametrize('bytecode_flag', ['', '-B '])
def test_witness_plan_preserves_pinned_command_and_only_prints_placeholders(module, already_bound, bytecode_flag):
    scheduler = _SCHEDULER.replace('/bin/python ', f'/bin/python {bytecode_flag}', 1)
    corrected = f'{scheduler} {_WITNESS}'
    loaded = corrected if already_bound else scheduler
    script_index = 2 if bytecode_flag else 1
    plan, dry_args, script = module._scheduler_plan(_loaded_scheduler(loaded), _SCHEDULER_CONFIG)
    assert plan['already_bound'] is already_bound
    assert plan['loaded_exec_start_sha256'] == hashlib.sha256(loaded.encode()).hexdigest()
    assert plan['proposed_exec_start_sha256'] == hashlib.sha256(corrected.encode()).hexdigest()
    assert plan['drop_in'] == (None if already_bound else f'[Service]\nExecStart=\nExecStart={corrected}\n')
    assert 'witness-fixture' not in json.dumps(plan)
    assert script == Path(loaded.split()[script_index])
    assert dry_args == ['--check-bindings', *corrected.replace(
        '${ASB_JOURNAL_BUCKET}', 'primary-fixture').replace(
        '${ASB_BACKUP_BUCKET}', 'backup-fixture').replace(
        '${ASB_JOURNAL_WITNESS_BUCKET}', 'witness-fixture').split()[script_index + 2:]]


@pytest.mark.parametrize('unsafe', [
    _loaded_scheduler().replace('NeedDaemonReload=no', 'NeedDaemonReload=yes'),
    _loaded_scheduler().replace('flags= ;', 'flags=privileged ;'),
    _loaded_scheduler().replace('(ignore_errors=no)', '(ignore_errors=yes)'),
    _loaded_scheduler().replace(' ; flags=', ' ; flags= ; pid=0 } { path=/bin/sh ; argv[]=/bin/sh ; flags='),
    _loaded_scheduler(f'{_SCHEDULER} {_WITNESS} {_WITNESS}'),
    _loaded_scheduler(_SCHEDULER.replace('--env-file /etc/', '--env-file /tmp/')),
    _loaded_scheduler(_SCHEDULER.replace('${ASB_BACKUP_BUCKET}', 'hard-coded')),
    *(_loaded_scheduler(_SCHEDULER.replace('/bin/python ', f'/bin/python {flags} ', 1))
      for flags in ('-I', '-B -B', '-B -I', '-c', '-BB')),
])
def test_witness_plan_rejects_changed_systemd_semantics(module, unsafe):
    with pytest.raises(module.ScheduledBackupError):
        module._scheduler_plan(unsafe, _SCHEDULER_CONFIG)


@pytest.mark.parametrize('capture_mode', ['online', 'offline'])
def test_witness_plan_preserves_the_explicit_capture_mode(module, capture_mode):
    loaded = f'{_SCHEDULER} {_WITNESS} --capture-mode {capture_mode}'
    report, dry_args, _ = module._scheduler_plan(_loaded_scheduler(loaded), _SCHEDULER_CONFIG)
    assert dry_args[-2:] == ['--capture-mode', capture_mode]
    assert report['loaded_exec_start_sha256'] == hashlib.sha256(loaded.encode()).hexdigest()
    assert report['already_bound'] is True


@pytest.mark.parametrize('suffix', ['--capture-mode hybrid', '--capture-mode online --capture-mode offline'])
def test_witness_plan_rejects_ambiguous_capture_mode(module, suffix):
    with pytest.raises(module.ScheduledBackupError):
        module._scheduler_plan(_loaded_scheduler(f'{_SCHEDULER} {_WITNESS} {suffix}'), _SCHEDULER_CONFIG)


@pytest.mark.parametrize('config', [
    _SCHEDULER_CONFIG.replace('ASB_JOURNAL_WITNESS_BUCKET=witness-fixture\n', ''),
    _SCHEDULER_CONFIG + 'ASB_JOURNAL_WITNESS_BUCKET=second-fixture\n',
    'OTHER="\n' + _SCHEDULER_CONFIG + '"\n',
])
def test_witness_plan_rejects_ambiguous_bucket_configuration(module, config):
    with pytest.raises(module.ScheduledBackupError):
        module._scheduler_plan(_loaded_scheduler(), config)


@pytest.mark.parametrize('assignment', [
    'PATH=/tmp/unreviewed:/usr/bin',
    'PYTHONPATH=/tmp/unreviewed',
    'GOOGLE_APPLICATION_CREDENTIALS=/tmp/unreviewed.json',
])
def test_witness_plan_rejects_environment_overrides_outside_reviewed_bindings(module, assignment):
    with pytest.raises(module.ScheduledBackupError, match='unreviewed variable'):
        module._scheduler_plan(_loaded_scheduler(), _SCHEDULER_CONFIG + assignment + '\n')


def test_witness_plan_pins_the_trusted_runner_with_the_declared_option(module, monkeypatch, tmp_path):
    monkeypatch.setattr(module, 'PILOT_ROOT', tmp_path)
    script = tmp_path / 'run_scheduled_backup.py'
    script.write_text('parser.add_argument("--journal-witness-bucket")\n')
    assert module._verify_pinned_scheduler(script) == hashlib.sha256(script.read_bytes()).hexdigest()
    script.chmod(0o666)
    with pytest.raises(module.ScheduledBackupError, match='not trusted'):
        module._verify_pinned_scheduler(script)
    script.chmod(0o600)
    script.write_text('# --journal-witness-bucket\n')
    with pytest.raises(module.ScheduledBackupError, match='does not accept'):
        module._verify_pinned_scheduler(script)


@pytest.mark.parametrize('check_passed', [False, True])
def test_witness_plan_cli_requires_read_only_binding_check(module, monkeypatch, capsys, check_passed):
    entry = module.main
    monkeypatch.setattr(module.subprocess, 'run', lambda *_, **__: SimpleNamespace(stdout=_loaded_scheduler()))
    monkeypatch.setattr(module, 'private_file', lambda *_args, **_kw: _SCHEDULER_CONFIG.encode())
    monkeypatch.setattr(module, '_verify_pinned_scheduler', lambda _path: 'a' * 64)

    def check(arguments):
        assert arguments[0] == '--check-bindings' and '--execute' not in arguments
        print(json.dumps({'status': 'BINDINGS_CHECKED', 'services_stopped': False,
                          'backup_created': False, 'restore_authorized': False}))
        return 0 if check_passed else 1

    monkeypatch.setattr(module, 'main', check)
    assert entry(['--plan-systemd-witness']) == (0 if check_passed else 1)
    report = json.loads(capsys.readouterr().out)
    assert report['installed'] is False and report['backup_created'] is False
    assert ('drop_in' in report) is check_passed


@pytest.mark.parametrize('phase', ['before', 'after', 'rolled_back', 'command_changed', 'runner_changed',
                                  'bytecode_flag_changed'])
def test_witness_plan_cli_rechecks_the_exact_reviewed_transition(module, monkeypatch, capsys, phase):
    entry = module.main
    corrected = f'{_SCHEDULER} {_WITNESS}'
    loaded = corrected if phase == 'after' else _SCHEDULER
    if phase == 'bytecode_flag_changed':
        loaded = loaded.replace('/bin/python ', '/bin/python -B ', 1)
    pinned = 'b' * 64 if phase == 'runner_changed' else 'a' * 64
    expected = corrected if phase in {'after', 'command_changed'} else _SCHEDULER
    monkeypatch.setattr(module.subprocess, 'run', lambda *_, **__: SimpleNamespace(stdout=_loaded_scheduler(loaded)))
    monkeypatch.setattr(module, 'private_file', lambda *_args, **_kw: _SCHEDULER_CONFIG.encode())
    monkeypatch.setattr(module, '_verify_pinned_scheduler', lambda _path: pinned)
    checks = []

    def check(arguments):
        checks.append(arguments)
        print(json.dumps({'status': 'BINDINGS_CHECKED', 'services_stopped': False,
                          'backup_created': False, 'restore_authorized': False}))
        return 0

    monkeypatch.setattr(module, 'main', check)
    result = entry(['--plan-systemd-witness',
                    '--expected-loaded-exec-start-sha256', hashlib.sha256(expected.encode()).hexdigest(),
                    '--expected-pinned-runner-sha256', 'a' * 64])
    report = json.loads(capsys.readouterr().out)
    assert report['installed'] is False and report['backup_created'] is False
    if phase in {'command_changed', 'runner_changed', 'bytecode_flag_changed'}:
        assert result == 1 and report['failure_stage'] == 'reviewed_fingerprints'
        assert not checks and 'drop_in' not in report
    else:
        assert result == 0 and checks[0][0] == '--check-bindings'
        assert report['already_bound'] is (phase == 'after')


@pytest.mark.parametrize('arguments', [
    ['--plan-systemd-witness', '--verify-prerequisites'],
    ['--plan-systemd-witness', '--expected-loaded-exec-start-sha256', 'a' * 64],
    ['--plan-systemd-witness', '--expected-loaded-exec-start-sha256', 'invalid',
     '--expected-pinned-runner-sha256', 'a' * 64],
    ['--execute', '--expected-loaded-exec-start-sha256', 'a' * 64,
     '--expected-pinned-runner-sha256', 'a' * 64],
])
def test_witness_fingerprints_cannot_be_partial_or_apply_changes(module, arguments):
    with pytest.raises(SystemExit) as caught:
        module.main(arguments)
    assert caught.value.code == 2


@pytest.mark.parametrize('fault', [None, 'source_preflight', 'destination_preflight', 'journal_preflight',
                                   'command_changed', 'bucket_changed', 'runner_changed',
                                   'bucket_changed_before'])
@pytest.mark.parametrize('bytecode_flag', ['', '-B '])
def test_witness_plan_checks_reviewed_prerequisites_and_rejects_drift(module, monkeypatch, capsys, fault,
                                                                    bytecode_flag):
    entry = module.main
    checked = False
    scheduler = _SCHEDULER.replace('/bin/python ', f'/bin/python {bytecode_flag}', 1)
    corrected = f'{scheduler} {_WITNESS}'

    def read_plan():
        command = corrected if checked and fault == 'command_changed' else scheduler
        config = _SCHEDULER_CONFIG
        if fault == 'bucket_changed_before' or (checked and fault == 'bucket_changed'):
            config = config.replace('witness-fixture', 'different-witness')
        return module._scheduler_plan(_loaded_scheduler(command), config)

    monkeypatch.setattr(module, '_read_scheduler_plan', read_plan)
    monkeypatch.setattr(module, '_verify_pinned_scheduler',
                        lambda _path: ('b' if checked and fault == 'runner_changed' else 'a') * 64)

    def check(arguments):
        nonlocal checked
        expected = module._scheduler_plan(_loaded_scheduler(scheduler), _SCHEDULER_CONFIG)[1]
        assert arguments == ['--check-prerequisites', *expected[1:]]
        checked = True
        if fault in ('source_preflight', 'destination_preflight', 'journal_preflight'):
            print(json.dumps({'status': 'FAILED', 'stage': fault, 'error_location': 'private-fixture'}))
            return 1
        print(json.dumps({'status': 'PREREQUISITES_CHECKED', 'services_stopped': False,
                          'backup_created': False, 'restore_authorized': False}))
        return 0

    monkeypatch.setattr(module, 'main', check)
    baseline, _, _ = module._scheduler_plan(_loaded_scheduler(scheduler), _SCHEDULER_CONFIG)
    result = entry(['--plan-systemd-witness', '--verify-prerequisites',
                    '--expected-loaded-exec-start-sha256', hashlib.sha256(scheduler.encode()).hexdigest(),
                    '--expected-pinned-runner-sha256', 'a' * 64,
                    '--expected-scheduler-bindings-sha256', baseline['scheduler_bindings_sha256']])
    output = capsys.readouterr().out
    report = json.loads(output)
    assert 'private-fixture' not in output and 'witness-fixture' not in output
    assert report['installed'] is report['backup_created'] is report['restore_authorized'] is False
    if fault == 'bucket_changed_before':
        assert not checked and result == 1 and report['failure_stage'] == 'reviewed_fingerprints'
        assert 'drop_in' not in report
    elif fault is None:
        assert checked
        assert result == 0 and report['prerequisites_checked'] is True
        assert report['drop_in'] == f'[Service]\nExecStart=\nExecStart={corrected}\n'
    else:
        assert checked
        assert result == 1 and 'drop_in' not in report
        assert report['failure_stage'] == ('scheduler_changed' if fault.endswith('_changed') else fault)


@pytest.mark.parametrize('fault', [None, 'writer', 'configuration'])
def test_binding_check_uses_scheduler_config_without_writes(module, monkeypatch, tmp_path, capsys, fault):
    env = tmp_path / 'pilot.env'
    values = {
        'DATABASE_URL': 'postgresql://fixture:credential@db.invalid/storybook',
        'DATABASE_SSL_MODE': 'verify-full', 'DATABASE_SSL_ROOT_CERT': '/container/ca.pem',
        'S3_ENDPOINT': 'https://storage.invalid', 'S3_REGION': 'us-east-1',
        'S3_AUTO_CREATE_BUCKET': 'false', 'S3_ACCESS_KEY': 'inert-access',
        'S3_SECRET_KEY': 'inert-secret', 'S3_BUCKET': 'media',
        'PRIVACY_JOURNAL_ENABLED': 'true', 'PRIVACY_JOURNAL_BUCKET': 'journal',
    }
    if fault == 'configuration':
        values['S3_ENDPOINT'] = 'http://inert-secret.invalid'
    env.write_text('\n'.join(f'{key}={value}' for key, value in values.items()))
    env.chmod(0o600)
    key = tmp_path / 'journal.key'
    key.write_bytes(b'k' * 32)
    key.chmod(0o600)
    ca = tmp_path / 'ca.pem'
    ca.touch()
    state = tmp_path / 'state'
    backup = tmp_path / 'backup'

    class Runtime:
        def _run(self, command, *, timeout):
            assert command[0] == 'inspect'
            if command[2] == '{{.Image}}':
                return 'sha256:' + 'a' * 64
            observed = dict(values)
            if fault == 'writer' and command[-1] == 'asb-pilot-worker':
                observed['S3_BUCKET'] = 'other'
            return json.dumps([f'{name}={value}' for name, value in observed.items()])

    monkeypatch.setattr(module, 'DockerRuntime', Runtime)
    result = module.main(['--check-bindings', '--state-dir', str(state),
        '--env-file', str(env), '--ca-file', str(ca), '--journal-key-file', str(key),
        '--journal-bucket', 'journal', '--backup-bucket', 'archive', '--output-dir', str(backup)])
    output = capsys.readouterr().out
    assert 'inert-secret' not in output
    report = json.loads(output)
    assert not state.exists() and not backup.exists()
    assert report['restore_authorized'] is False
    if fault is None:
        assert result == 0 and report['status'] == 'BINDINGS_CHECKED'
        assert report['services_stopped'] is report['backup_created'] is False
    elif fault == 'writer':
        assert result == 1 and report['stage'] == 'writer_bindings'
    else:
        assert result == 1 and report['stage'] == 'configuration'
        assert report['invalid_fields'] == ['S3_ENDPOINT']


def test_execute_preserves_failure_stage_without_leaking_exception(module, tmp_path, monkeypatch, capsys):
    def unavailable():
        raise RuntimeError('inert-private-provider-output')

    monkeypatch.setattr(module, 'DockerRuntime', unavailable)
    assert module.main(['--execute', '--state-dir', str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert 'inert-private-provider-output' not in output
    assert json.loads(output)['failure_recorded'] is True
    record = json.loads((tmp_path / 'last-scheduled-failure.json').read_text())
    assert record['stage'] == 'configuration' and record['restore_authorized'] is False


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


@pytest.mark.parametrize(('mode', 'fault'), [
    ('--execute', 'database'), ('--execute', 'media'),
    ('--execute', 'credentials'), ('--execute', 'destination'), ('--execute', 'journal'),
    ('--execute', 'media_size'), ('--execute', 'capacity'),
    ('--execute', 'journal_missing'), ('--execute', 'journal_lag'),
    ('--execute', 'guarded_journal'),
    ('--execute', 'bindings'), ('--execute', None),
    ('--check-prerequisites', 'bindings'), ('--check-prerequisites', 'media'),
    ('--check-prerequisites', 'destination'), ('--check-prerequisites', 'journal'),
    ('--check-prerequisites', 'capacity'),
    ('--check-prerequisites', 'mirror_lag'),
    ('--check-prerequisites', None),
])
def test_source_preflight_runs_before_service_guard(module, tmp_path, monkeypatch, capsys, mode, fault):
    from src.core import database
    from src.services.privacy_journal import JournalError
    from src.services import privacy_journal_gcs, privacy_journal_verify

    calls = []
    scans = []
    delays = []
    env = tmp_path / 'env'
    env.write_text('DATABASE_URL=postgresql://fixture:inert-secret@db.example.test/database\n'
                   'DATABASE_SSL_MODE=verify-full\nS3_ACCESS_KEY=fixture\n'
                   'S3_SECRET_KEY=inert-secret\nS3_BUCKET=media-fixture\n')
    env.chmod(0o600)
    key = tmp_path / 'key'
    key.write_bytes(b'k' * 32)
    key.chmod(0o600)
    ca = tmp_path / 'ca'
    ca.touch()

    class Runtime:
        def _run(self, command, *, timeout):
            assert command[0] == 'inspect'
            return 'sha256:' + 'a' * 64

    def check(name):
        calls.append(name)
        if fault == name:
            raise RuntimeError('inert-secret')

    class Media:
        def get_paginator(self, operation):
            assert operation == 'list_objects_v2'
            return self

        def paginate(self, *, Bucket):
            assert Bucket == 'media-fixture'
            check('media')
            yield {'IsTruncated': True, 'NextContinuationToken': 'next',
                   'Contents': [{'Key': 'illustration', 'Size': 200}]}
            yield {'IsTruncated': False, 'Contents': [
                {'Key': 'narration', 'Size': -50 if fault == 'media_size' else 50},
            ]}

        def close(self):
            calls.append('media_closed')

    def run_guard(**kwargs):
        calls.append('backup')
        assert kwargs['media_upload_workers'] == 2
        if fault == 'guarded_journal':
            kwargs['verify_journal']()
        return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED', 'restore_authorized': False}

    @asynccontextmanager
    async def read_session():
        yield 'read-only-session'

    async def compare_journal(session, scan):
        assert session == 'read-only-session' and scan == 'journal-snapshot'
        check('journal')
        if (fault == 'journal_missing' or (fault == 'journal_lag' and len(scans) == 1)
                or (fault == 'guarded_journal' and 'guard' in calls)):
            raise privacy_journal_verify.JournalVerificationError('inert-secret')

    def scan_journal():
        scans.append(tuple(calls))
        if fault == 'mirror_lag' and len(scans) == 1:
            raise JournalError('inert-secret')
        return 'journal-snapshot'

    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ('DATABASE_URL', 'DATABASE_SSL_MODE', 'DATABASE_SSL_ROOT_CERT', 'TESTING'):
        monkeypatch.setenv(name, 'fixture')
    monkeypatch.setattr(module, 'DockerRuntime', Runtime)
    monkeypatch.setattr(module, 'external_infrastructure_errors', lambda _values: [])
    monkeypatch.setattr(module, 'backup_api_source', lambda *_args, **_kwargs: tmp_path)
    monkeypatch.setattr(module, 'assert_runtime_journal_binding', lambda *_args: check('bindings'))
    monkeypatch.setattr(module, 'assert_runtime_media_binding', lambda *_args: None)
    monkeypatch.setattr(module, 'assert_runtime_database_binding', lambda *_args: None)
    monkeypatch.setattr(database, 'configure_for_worker', lambda: None)
    monkeypatch.setattr(database, 'AsyncSessionLocal', read_session)
    monkeypatch.setattr(privacy_journal_gcs, 'application_default_token', lambda: check('credentials'))
    monkeypatch.setattr(privacy_journal_verify, 'verify_current_outbox', compare_journal)
    monkeypatch.setattr(module, 'build_backup_journal', lambda *_args: (
        SimpleNamespace(scan=scan_journal),
        SimpleNamespace(close=lambda: calls.append('journal_closed')),
    ))
    monkeypatch.setattr(module, 'time', SimpleNamespace(sleep=delays.append))
    def backup_store(bucket, token_provider):
        assert bucket == 'backup'

        def verify_access():
            token_provider()
            check('destination')

        return SimpleNamespace(verify_publish_access=verify_access, close=lambda: calls.append('backup_closed'))

    monkeypatch.setattr(module, 'GCSBackupStore', backup_store)
    monkeypatch.setattr(module, 'verify_database_backup_tools', lambda *_args: check('database'))
    monkeypatch.setattr(module, 'storage_client', lambda _values: Media())
    reserve = module.BACKUP_DISK_RESERVE_BYTES
    minimums = []
    require_capacity = module.require_backup_disk_headroom
    available = reserve + (249 if fault == 'capacity' else 250)
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _path: SimpleNamespace(free=available))

    def check_capacity(path, *, minimum_bytes=reserve):
        assert path == tmp_path / 'backup'
        minimums.append(minimum_bytes)
        if minimum_bytes > reserve:
            calls.append('capacity')
        require_capacity(path, minimum_bytes=minimum_bytes)

    monkeypatch.setattr(module, 'require_backup_disk_headroom', check_capacity)
    monkeypatch.setattr(module, 'BackupServiceGuard', lambda *_args, **_kwargs: calls.append('guard'))
    monkeypatch.setattr(module, 'run_guarded_backup', run_guard)
    monkeypatch.setattr(module, 'record_success', lambda *_args: calls.append('recorded'))

    result = module.main([mode, '--state-dir', str(tmp_path / 'state'),
        '--env-file', str(env), '--ca-file', str(ca), '--journal-key-file', str(key),
        '--journal-bucket', 'journal', '--backup-bucket', 'backup', '--output-dir', str(tmp_path / 'backup')])
    output = capsys.readouterr().out
    assert 'inert-secret' not in output
    expected_minimums = [reserve, reserve + 250] if fault in (
        None, 'capacity', 'guarded_journal', 'journal_lag', 'mirror_lag',
    ) else [reserve]
    assert minimums == expected_minimums
    expected_delays = {'journal_lag': [1], 'mirror_lag': [1], 'journal_missing': [1, 2], 'guarded_journal': []}
    if fault in expected_delays:
        assert delays == expected_delays[fault]
        assert len(scans) == (3 if fault == 'journal_missing' else 2)
        if fault == 'guarded_journal':
            assert result == 1 and json.loads(output)['stage'] == 'guarded_backup'
            assert 'guard' in scans[-1] and 'recorded' not in calls
        else:
            assert all('guard' not in scan for scan in scans)
            assert result == (1 if fault == 'journal_missing' else 0)
            assert ('guard' in calls) == (fault == 'journal_lag')
            if fault == 'journal_missing':
                assert json.loads(output)['stage'] == 'journal_preflight'
        return
    assert delays == []
    if mode == '--check-prerequisites':
        assert not (tmp_path / 'state').exists() and not (tmp_path / 'backup').exists()
        assert not {'guard', 'backup', 'recorded'}.intersection(calls)
        if fault is None:
            assert result == 0
            assert json.loads(output) == {
                'status': 'PREREQUISITES_CHECKED', 'services_stopped': False,
                'backup_created': False, 'restore_authorized': False,
            }
            assert calls == ['bindings', 'database', 'media', 'media_closed', 'credentials', 'destination',
                             'journal', 'capacity', 'backup_closed', 'journal_closed']
        else:
            assert result == 1
            assert json.loads(output)['stage'] == {
                'bindings': 'writer_bindings', 'media': 'source_preflight',
                'destination': 'destination_preflight', 'journal': 'journal_preflight',
                'capacity': 'local_destination_preflight',
            }[fault]
            assert fault in calls
    elif fault is None:
        assert result == 0
        assert calls == ['bindings', 'database', 'media', 'media_closed', 'credentials', 'destination',
                         'journal', 'capacity', 'guard', 'backup', 'backup_closed', 'recorded', 'journal_closed']
    else:
        expected_stage = {
            'bindings': 'writer_bindings', 'credentials': 'destination_preflight',
            'destination': 'destination_preflight', 'journal': 'journal_preflight',
            'capacity': 'local_destination_preflight',
        }.get(fault, 'source_preflight')
        assert result == 1 and json.loads(output)['stage'] == expected_stage
        assert (fault in calls or fault == 'media_size') and not {'guard', 'backup', 'recorded'}.intersection(calls)
        assert ('backup_closed' in calls) == (fault in {'credentials', 'destination', 'journal', 'capacity'})
        if fault != 'bindings':
            assert calls[-1] == 'journal_closed'


def test_worker_drain_requires_one_consistent_idle_worker(module):
    class Runtime:
        def __init__(self, reply):
            self.reply = reply
        def _run(self, command, *, timeout):
            assert command[:4] == ['exec', 'asb-pilot-worker', 'python', '-c'] and timeout == 30
            return self.reply
    module.assert_idle_worker(Runtime('{"active":true,"reserved":true,"scheduled":true}'))
    for reply in (
        '{"active":false,"reserved":true,"scheduled":true}',
        '{"active":true,"reserved":false,"scheduled":true}',
        '{"active":true,"reserved":true,"scheduled":false}',
        '{"active":true,"reserved":true,"scheduled":1}',
        '{"active":true,"reserved":true}',
        '{}',
        'provider error',
    ):
        with pytest.raises(module.ScheduledBackupError):
            module.assert_idle_worker(Runtime(reply))


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


def test_timer_and_service_provide_boot_and_stop_recovery(module):
    from backup_service_guard import RECOVERY_COMMAND_SECONDS

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
    assert RECOVERY_COMMAND_SECONDS < int(recovery['Service']['TimeoutStartSec'])
    assert RECOVERY_COMMAND_SECONDS < int(service['Service']['TimeoutStopSec'])


def test_scheduler_recover_uses_bounded_command(module, monkeypatch, tmp_path, capsys):
    calls = []
    monkeypatch.setattr(module, 'recover_services', lambda state: calls.append(state) or True)
    assert module.main(['--recover', '--state-dir', str(tmp_path)]) == 0
    assert calls == [tmp_path]
    assert json.loads(capsys.readouterr().out) == {'status': 'RECOVERED'}
