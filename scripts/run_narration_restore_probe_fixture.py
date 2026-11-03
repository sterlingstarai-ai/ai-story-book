"""Run the offline archive probe with a disposable synthetic PostgreSQL DB.

This experiment uses no production data, credentials, remote resources or
existing volumes. It never authorizes restoring or publishing a service.
"""
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

from narration_restore_probe import RestoreProbeError, probe_database_archive
from run_offline_restore_rehearsal import local_daemon


def _run(args, *, timeout=90):
    return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout


def main():
    local_daemon()
    image = json.loads(_run(['docker', 'image', 'inspect', 'postgres:16']))[0]['Id']
    name = 'asb-db-probe-fixture-' + secrets.token_hex(16)
    container_id = None
    result = {'status': 'FAILED', 'synthetic_only': True, 'restore_authorized': False}
    try:
        container_id = _run(['docker', 'run', '-d', '--name', name, '--network', 'none', '--log-driver', 'none',
                             '--tmpfs', '/var/lib/postgresql/data:rw,size=256m',
                             '-e', 'POSTGRES_PASSWORD=synthetic-only', image]).decode().strip()
        sql = ("CREATE TABLE IF NOT EXISTS public.alembic_version (version_num varchar(32) NOT NULL); "
               "INSERT INTO public.alembic_version SELECT '5de7a40b6c12' "
               "WHERE NOT EXISTS (SELECT 1 FROM public.alembic_version); "
               "CREATE TABLE IF NOT EXISTS public.probe_sentinel (id integer)")
        archive = None
        # The official image briefly starts and stops a bootstrap server; wait
        # until a complete pg_dump is available from the final server.
        for _ in range(100):
            seed = subprocess.run(['docker', 'exec', '-u', 'postgres', container_id, 'psql', '-d', 'postgres',
                                   '-v', 'ON_ERROR_STOP=1', '-c', sql], capture_output=True, timeout=10)
            if seed.returncode == 0:
                dump = subprocess.run(['docker', 'exec', '-u', 'postgres', container_id, 'pg_dump', '-Fc',
                                       '-n', 'public', 'postgres'], capture_output=True, timeout=30)
                if dump.returncode == 0:
                    archive = dump.stdout
                    break
            time.sleep(.2)
        if not archive:
            raise RuntimeError('Synthetic source did not start')
        with tempfile.TemporaryDirectory(prefix='asb-db-probe-fixture-') as temp:
            folder = Path(temp)
            (folder / 'objects').mkdir(mode=0o700)
            (folder / 'database.dump').write_bytes(archive)
            manifest = {'format_version': 1, 'database_scope': 'public', 'restore_verified': False,
                        'alembic_revision': '5de7a40b6c12',
                        'requires_latest_deletion_and_identity_revocations': True,
                        'database': {'file': 'database.dump', 'size': len(archive),
                                     'sha256': hashlib.sha256(archive).hexdigest()}, 'objects': []}
            (folder / 'manifest.json').write_text(json.dumps(manifest))
            positive = probe_database_archive(folder, image_id=image, expected_revision='5de7a40b6c12')
            if positive['status'] != 'OFFLINE_DATABASE_RESTORED' or positive['restore_authorized'] is not False:
                raise RuntimeError('Synthetic restore probe failed')
            manifest['alembic_revision'] = 'aaaaaaaaaaaa'
            (folder / 'manifest.json').write_text(json.dumps(manifest))
            try:
                probe_database_archive(folder, image_id=image, expected_revision='aaaaaaaaaaaa')
            except RestoreProbeError:
                pass
            else:
                raise RuntimeError('Mismatched restored revision was not rejected')
        result.update(status='PASSED', verified_database_restore=True, mismatched_revision_rejected=True,
                      media_restore_verified=False, migration_authorized=False)
    finally:
        if container_id:
            _run(['docker', 'rm', '-f', container_id], timeout=30)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
