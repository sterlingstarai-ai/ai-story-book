"""Offline database backup probe; never exposes or authorizes a restore.

The caller must supply a trusted, locally available PostgreSQL 16 image ID.
This verifies one bounded archive in an ephemeral network-none container; it
does not prove privacy-journal completeness, media recovery, or release safety.
Docker daemon, image provenance, and the host remain trusted dependencies.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

from verify_backup_set import verify

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


class RestoreProbeError(RuntimeError):
    pass


def _run(args, *, input_bytes=None, timeout=60):
    try:
        result = subprocess.run(args, input=input_bytes, capture_output=True, timeout=timeout, check=True)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        # pg_restore failures can include private SQL or row contents.
        raise RestoreProbeError('Offline database probe failed') from None


def _sandbox(container_id, image_id, token):
    output = _run([sys.executable, str(ROOT / 'scripts/check_restore_sandbox.py'),
                   '--container-id', container_id, '--image-id', image_id, '--token', token])
    if json.loads(output) != {'status': 'SANDBOX_CONFIGURATION_MATCHES', 'restore_authorized': False}:
        raise RestoreProbeError('Offline sandbox configuration was not verified')


def probe_database_archive(backup_dir, *, image_id, expected_revision):
    """Restore a validated archive into an isolated temporary PG16 database.

    Expected revision and image ID must come from independently trusted release
    configuration. A successful probe is never permission to open the restored
    database or migrate the original. No backup data is sent to the network.
    """
    if (not isinstance(image_id, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id)
            or not isinstance(expected_revision, str) or not re.fullmatch(r'[0-9a-f]{12}', expected_revision)):
        raise RestoreProbeError('Trusted image and revision identities are required')
    try:
        override = os.environ.get('DOCKER_HOST', '')
        endpoint = json.loads(_run(['docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}']))
        if (override and not override.startswith('unix://')) or not isinstance(endpoint, str) or not endpoint.startswith('unix://'):
            raise RestoreProbeError('A local Docker daemon is required')
        image = json.loads(_run(['docker', 'image', 'inspect', image_id]))
        if not isinstance(image, list) or len(image) != 1 or image[0].get('Id') != image_id:
            raise RestoreProbeError('Trusted local image is missing')
        folder = Path(backup_dir)
        if verify(folder).get('restore_verified') is not False:
            raise RestoreProbeError('Backup checksum validation failed')
        manifest_bytes = (folder / 'manifest.json').read_bytes()
        manifest = json.loads(manifest_bytes)
        if manifest.get('alembic_revision') != expected_revision or manifest.get('restore_verified') is not False:
            raise RestoreProbeError('Backup revision metadata is invalid')
        descriptor = manifest['database']
        if not 0 < descriptor['size'] <= MAX_ARCHIVE_BYTES:
            raise RestoreProbeError('Archive size is outside probe limits')
        archive_path = folder / 'database.dump'
        fd = os.open(archive_path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            before = os.fstat(fd)
            with os.fdopen(fd, 'rb', closefd=False) as source:
                data = source.read(MAX_ARCHIVE_BYTES + 1)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        if (len(data) != descriptor['size'] or hashlib.sha256(data).hexdigest() != descriptor['sha256']
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise RestoreProbeError('Backup archive changed during validation')
    except RestoreProbeError:
        raise
    except Exception:
        raise RestoreProbeError('Backup or sandbox prerequisites failed') from None

    token = secrets.token_hex(16)
    name = 'asb-db-probe-' + token
    container_id = None
    cleanup_ok = False
    run_attempted = False
    try:
        run_attempted = True
        container_id = _run(['docker', 'run', '-d', '--name', name, '--network', 'none', '--read-only',
            '--user', '65534:65534', '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=64m,uid=65534,gid=65534,mode=0700',
            '--tmpfs', '/var/lib/asb-restore:rw,nosuid,nodev,noexec,size=512m,uid=65534,gid=65534,mode=0700',
            '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size=8m,uid=65534,gid=65534,mode=0700',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '128',
            '--memory', '1g', '--memory-swap', '1g', '--log-driver', 'none',
            '--label', 'asb.restore.purpose=offline-candidate', '--label', 'asb.restore.token=' + token,
            '--entrypoint', '/bin/sleep', image_id, '600']).decode().strip()
        if not re.fullmatch('[0-9a-f]{64}', container_id):
            raise RestoreProbeError('Offline container identity is invalid')
        _sandbox(container_id, image_id, token)
        base = ['docker', 'exec', '-e', 'HOME=/tmp', container_id]
        pg = '/usr/lib/postgresql/16/bin/'
        _run(base + [pg + 'initdb', '-D', '/var/lib/asb-restore/pg', '-U', 'probe', '--auth=trust',
                     '--no-locale', '--no-sync'], timeout=90)
        _run(base + [pg + 'pg_ctl', '-D', '/var/lib/asb-restore/pg', '-l', '/tmp/pg.log', '-o',
                     "-c listen_addresses='' -k /tmp -c max_connections=8", '-w', 'start'], timeout=90)
        _run(base + [pg + 'createdb', '-h', '/tmp', '-U', 'probe', 'probe'], timeout=30)
        # pg_dump --schema=public includes CREATE SCHEMA public.  This target
        # database is freshly created inside the verified disposable sandbox.
        _run(base + [pg + 'psql', '-X', '-h', '/tmp', '-U', 'probe', '-d', 'probe',
                     '--set', 'ON_ERROR_STOP=1', '-c', 'DROP SCHEMA public CASCADE'], timeout=30)
        _run(['docker', 'exec', '-i', container_id, pg + 'pg_restore', '-h', '/tmp', '-U', 'probe',
              '-d', 'probe', '--exit-on-error', '--no-owner', '--no-privileges', '--single-transaction'],
             input_bytes=data, timeout=300)
        data = None
        revision = _run(base + [pg + 'psql', '-X', '-h', '/tmp', '-U', 'probe', '-d', 'probe',
            '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c',
            'SELECT version_num FROM public.alembic_version ORDER BY version_num']).decode().strip()
        if revision != expected_revision:
            raise RestoreProbeError('Restored database revision does not match')
        _sandbox(container_id, image_id, token)
        # Recheck the source archive/inventory after restore; this is not a
        # substitute for an external writer fence around the live service.
        if (verify(folder).get('restore_verified') is not False
                or (folder / 'manifest.json').read_bytes() != manifest_bytes):
            raise RestoreProbeError('Backup changed during offline probe')
    except RestoreProbeError:
        raise
    except Exception:
        raise RestoreProbeError('Offline database probe could not be verified') from None
    finally:
        if run_attempted and (not container_id or not re.fullmatch('[0-9a-f]{64}', container_id)):
            try:
                found = _run(['docker', 'ps', '-a', '--no-trunc', '--filter', 'name=^/' + name + '$',
                              '--format', '{{.ID}}']).decode().strip()
                if not found:
                    cleanup_ok = True
                elif re.fullmatch('[0-9a-f]{64}', found):
                    items = json.loads(_run(['docker', 'inspect', found]))
                    item = items[0] if isinstance(items, list) and len(items) == 1 else {}
                    labels = item.get('Config', {}).get('Labels') or {}
                    if (item.get('Image') == image_id and item.get('Name') == '/' + name
                            and labels.get('asb.restore.token') == token
                            and labels.get('asb.restore.purpose') == 'offline-candidate'):
                        container_id = found
            except (RestoreProbeError, ValueError, UnicodeError):
                pass
        if container_id and re.fullmatch('[0-9a-f]{64}', container_id):
            try:
                _run(['docker', 'rm', '-f', container_id], timeout=30)
                cleanup_ok = True
            except RestoreProbeError:
                pass
    if not cleanup_ok:
        raise RestoreProbeError('Offline container cleanup could not be verified')
    return {'status': 'OFFLINE_DATABASE_RESTORED', 'revision': expected_revision,
            'archive_sha256': descriptor['sha256'], 'media_restore_verified': False,
            'restore_authorized': False, 'migration_authorized': False}
