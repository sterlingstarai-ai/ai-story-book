"""Explicit runner for a guarded private-pilot backup; not a restore approval.

The default only parses arguments. Running requires dedicated GCS credentials,
an independently recoverable journal key, a migrated database and validated
service-drain/restore controls. A successful upload never authorizes restore.
"""

import argparse
import asyncio
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid

from dotenv import dotenv_values

from automatic_backup import run_guarded_backup
from backup_external import (assert_quiescent, create_backup, database_environment,
                             inventory, inventory_fingerprint, storage_client)
from backup_service_guard import BackupServiceGuard, DockerRuntime
from final_external_preflight import external_infrastructure_errors, present
from postgres_backup_fence import PostgresBackupFence
from publish_backup_gcs import GCSBackupStore

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / 'apps' / 'api'
BACKUP_API_SOURCES = Path('/opt/ai-story-book/backup-api-sources')


class ScheduledBackupError(RuntimeError):
    pass


def require_backup_disk_headroom(output_dir, *, minimum_bytes=1024 * 1024 * 1024):
    """Check the destination filesystem before stopping live services.

    This is a fixed emergency reserve, not an estimate of backup size and not
    a guarantee against concurrent writers or an unexpectedly large backup.
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


def record_success(state_dir):
    """Persist the time of a remotely verified cycle after service recovery."""
    target = state_dir / 'last-verified-backup.json'
    fd, temp_name = tempfile.mkstemp(prefix='.last-verified-', dir=state_dir)
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump({'version': 1, 'verified_at': datetime.now(timezone.utc).isoformat(),
                       'restore_authorized': False}, output, sort_keys=True)
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
    workers = None
    for kind in ('active', 'reserved', 'scheduled'):
        raw = runtime._run(['exec', 'asb-pilot-worker', 'celery', '-A', 'src.worker', 'inspect',
                            kind, '--timeout', '10', '--json'], timeout=30)
        try:
            value = json.loads(raw)
        except ValueError:
            raise ScheduledBackupError('Worker state could not be verified') from None
        if (not isinstance(value, dict) or len(value) != 1
                or any(not isinstance(tasks, list) or tasks for tasks in value.values())):
            raise ScheduledBackupError('Worker is busy or did not respond')
        current = frozenset(value)
        if workers is not None and current != workers:
            raise ScheduledBackupError('Worker identity changed during drain')
        workers = current


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--ca-file', type=Path)
    parser.add_argument('--journal-key-file', type=Path)
    parser.add_argument('--journal-bucket')
    parser.add_argument('--journal-witness-bucket', default='')
    parser.add_argument('--backup-bucket')
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    if args.execute and args.recover:
        parser.error('Choose execution or recovery')
    if not args.execute and not args.recover:
        print(json.dumps({'status': 'DRY_RUN', 'services_stopped': False, 'restore_authorized': False}))
        return 0
    try:
        runtime = DockerRuntime()
        guard = BackupServiceGuard(args.state_dir, runtime)
        if args.recover:
            print(json.dumps({'status': 'RECOVERED' if guard.recover() else 'NO_RECOVERY_NEEDED'}))
            return 0
        if not all((args.env_file, args.ca_file, args.journal_key_file, args.journal_bucket,
                    args.backup_bucket, args.output_dir)) or args.journal_bucket == args.backup_bucket:
            raise ScheduledBackupError('Distinct journal and backup buckets and private inputs are required')
        if args.journal_witness_bucket and args.journal_witness_bucket in (args.journal_bucket, args.backup_bucket):
            raise ScheduledBackupError('Witness must use a distinct bucket')
        require_backup_disk_headroom(args.output_dir)
        # SQLAlchemy async needs this optional dependency; fail before stopping
        # either service if the backup host environment is incomplete.
        import greenlet  # noqa: F401
        env_bytes = private_file(args.env_file, max_bytes=1024 * 1024)
        key = private_file(args.journal_key_file, max_bytes=32)
        if len(key) != 32:
            raise ScheduledBackupError('Journal key must be exactly 32 bytes')
        # dotenv_values accepts a stream so checked file bytes are parsed only once.
        import io
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
        if external_infrastructure_errors(values) or any(not present(values.get(name)) for name in (
            'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_BUCKET',
        )):
            raise ScheduledBackupError('External backup configuration is invalid')
        ca_stat = args.ca_file.lstat()
        if (not stat.S_ISREG(ca_stat.st_mode) or stat.S_ISLNK(ca_stat.st_mode)
                or ca_stat.st_uid != os.geteuid() or ca_stat.st_mode & 0o022):
            raise ScheduledBackupError('A valid provider CA is required')
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
        source = backup_api_source(values['API_IMAGE'], mirrored=bool(args.journal_witness_bucket or any(s3_values.values())))
        sys.path.insert(0, str(source))
        from src.core.database import AsyncSessionLocal, configure_for_worker
        from src.services.privacy_journal_gcs import application_default_token
        from src.services.privacy_journal_verify import verify_current_outbox

        configure_for_worker()  # Separate asyncio.run calls must not reuse an event loop's pool.
        journal, journal_store = build_backup_journal(args.journal_bucket, args.journal_witness_bucket,
                                                       s3_values, values, key)
        backup_store = GCSBackupStore(args.backup_bucket, application_default_token)
        environment = database_environment(values, args.ca_file)
        query = ['psql', '-X', '--no-password', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c']

        def verify_idle():
            assert_runtime_journal_binding(runtime, args.journal_bucket, args.journal_witness_bucket, s3_values)
            assert_runtime_media_binding(runtime, values)
            assert_runtime_database_binding(runtime, values, args.ca_file)
            for name, container in (('API_IMAGE', 'asb-pilot-api'), ('WORKER_IMAGE', 'asb-pilot-worker')):
                image_id = runtime._run(['inspect', '--format', '{{.Image}}', container], timeout=15)
                if values[name] != 'local-image@' + image_id:
                    raise ScheduledBackupError('Container image changed during backup preflight')
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
                    return create_backup(values, args.output_dir, args.ca_file, fence=fence)

                def verify(result):
                    fence.verify()
                    with closing(storage_client(values)) as client:
                        observed = inventory_fingerprint(inventory(client, values['S3_BUCKET']))
                    if observed != result.get('media_inventory_sha256'):
                        raise ScheduledBackupError('Media inventory changed before backup publication')
                    fence.verify()

                yield capture, verify

        try:
            result = run_guarded_backup(guard=guard, verify_idle=verify_idle, preflight_idle=verify_idle,
                verify_journal=verify_journal,
                publication_boundary=publication_boundary,
                output_dir=args.output_dir, store=backup_store, run_id=uuid.uuid4().hex)
            record_success(args.state_dir)
        finally:
            journal_store.close()
            backup_store.close()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        # Commands/provider responses can contain credentials and child data.
        import traceback
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        print(json.dumps({'status': 'FAILED', 'restore_authorized': False,
                          'error_type': type(exc).__name__, 'error_location': f'{Path(frame.filename).name}:{frame.lineno}',
                          'message': 'Backup did not complete; check restricted operator logs and recovery marker.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
