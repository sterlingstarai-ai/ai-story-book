"""Deploy the explicitly identified private pilot images with boot-time rollback.

A durable marker remains until readiness and restart policies are confirmed.
This does not authorize a production release or a backup restoration.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from backup_service_guard import BackupServiceGuard, DockerRuntime, assert_no_narration_recovery
from run_scheduled_backup import assert_idle_worker

STATE = Path('/var/lib/ai-story-book/privacy-deploy')
MARKER = STATE / 'rollback.json'
BACKUP_STATE = Path('/var/lib/ai-story-book/backup-state')
API = 'asb-pilot-api'
WORKER = 'asb-pilot-worker'
NEXT = {API: 'asb-privacy-next-api', WORKER: 'asb-privacy-next-worker'}
OLD = {API: 'asb-pilot-api-before-privacy', WORKER: 'asb-pilot-worker-before-privacy'}
IMAGES = {API: 'sha256:47dcb13c52033638740a93463cded3d61c28bc9c85ccfd7ce4932e681be139b1', WORKER: 'sha256:75a13c62b099d33f5d23ef4b56a6a41cde8ac0f5aff1b6828a65baf5c528f638'}
EXPECTED_OLD = {API: 'sha256:559f96f60c7707a478be6bb2a9cb2e22bae8e19d9ce7430796063ae8cabf3eb1', WORKER: 'sha256:aeb5e569b35d53221aaee7ec203303977a6bcdf77156a23d3c56b8ca11366a5f'}


def docker(*args):
    return subprocess.run(['docker', *args], check=True, text=True, capture_output=True, timeout=120).stdout.strip()


def inspect(name, fmt):
    return docker('inspect', '--format', fmt, name)


def exists(name):
    return subprocess.run(['docker', 'inspect', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30).returncode == 0


def sync_dir():
    fd = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rollback():
    if not MARKER.exists():
        return False
    # Coordinate with narration arming and the backup recovery unit. Checking
    # the marker without the shared lock would permit a restart race.
    guard = BackupServiceGuard(BACKUP_STATE, DockerRuntime())
    fd = guard._locked()
    try:
        assert_no_narration_recovery()
        return _rollback_locked()
    finally:
        os.close(fd)


def _rollback_locked():
    marker = json.loads(MARKER.read_text())
    if set(marker) != {'version', 'old', 'new'} or marker['version'] != 1:
        raise RuntimeError('Invalid rollback marker')
    for collection in ('old', 'new'):
        if set(marker[collection]) != {API, WORKER} or any(not re.fullmatch('[0-9a-f]{64}', x) for x in marker[collection].values()):
            raise RuntimeError('Invalid container identity')
    for name in (API, WORKER):
        old_id, new_id = marker['old'][name], marker['new'][name]
        if not exists(old_id) or not exists(new_id):
            raise RuntimeError('Recorded container missing')
        current_name = inspect(new_id, '{{.Name}}').lstrip('/')
        if current_name not in (name, NEXT[name]):
            raise RuntimeError('Unexpected replacement container name')
        if inspect(new_id, '{{.State.Running}}') == 'true':
            docker('stop', '--time', '60', new_id)
        docker('update', '--restart=no', new_id)
        if current_name == name:
            if exists(NEXT[name]):
                raise RuntimeError('Replacement staging name occupied')
            docker('rename', new_id, NEXT[name])
        old_name = inspect(old_id, '{{.Name}}').lstrip('/')
        if old_name not in (name, OLD[name]):
            raise RuntimeError('Unexpected original container name')
        if old_name == OLD[name]:
            if exists(name):
                raise RuntimeError('Original name occupied')
            docker('rename', old_id, name)
        docker('update', '--restart=unless-stopped', old_id)
    for name in (WORKER, API):
        if inspect(marker['old'][name], '{{.State.Running}}') != 'true':
            docker('start', marker['old'][name])
    docker('exec', 'asb-pilot-nginx', 'nginx', '-s', 'reload')
    MARKER.unlink()
    sync_dir()
    return True


def deploy():
    # Keep staging, durable marker publication and swap under the same lock
    # used by narration arming and backup recovery, eliminating check races.
    runtime = DockerRuntime()
    guard = BackupServiceGuard(BACKUP_STATE, runtime)
    fd = guard._locked()
    try:
        assert_no_narration_recovery()
        return _deploy_locked(runtime, guard)
    finally:
        os.close(fd)


def _deploy_locked(runtime, guard):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = STATE.lstat()
    if not STATE.is_dir() or STATE.is_symlink() or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise RuntimeError('Invalid state directory')
    if MARKER.exists() or MARKER.is_symlink():
        raise RuntimeError('Previous deployment needs recovery')
    old, new = {}, {}
    marker_published = False
    for name in (API, WORKER):
        if exists(NEXT[name]) or exists(OLD[name]):
            raise RuntimeError('Staging names already exist')
        if inspect(name, '{{.Image}}') != EXPECTED_OLD[name] or inspect(name, '{{.State.Running}}') != 'true':
            raise RuntimeError('Original container is not the expected running image')
        old[name] = inspect(name, '{{.Id}}')
    # A slow or unresponsive control probe must fail before stopping admission.
    # The guard repeats this check after admission stops to close the race.
    assert_idle_worker(runtime)
    common = ['--restart=no', '--network', 'asb-pilot-net', '--env-file', '/etc/ai-story-book/pilot/private/pilot-privacy.env', '-v', '/etc/ai-story-book/pilot/private/neon-ca.pem:/run/storybook-certs/neon-ca.pem:ro', '-v', '/etc/ai-story-book/pilot/guard:/guard:rw', '-v', '/etc/ai-story-book/pilot/private/privacy-journal-app.key:/run/storybook-secrets/journal.key:ro', '--entrypoint', 'python']
    try:
        new[API] = docker('create', '--name', NEXT[API], *common, '-p', '127.0.0.1:18081:8000', IMAGES[API], '/guard/entry.py', 'uvicorn', 'src.main:app', '--host', '0.0.0.0', '--port', '8000', '--no-access-log')
        new[WORKER] = docker('create', '--name', NEXT[WORKER], *common, IMAGES[WORKER], '/guard/entry.py', 'celery', '-A', 'src.worker', 'worker', '--loglevel=warning', '--concurrency=1')
        if any(not re.fullmatch('[0-9a-f]{64}', x) for x in (*old.values(), *new.values())):
            raise RuntimeError('Invalid container identity')
        staging_marker = STATE / 'rollback.pending'
        fd = os.open(staging_marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'version': 1, 'old': old, 'new': new}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging_marker, MARKER, follow_symlinks=False)
        marker_published = True
        staging_marker.unlink()
        sync_dir()
        def swap():
            for name in (API, WORKER):
                docker('update', '--restart=no', old[name])
                docker('rename', old[name], OLD[name])
                docker('rename', new[name], name)
        guard._run_unlocked(verify_idle=lambda: assert_idle_worker(runtime), backup=swap)
        # nginx re-resolves Docker DNS in guard; allow services to initialise.
        for _ in range(36):
            result = subprocess.run(['curl', '--silent', '--fail', '--max-time', '5', '--output', '/dev/null', 'http://127.0.0.1:18081/health/ready'], timeout=8)
            if result.returncode == 0:
                break
            time.sleep(5)
        else:
            raise RuntimeError('New API readiness failed')
        assert_idle_worker(runtime)
        for name in (API, WORKER):
            docker('update', '--restart=unless-stopped', new[name])
        MARKER.unlink()
        sync_dir()
        return True
    except BaseException:
        if MARKER.exists():
            assert_no_narration_recovery()
            _rollback_locked()
        elif not marker_published:
            for cid in new.values():
                if re.fullmatch('[0-9a-f]{64}', cid) and exists(cid):
                    docker('rm', cid)
        raise


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--execute', action='store_true')
    group.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    try:
        changed = deploy() if args.execute else rollback()
        print(json.dumps({'status': 'DEPLOYED' if args.execute else ('RECOVERED' if changed else 'NO_RECOVERY_NEEDED')}))
        return 0
    except Exception:
        print(json.dumps({'status': 'FAILED_OR_RECOVERY_REQUIRED'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
