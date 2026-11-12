"""Explicit runner for a guarded private-pilot backup; not a restore approval.

The default only parses arguments. Running requires dedicated GCS credentials,
an independently recoverable journal key, a migrated database and validated
service-drain/restore controls. A successful upload never authorizes restore.
"""

import argparse
import ast
import asyncio
from contextlib import closing, contextmanager, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from dotenv import dotenv_values

from automatic_backup import run_guarded_backup
from backup_external import (assert_quiescent, create_backup, database_environment,
                             inventory, inventory_fingerprint, storage_client, verify_database_backup_tools)
from backup_service_guard import BackupServiceGuard, DockerRuntime, recover_services
from final_external_preflight import external_infrastructure_errors, present
from postgres_backup_fence import PostgresBackupFence
from publish_backup_gcs import GCSBackupStore

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / 'apps' / 'api'
PILOT_ROOT = Path('/opt/ai-story-book')
BACKUP_API_SOURCES = PILOT_ROOT / 'backup-api-sources'
SCHEDULER_ENV = Path('/etc/ai-story-book/pilot/private/backup-config.env')
_BUCKET_OPTIONS = {
    '--journal-bucket': 'ASB_JOURNAL_BUCKET',
    '--backup-bucket': 'ASB_BACKUP_BUCKET',
    '--journal-witness-bucket': 'ASB_JOURNAL_WITNESS_BUCKET',
}
_PRIVATE_OPTIONS = {'--env-file', '--ca-file', '--journal-key-file'}
_DATA_OPTIONS = {'--state-dir', '--output-dir'}
BACKUP_DISK_RESERVE_BYTES = 1024 * 1024 * 1024


class ScheduledBackupError(RuntimeError):
    pass


def verify_backup_sources(values, environment, query):
    """Check source access and measure the media that must fit on disk."""
    verify_database_backup_tools(environment, query)
    try:
        with closing(storage_client(values)) as client:
            objects = inventory(client, values['S3_BUCKET'])
        size = 0
        for metadata in objects.values():
            value = metadata['Size']
            if not re.fullmatch(r'[0-9]{1,20}', value):
                raise ValueError('Media size is invalid')
            size += int(value)
        return size
    except Exception:
        raise ScheduledBackupError('Source media inventory could not be verified') from None


def require_backup_disk_headroom(output_dir, *, minimum_bytes=BACKUP_DISK_RESERVE_BYTES):
    """Check the destination filesystem before stopping live services.

    The caller can include known media bytes above the reserve. This does not
    bound dump size or guarantee space against concurrent changes.
    """
    if not isinstance(output_dir, Path) or not output_dir.is_absolute():
        raise ScheduledBackupError('An absolute backup destination is required')
    path = output_dir
    while not path.exists():
        if path.is_symlink() or path == path.parent:
            raise ScheduledBackupError('Backup destination is inaccessible')
        path = path.parent
    if path.is_symlink() or not path.is_dir():
        raise ScheduledBackupError('Backup destination must be a directory')
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        raise ScheduledBackupError('Backup disk capacity is unavailable') from None
    if free < minimum_bytes:
        raise ScheduledBackupError('Insufficient backup disk headroom')


def _write_backup_record(state_dir, filename, record):
    target = state_dir / filename
    fd, temp_name = tempfile.mkstemp(prefix=f'.{filename}-', dir=state_dir)
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(record, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, target)
        directory_fd = os.open(state_dir, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def record_success(state_dir):
    """Persist the time of a remotely verified cycle after service recovery."""
    _write_backup_record(state_dir, 'last-verified-backup.json', {
        'version': 1, 'verified_at': datetime.now(timezone.utc).isoformat(), 'restore_authorized': False,
    })


def record_failure(state_dir, stage):
    """Persist only the stage and time so a reboot cannot erase the diagnosis."""
    _write_backup_record(state_dir, 'last-scheduled-failure.json', {
        'version': 1, 'failed_at': datetime.now(timezone.utc).isoformat(), 'stage': stage,
        'restore_authorized': False,
    })


def private_file(path, *, max_bytes):
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ScheduledBackupError('A private owner-only file is required')
        data = os.read(fd, max_bytes + 1)
        if len(data) > max_bytes:
            raise ScheduledBackupError('Private input exceeds its size limit')
        return data
    finally:
        os.close(fd)


def assert_idle_worker(runtime):
    """Reject unresponsive, multiple, active, reserved or ETA worker tasks."""
    from worker_control_probe import worker_control_source

    # Avoid repeated Celery CLI/application imports on the memory-limited VM.
    # Each control retains its own reply mailbox and full broadcast window.
    probe = worker_control_source(('active', 'reserved', 'scheduled'), timeout=10)
    raw = runtime._run(['exec', 'asb-pilot-worker', 'python', '-c', probe], timeout=30)
    try:
        value = json.loads(raw)
    except ValueError:
        raise ScheduledBackupError('Worker state could not be verified') from None
    if (not isinstance(value, dict) or set(value) != {'active', 'reserved', 'scheduled'}
            or any(idle is not True for idle in value.values())):
        raise ScheduledBackupError('Worker is busy or did not respond')


def assert_runtime_journal_binding(runtime, primary_bucket, witness_bucket, s3_values=None):
    """Reject backup configurations that differ from either live writer.

    Docker environment values stay in this process; no values are logged.
    S3 settings must be supplied by the checked private backup env file and
    match both writers exactly, including credentials.
    """
    names = {'PRIVACY_JOURNAL_ENABLED', 'PRIVACY_JOURNAL_BUCKET', 'PRIVACY_JOURNAL_WITNESS_BUCKET'}
    expected = {'PRIVACY_JOURNAL_ENABLED': 'true', 'PRIVACY_JOURNAL_BUCKET': primary_bucket,
                'PRIVACY_JOURNAL_WITNESS_BUCKET': witness_bucket}
    s3_names = {'PRIVACY_JOURNAL_WITNESS_S3_' + suffix for suffix in
                ('ENDPOINT', 'BUCKET', 'REGION', 'ACCESS_KEY', 'SECRET_KEY')}
    names.update(s3_names)
    if s3_values is None:
        s3_values = {name: '' for name in s3_names}
    if (not isinstance(s3_values, dict) or set(s3_values) != s3_names
            or any(not isinstance(value, str) for value in s3_values.values())):
        raise ScheduledBackupError('Live service journal settings do not match the backup')
    expected.update(s3_values)
    for container in ('asb-pilot-api', 'asb-pilot-worker'):
        try:
            values = json.loads(runtime._run(['inspect', '--format', '{{json .Config.Env}}', container], timeout=15))
            if not isinstance(values, list):
                raise ValueError('invalid environment')
            selected = {}
            for item in values:
                if not isinstance(item, str) or '=' not in item:
                    raise ValueError('invalid environment item')
                key, value = item.split('=', 1)
                if key in names:
                    if key in selected:
                        raise ValueError('duplicate journal setting')
                    selected[key] = value
            selected.setdefault('PRIVACY_JOURNAL_WITNESS_BUCKET', '')
            for name in s3_names:
                selected.setdefault(name, '')
            if selected.get('PRIVACY_JOURNAL_ENABLED', '').lower() != 'true':
                raise ValueError('journal disabled')
            selected['PRIVACY_JOURNAL_ENABLED'] = selected['PRIVACY_JOURNAL_ENABLED'].lower()
            if selected != expected:
                raise ValueError('journal configuration mismatch')
        except Exception:
            raise ScheduledBackupError('Live service journal settings do not match the backup') from None


def assert_runtime_media_binding(runtime, values):
    """Ensure the backup inventory points to the same media store as both writers."""
    names = ('S3_ENDPOINT', 'S3_BUCKET', 'S3_REGION', 'S3_ACCESS_KEY', 'S3_SECRET_KEY')
    expected = {name: values.get(name) for name in names}
    if any(not present(value) for value in expected.values()):
        raise ScheduledBackupError('Backup media configuration is incomplete')
    for container in ('asb-pilot-api', 'asb-pilot-worker'):
        try:
            items = json.loads(runtime._run(['inspect', '--format', '{{json .Config.Env}}', container], timeout=15))
            if not isinstance(items, list):
                raise ValueError()
            observed = {}
            for item in items:
                key, value = item.split('=', 1)
                if key in expected:
                    if key in observed:
                        raise ValueError()
                    observed[key] = value
            if observed != expected:
                raise ValueError()
        except Exception:
            raise ScheduledBackupError('Live service media settings do not match the backup') from None


def assert_runtime_database_binding(runtime, values, ca_file):
    """Verify the DB and transport used by the backup match both live writers."""
    names = {'DATABASE_URL', 'DATABASE_MIGRATION_URL', 'DATABASE_SSL_MODE'}
    try:
        expected = database_environment(values, ca_file)
        expected_app = database_environment({'DATABASE_URL': values['DATABASE_URL']}, ca_file)
        for container in ('asb-pilot-api', 'asb-pilot-worker'):
            items = json.loads(runtime._run(['inspect', '--format', '{{json .Config.Env}}', container], timeout=15))
            if not isinstance(items, list):
                raise ValueError()
            observed = {}
            for item in items:
                key, value = item.split('=', 1)
                if key in names:
                    if key in observed:
                        raise ValueError()
                    observed[key] = value
            if (observed.get('DATABASE_SSL_MODE') != values.get('DATABASE_SSL_MODE')
                    or database_environment(observed, ca_file) != expected):
                raise ValueError()
            # The running app may use a pooled URL while the backup uses a
            # direct connection. It must still match the reviewed app DSN.
            app = {'DATABASE_URL': observed['DATABASE_URL']}
            if database_environment(app, ca_file) != expected_app:
                raise ValueError()
    except Exception:
        raise ScheduledBackupError('Live service database settings do not match the backup') from None


def build_backup_journal(primary_bucket, witness_bucket, s3_values, values, key):
    """Build the same explicitly configured readers used by both writers."""
    from src.services.privacy_journal import PrivacyJournal
    from src.services.privacy_journal_gcs import GCSImmutableStore

    store = GCSImmutableStore(primary_bucket)
    try:
        if not witness_bucket and not any(s3_values.values()):
            return PrivacyJournal(store, key), store
        from src.services.privacy_journal_mirror import MirroredJournalStore
        from src.services.privacy_journal_runtime import create_s3_witness

        s3_witness = create_s3_witness(
            endpoint=s3_values['PRIVACY_JOURNAL_WITNESS_S3_ENDPOINT'],
            bucket=s3_values['PRIVACY_JOURNAL_WITNESS_S3_BUCKET'],
            region=s3_values['PRIVACY_JOURNAL_WITNESS_S3_REGION'],
            access=s3_values['PRIVACY_JOURNAL_WITNESS_S3_ACCESS_KEY'],
            secret=s3_values['PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY'],
            app_endpoint=values.get('S3_ENDPOINT', ''), app_bucket=values.get('S3_BUCKET', ''),
            app_access=values.get('S3_ACCESS_KEY', ''), app_secret=values.get('S3_SECRET_KEY', ''),
            gcs_witness_bucket=witness_bucket)
        if s3_witness is not None:
            store = MirroredJournalStore(store, s3_witness)
        elif witness_bucket:
            store = MirroredJournalStore(store, GCSImmutableStore(witness_bucket))
        return PrivacyJournal(store, key), store
    except Exception:
        store.close()
        raise


def backup_api_source(image_id, *, mirrored):
    """Select the same model/journal implementation as the mirrored writers."""
    if not mirrored:
        return API
    if not re.fullmatch(r'local-image@sha256:[0-9a-f]{64}', image_id):
        raise ScheduledBackupError('Backup API source requires a pinned image')
    path = BACKUP_API_SOURCES / image_id.rsplit(':', 1)[1]
    for directory in (BACKUP_API_SOURCES, path, path / 'src'):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ScheduledBackupError('Backup API source directory is unsafe')
    if private_file(path / 'image-id', max_bytes=128) != image_id.encode() + b'\n':
        raise ScheduledBackupError('Backup API source does not match the running image')
    files = {}
    for entry in (path / 'src').rglob('*'):
        info = entry.lstat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o022 or entry.is_symlink():
            raise ScheduledBackupError('Backup API source file is unsafe')
        if stat.S_ISREG(info.st_mode) and '__pycache__' not in entry.parts and entry.suffix != '.pyc':
            files[str(entry.relative_to(path))] = hashlib.sha256(entry.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if not files or private_file(path / 'source-sha256', max_bytes=128) != digest.encode() + b'\n':
        raise ScheduledBackupError('Backup API source has changed')
    return path


def _scheduler_path(value, parent):
    path = Path(value)
    return (re.fullmatch(r'/[A-Za-z0-9_./-]+', value)
            and str(path) == value and '..' not in path.parts and parent in path.parents)


def _scheduler_plan(raw, config):
    """Allow only the known scheduler command shape and literal environment file."""
    lines = raw.splitlines()
    props = dict(line.split('=', 1) for line in lines if '=' in line)
    if (len(lines) != 3 or set(props) != {'ExecStartEx', 'NeedDaemonReload', 'EnvironmentFiles'}
            or props['NeedDaemonReload'] != 'no'
            or props['EnvironmentFiles'] != f'{SCHEDULER_ENV} (ignore_errors=no)'):
        raise ScheduledBackupError('Loaded scheduler unit or environment is unexpected')
    command = re.fullmatch(r'\{ path=([^ ;]+) ; argv\[\]=([^;]+) ; flags= ; [^{}]+\}',
                           props['ExecStartEx'].strip())
    if command is None:
        raise ScheduledBackupError('Exactly one unmodified scheduler command is required')
    executable, command_line = command.groups()
    argv = shlex.split(command_line)
    # Accept the legacy command for transition planning and exactly one reviewed
    # bytecode-suppression flag. Other Python options can change code loading.
    script_index = 2 if len(argv) > 1 and argv[1] == '-B' else 1
    if (len(argv) < script_index + 2 or argv[0] != executable or argv[script_index + 1] != '--execute'
            or not (_scheduler_path(argv[0], PILOT_ROOT) or argv[0] == '/usr/bin/python3')
            or not re.fullmatch(r'python(?:3(?:\.\d+)?)?', Path(argv[0]).name)
            or not _scheduler_path(argv[script_index], PILOT_ROOT)
            or Path(argv[script_index]).name != 'run_scheduled_backup.py'):
        raise ScheduledBackupError('Loaded scheduler executable is unexpected')
    fields = argv[script_index + 2:]
    options = fields[::2]
    witness_option = '--journal-witness-bucket'
    required = _PRIVATE_OPTIONS | _DATA_OPTIONS | (_BUCKET_OPTIONS.keys() - {witness_option})
    if (len(fields) != 2 * len(options) or len(options) != len(set(options))
            or set(options) not in (required, required | {witness_option},
                                    required | {'--capture-mode'},
                                    required | {witness_option, '--capture-mode'})):
        raise ScheduledBackupError('Loaded scheduler arguments are unexpected')
    original = ' '.join(argv)
    environment = {}
    allowed_variables = _BUCKET_OPTIONS.values()
    for line in config.splitlines():
        if not line.strip() or line.lstrip().startswith(('#', ';')):
            continue
        assignment = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)=([A-Za-z0-9_./:@+\-]*)', line)
        if assignment is None or assignment[1] in environment:
            raise ScheduledBackupError('Scheduler environment assignments must be unique and literal')
        if assignment[1] not in allowed_variables:
            raise ScheduledBackupError('Scheduler environment contains an unreviewed variable')
        environment[assignment[1]] = assignment[2]
    if witness_option not in options:
        fields.extend((witness_option, '${ASB_JOURNAL_WITNESS_BUCKET}'))
    dry_args = ['--check-bindings']
    for option, value in zip(fields[::2], fields[1::2], strict=True):
        if option == '--capture-mode':
            if value not in ('offline', 'online'):
                raise ScheduledBackupError('Unreviewed backup capture mode')
        elif option in _BUCKET_OPTIONS:
            name = _BUCKET_OPTIONS[option]
            if value != '${' + name + '}':
                raise ScheduledBackupError('Scheduler bucket argument is not bound to its environment')
            value = environment.get(name, '')
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', value):
                raise ScheduledBackupError('Scheduler bucket configuration is absent or ambiguous')
        elif not _scheduler_path(value, SCHEDULER_ENV.parent if option in _PRIVATE_OPTIONS
                                 else Path('/var/lib/ai-story-book')):
            raise ScheduledBackupError('Loaded scheduler data path is unexpected')
        dry_args.extend((option, value))
    command = ' '.join(argv[:script_index + 2] + fields)
    return {
        'status': 'SCHEDULER_WITNESS_PLAN_CHECKED',
        'loaded_exec_start_sha256': hashlib.sha256(original.encode()).hexdigest(),
        'proposed_exec_start_sha256': hashlib.sha256(command.encode()).hexdigest(),
        'scheduler_bindings_sha256': hashlib.sha256(
            json.dumps(dry_args[1:], separators=(',', ':')).encode()).hexdigest(),
        'already_bound': witness_option in options,
        'drop_in': None if witness_option in options else f'[Service]\nExecStart=\nExecStart={command}\n',
        'installed': False, 'backup_created': False, 'restore_authorized': False,
    }, dry_args, Path(argv[script_index])


def _verify_pinned_scheduler(path):
    path = path.resolve(strict=True)
    if PILOT_ROOT not in path.parents:
        raise ScheduledBackupError('Pinned scheduler is outside the pilot tree')
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as source:
        mode = os.fstat(source.fileno())
        if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid() or mode.st_mode & 0o022:
            raise ScheduledBackupError('Pinned scheduler is not trusted')
        data = source.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024 or not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'add_argument' and node.args and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == '--journal-witness-bucket'
        for node in ast.walk(ast.parse(data))
    ):
        raise ScheduledBackupError('Pinned scheduler does not accept the witness option')
    return hashlib.sha256(data).hexdigest()


def _read_scheduler_plan():
    raw = subprocess.run(
        ['/usr/bin/systemctl', 'show', 'asb-backup.service',
         '--property=ExecStartEx,NeedDaemonReload,EnvironmentFiles'],
        capture_output=True, text=True, timeout=15, check=True,
    ).stdout
    config = private_file(SCHEDULER_ENV, max_bytes=1024 * 1024).decode('utf-8')
    return _scheduler_plan(raw, config)


def _plan_systemd_witness(expected_fingerprints=None, *, expected_bindings=None):
    stage = 'loaded_scheduler'
    try:
        report, dry_args, pinned = _read_scheduler_plan()
        stage = 'pinned_runner'
        report['pinned_runner_sha256'] = _verify_pinned_scheduler(pinned)
        stage = 'reviewed_fingerprints'
        if expected_fingerprints is not None and expected_fingerprints != (
                report['loaded_exec_start_sha256'], report['pinned_runner_sha256']):
            raise ScheduledBackupError('Loaded scheduler differs from the reviewed plan')
        if expected_bindings is not None and expected_bindings != report['scheduler_bindings_sha256']:
            raise ScheduledBackupError('Scheduler bindings differ from the reviewed plan')
        verify_prerequisites = expected_bindings is not None
        stage = 'writer_bindings'
        check_args = ['--check-prerequisites', *dry_args[1:]] if verify_prerequisites else dry_args
        with redirect_stdout(io.StringIO()) as output:
            status = main(check_args)
        observed = json.loads(output.getvalue())
        if status != 0 and verify_prerequisites and isinstance(observed, dict):
            failed_stage = observed.get('stage')
            if failed_stage in ('backup_source', 'configuration', 'initialization',
                                'writer_bindings', 'source_preflight', 'destination_preflight', 'journal_preflight'):
                stage = failed_stage
        if status != 0 or observed != {
            'status': 'PREREQUISITES_CHECKED' if verify_prerequisites else 'BINDINGS_CHECKED',
            'services_stopped': False,
            'backup_created': False, 'restore_authorized': False,
        }:
            raise ScheduledBackupError('Proposed backup checks failed')
        if verify_prerequisites:
            stage = 'scheduler_changed'
            fresh, fresh_args, fresh_pinned = _read_scheduler_plan()
            if (fresh['loaded_exec_start_sha256'] != report['loaded_exec_start_sha256']
                    or fresh_args != dry_args or fresh_pinned != pinned
                    or _verify_pinned_scheduler(fresh_pinned) != report['pinned_runner_sha256']):
                raise ScheduledBackupError('Scheduler changed during verification')
            report['prerequisites_checked'] = True
        print(json.dumps(report))
        return 0
    except (OSError, SyntaxError, ValueError, subprocess.SubprocessError, ScheduledBackupError):
        print(json.dumps({'status': 'SCHEDULER_WITNESS_PLAN_FAILED', 'failure_stage': stage, 'installed': False,
                          'backup_created': False, 'restore_authorized': False}))
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--recover', action='store_true')
    mode.add_argument('--check-bindings', action='store_true',
                      help='Check the scheduled backup inputs and live container bindings without stopping services')
    mode.add_argument('--check-prerequisites', action='store_true',
                      help='Read backup sources and reconcile the privacy journal without stopping services')
    mode.add_argument('--plan-systemd-witness', action='store_true',
                      help='Print a binding-checked witness drop-in for the loaded scheduler without installing it')
    parser.add_argument('--verify-prerequisites', action='store_true',
                        help='Check the reviewed witness plan against the source data and journal')
    parser.add_argument('--expected-loaded-exec-start-sha256',
                        help='Reviewed scheduler command fingerprint for a witness plan recheck')
    parser.add_argument('--expected-pinned-runner-sha256',
                        help='Reviewed scheduler runner fingerprint for a witness plan recheck')
    parser.add_argument('--expected-scheduler-bindings-sha256',
                        help='Reviewed resolved scheduler argument fingerprint for prerequisite verification')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--ca-file', type=Path)
    parser.add_argument('--journal-key-file', type=Path)
    parser.add_argument('--journal-bucket')
    parser.add_argument('--journal-witness-bucket', default='')
    parser.add_argument('--backup-bucket')
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--capture-mode', choices=('offline', 'online'), default='offline',
                        help='Online uses a bounded snapshot cut without stopping API or worker')
    args = parser.parse_args(argv)
    fingerprints = (args.expected_loaded_exec_start_sha256, args.expected_pinned_runner_sha256)
    if any(value is not None for value in fingerprints):
        if not args.plan_systemd_witness or not all(
                value and re.fullmatch(r'[0-9a-f]{64}', value) for value in fingerprints):
            parser.error('Both lowercase SHA-256 fingerprints require --plan-systemd-witness')
    else:
        fingerprints = None
    expected_bindings = args.expected_scheduler_bindings_sha256
    if args.verify_prerequisites:
        if fingerprints is None or not re.fullmatch(r'[0-9a-f]{64}', expected_bindings or ''):
            parser.error('--verify-prerequisites requires --plan-systemd-witness and all three reviewed SHA-256 fingerprints')
    elif expected_bindings is not None:
        parser.error('--expected-scheduler-bindings-sha256 requires --verify-prerequisites')
    if args.plan_systemd_witness:
        if any((args.state_dir, args.env_file, args.ca_file, args.journal_key_file,
                args.journal_bucket, args.journal_witness_bucket, args.backup_bucket, args.output_dir,
                args.capture_mode != 'offline')):
            parser.error('--plan-systemd-witness reads arguments from the loaded scheduler')
        return _plan_systemd_witness(fingerprints, expected_bindings=expected_bindings)
    if args.state_dir is None:
        parser.error('--state-dir is required')
    if not (args.execute or args.recover or args.check_bindings or args.check_prerequisites):
        print(json.dumps({'status': 'DRY_RUN', 'services_stopped': False, 'restore_authorized': False}))
        return 0
    stage = 'configuration'
    invalid_fields = []
    timings_ms = {}
    try:
        if args.recover:
            stage = 'recovery'
            recovered = recover_services(args.state_dir)
            print(json.dumps({'status': 'RECOVERED' if recovered else 'NO_RECOVERY_NEEDED'}))
            return 0
        runtime = DockerRuntime()
        if not all((args.env_file, args.ca_file, args.journal_key_file, args.journal_bucket,
                    args.backup_bucket, args.output_dir)) or args.journal_bucket == args.backup_bucket:
            raise ScheduledBackupError('Distinct journal and backup buckets and private inputs are required')
        if args.journal_witness_bucket and args.journal_witness_bucket in (args.journal_bucket, args.backup_bucket):
            raise ScheduledBackupError('Witness must use a distinct bucket')
        stage = 'local_destination_preflight'
        require_backup_disk_headroom(args.output_dir)
        stage = 'configuration'
        # SQLAlchemy async needs this optional dependency; fail before stopping
        # either service if the backup host environment is incomplete.
        import greenlet  # noqa: F401
        env_bytes = private_file(args.env_file, max_bytes=1024 * 1024)
        key = private_file(args.journal_key_file, max_bytes=32)
        if len(key) != 32:
            raise ScheduledBackupError('Journal key must be exactly 32 bytes')
        # dotenv_values accepts a stream so checked file bytes are parsed only once.
        values = {k: v or '' for k, v in dotenv_values(stream=io.StringIO(env_bytes.decode('utf-8')),
                                                       interpolate=False).items()}
        for name, container in (('API_IMAGE', 'asb-pilot-api'), ('WORKER_IMAGE', 'asb-pilot-worker')):
            image_id = runtime._run(['inspect', '--format', '{{.Image}}', container], timeout=15)
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
                raise ScheduledBackupError('Container image identity is invalid')
            values[name] = 'local-image@' + image_id
        s3_values = {name: values.get(name, '') for name in (
            'PRIVACY_JOURNAL_WITNESS_S3_ENDPOINT', 'PRIVACY_JOURNAL_WITNESS_S3_BUCKET',
            'PRIVACY_JOURNAL_WITNESS_S3_REGION', 'PRIVACY_JOURNAL_WITNESS_S3_ACCESS_KEY',
            'PRIVACY_JOURNAL_WITNESS_S3_SECRET_KEY')}
        errors = external_infrastructure_errors(values)
        errors.extend(name for name in ('S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_BUCKET')
                      if not present(values.get(name)))
        if errors:
            invalid_fields = sorted({error.split(' ', 1)[0] for error in errors
                                     if re.fullmatch(r'[A-Z][A-Z0-9_]*', error.split(' ', 1)[0])})
            raise ScheduledBackupError('External backup configuration is invalid')
        ca_stat = args.ca_file.lstat()
        if (not stat.S_ISREG(ca_stat.st_mode) or stat.S_ISLNK(ca_stat.st_mode)
                or ca_stat.st_uid != os.geteuid() or ca_stat.st_mode & 0o022):
            raise ScheduledBackupError('A valid provider CA is required')

        def verify_bindings():
            assert_runtime_journal_binding(runtime, args.journal_bucket, args.journal_witness_bucket, s3_values)
            assert_runtime_media_binding(runtime, values)
            assert_runtime_database_binding(runtime, values, args.ca_file)
            for name, container in (('API_IMAGE', 'asb-pilot-api'), ('WORKER_IMAGE', 'asb-pilot-worker')):
                image_id = runtime._run(['inspect', '--format', '{{.Image}}', container], timeout=15)
                if values[name] != 'local-image@' + image_id:
                    raise ScheduledBackupError('Container image changed during backup preflight')

        stage = 'backup_source'
        source = backup_api_source(values['API_IMAGE'], mirrored=bool(args.journal_witness_bucket or any(s3_values.values())))
        stage = 'writer_bindings'
        verify_bindings()
        if args.check_bindings:
            print(json.dumps({'status': 'BINDINGS_CHECKED', 'services_stopped': False,
                              'backup_created': False, 'restore_authorized': False}))
            return 0

        stage = 'initialization'
        # Async ORM reads the same source DB using the host's explicit CA.
        from sqlalchemy.engine import make_url
        # The container CA path may also be present in the DSN; the scheduler
        # uses the independently supplied host path with the same TLS mode.
        # Match the exact endpoint/database selected by backup_external.
        raw_database = values.get('DATABASE_MIGRATION_URL') or values['DATABASE_URL']
        if raw_database.startswith('postgres://'):
            raw_database = 'postgresql://' + raw_database[len('postgres://'):]
        os.environ['DATABASE_URL'] = make_url(raw_database).difference_update_query(
            ['sslrootcert']).render_as_string(hide_password=False)
        os.environ['DATABASE_SSL_MODE'] = values['DATABASE_SSL_MODE']
        os.environ['DATABASE_SSL_ROOT_CERT'] = str(args.ca_file)
        os.environ['TESTING'] = 'false'
        sys.path.insert(0, str(source))
        from src.core.database import AsyncSessionLocal, configure_for_worker
        from src.services.privacy_journal import JournalError
        from src.services.privacy_journal_gcs import application_default_token
        from src.services.privacy_journal_verify import JournalVerificationError, verify_current_outbox

        configure_for_worker()  # Separate asyncio.run calls must not reuse an event loop's pool.
        environment = database_environment(values, args.ca_file)
        journal, journal_store = build_backup_journal(args.journal_bucket, args.journal_witness_bucket,
                                                       s3_values, values, key)
        query = ['psql', '-X', '--no-password', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c']

        def verify_idle():
            verify_bindings()
            assert_quiescent(environment, query)
            assert_idle_worker(runtime)

        def verify_journal():
            async def check():
                scan = await asyncio.to_thread(journal.scan)
                async with AsyncSessionLocal() as session:
                    return await verify_current_outbox(session, scan)
            return asyncio.run(check())

        @contextmanager
        def publication_boundary():
            with PostgresBackupFence(environment) as fence:
                def capture():
                    return create_backup(values, args.output_dir, args.ca_file, fence=fence, media_download_workers=2)

                def verify(result):
                    fence.verify()
                    with closing(storage_client(values)) as client:
                        observed = inventory_fingerprint(inventory(client, values['S3_BUCKET']))
                    if observed != result.get('media_inventory_sha256'):
                        raise ScheduledBackupError('Media inventory changed before backup publication')
                    fence.verify()

                yield capture, verify

        try:
            stage = 'source_preflight'
            media_bytes = verify_backup_sources(values, environment, query)
            stage = 'destination_preflight'
            with closing(GCSBackupStore(args.backup_bucket, application_default_token)) as backup_store:
                backup_store.verify_publish_access()
                # Live privacy writes can span the store listings and DB read.
                # Retry the comparison here. The fenced checks remain single-attempt.
                stage = 'journal_preflight'
                if args.capture_mode == 'offline':
                    for attempt in range(1, 4):
                        try:
                            verify_journal()
                            break
                        except (JournalError, JournalVerificationError):
                            if attempt == 3:
                                raise
                            time.sleep(attempt)
                else:
                    # Full live equality is checked at the online snapshot cut,
                    # not against a DB that can change during this network scan.
                    journal.scan()
                stage = 'local_destination_preflight'
                require_backup_disk_headroom(
                    args.output_dir, minimum_bytes=BACKUP_DISK_RESERVE_BYTES + media_bytes,
                )
                if args.check_prerequisites:
                    print(json.dumps({'status': 'PREREQUISITES_CHECKED', 'services_stopped': False,
                                      'backup_created': False, 'restore_authorized': False}))
                    return 0
                stage = 'guarded_backup'
                guard = BackupServiceGuard(args.state_dir, runtime, timings_ms=timings_ms)
                if args.capture_mode == 'online':
                    from online_backup import run_online_backup
                    result = run_online_backup(
                        guard=guard, values=values, environment=environment, ca_file=args.ca_file,
                        output_dir=args.output_dir, store=backup_store, run_id=uuid.uuid4().hex,
                        journal=journal, session_factory=AsyncSessionLocal,
                        verify_bindings=verify_bindings, timings_ms=timings_ms,
                        on_snapshot_ready=lambda: print(json.dumps({
                            'status': 'ONLINE_SNAPSHOT_CUT_RELEASED', 'services_stopped': False,
                        }), file=sys.stderr, flush=True))
                else:
                    result = run_guarded_backup(guard=guard, verify_idle=verify_idle, preflight_idle=verify_idle,
                        verify_journal=verify_journal,
                        publication_boundary=publication_boundary,
                        output_dir=args.output_dir, store=backup_store, run_id=uuid.uuid4().hex,
                        media_upload_workers=2, timings_ms=timings_ms)
            record_success(args.state_dir)
        finally:
            journal_store.close()
        print(json.dumps({**result, 'timings_ms': timings_ms}, sort_keys=True))
        return 0
    except Exception as exc:
        # Commands/provider responses can contain credentials and child data.
        import traceback
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        failure_recorded = False
        if args.execute:
            try:
                record_failure(args.state_dir, stage)
                failure_recorded = True
            except OSError:
                pass
        print(json.dumps({'status': 'FAILED', 'restore_authorized': False,
                          'stage': stage,
                          **({'timings_ms': timings_ms} if timings_ms else {}),
                          **({'failure_recorded': failure_recorded} if args.execute else {}),
                          **({'invalid_fields': invalid_fields} if invalid_fields else {}),
                          'error_type': type(exc).__name__, 'error_location': f'{Path(frame.filename).name}:{frame.lineno}',
                          'message': 'Backup did not complete; check restricted operator logs and recovery marker.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
