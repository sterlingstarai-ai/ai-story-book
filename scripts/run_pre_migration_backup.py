"""One explicitly requested backup of the exact legacy pilot before migration.

Never migrates or restores. It uses the existing crash-recovery guard and only
accepts the known pre-journal revision, drained worker and empty purge queue.
"""

import argparse
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from dotenv import dotenv_values

from backup_external import BackupError, database_environment
from backup_service_guard import BackupServiceGuard, DockerRuntime, GuardError
from bootstrap_privacy_backup import assert_legacy_quiescent, create_pre_migration_backup
from final_external_preflight import external_infrastructure_errors, present
from postgres_backup_fence import BackupFenceError, PostgresBackupFence
from publish_backup_gcs import BackupPublishError, GCSBackupStore, publish_verified_backup
from run_scheduled_backup import ScheduledBackupError, private_file, assert_idle_worker

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--ca-file', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--backup-bucket', required=True)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'DRY_RUN', 'services_stopped': False}))
        return 0
    try:
        raw_env = private_file(args.env_file, max_bytes=1024 * 1024)
        values = {k: v or '' for k, v in dotenv_values(stream=io.StringIO(raw_env.decode()), interpolate=False).items()}
        runtime = DockerRuntime()
        for name, container in (('API_IMAGE', 'asb-pilot-api'), ('WORKER_IMAGE', 'asb-pilot-worker')):
            image_id = runtime._run(['inspect', '--format', '{{.Image}}', container], timeout=15)
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
                raise ValueError('invalid image identity')
            values[name] = 'local-image@' + image_id
        if external_infrastructure_errors(values) or any(not present(values.get(name)) for name in (
            'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_BUCKET',
        )):
            raise ValueError('invalid source settings')
        ca = args.ca_file.lstat()
        if not stat.S_ISREG(ca.st_mode) or ca.st_uid != os.geteuid() or ca.st_mode & 0o022:
            raise ValueError('invalid CA')
        sys.path.insert(0, str(ROOT / 'apps/api'))
        from src.services.privacy_journal_gcs import application_default_token

        environment = database_environment(values, args.ca_file)
        query = ['psql', '-X', '--no-password', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c']
        guard = BackupServiceGuard(args.state_dir, runtime)
        store = GCSBackupStore(args.backup_bucket, application_default_token)

        def idle():
            assert_legacy_quiescent(environment, query)
            assert_idle_worker(runtime)

        def take_and_publish():
            with PostgresBackupFence(environment) as fence:
                result = create_pre_migration_backup(values, args.output_dir, args.ca_file, fence=fence)
            folder = args.output_dir / result['backup_set']
            return publish_verified_backup(folder, uuid.uuid4().hex, store)

        try:
            result = guard.run(verify_idle=idle, backup=take_and_publish)
        finally:
            store.close()
        print(json.dumps({'status': result['status'], 'restore_authorized': False}))
        return 0
    except Exception as exc:
        # These project-defined messages are deliberately free of credentials.
        detail = str(exc) if isinstance(exc, (BackupError, BackupFenceError, BackupPublishError, GuardError, ScheduledBackupError)) else type(exc).__name__
        print(json.dumps({'status': 'FAILED', 'restore_authorized': False,
                          'message': 'Bootstrap backup did not complete; services require recovery check.',
                          'reason': detail}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
