"""Owned Docker-only provider rotation rehearsal; never a deployment tool.

All containers use a pinned local fixture image, network=none and literal dummy
credentials. Ingress and provider checks are synthetic. No real credentials,
services, provider calls, backups or systemd state are read or modified.
"""
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def docker(*args):
    return subprocess.run(['docker', *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=30).stdout.strip()


def _write_marker(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, b'SYNTHETIC_ONLY\n')
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _child(marker, lockfile, ids, target, ready):
    # Lock is shared with the fixture's simulated backup operation.
    lock = os.open(lockfile, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        _write_marker(marker)
        for phase in ('fenced', 'old_stopped', 'new_started', 'verified'):
            if phase == 'old_stopped':
                for identifier in ids[:2]:
                    docker('stop', '--time', '0', identifier)
            elif phase == 'new_started':
                # Synthetic restart failure: only the API starts; worker stays
                # stopped, then the fixture simulates abrupt supervisor loss.
                for identifier in (ids[2:3] if target == 'restart_failed' else ids[2:]):
                    docker('start', identifier)
            if phase == target or (phase == 'new_started' and target == 'restart_failed') or (
                    phase == 'verified' and target == 'probe_failed'):
                ready.set()
                while True:
                    time.sleep(1)
    finally:
        os.close(lock)


def _recover(marker, ids):
    # Simulated boot handler: an armed marker always quarantines every owned
    # fixture container, including the retired-key containers. It never starts.
    if marker.read_bytes() != b'SYNTHETIC_ONLY\n':
        raise RuntimeError('Synthetic marker is invalid')
    for identifier in ids:
        docker('update', '--restart=no', identifier)
        docker('stop', '--time', '0', identifier)
    for identifier in ids:
        info = json.loads(docker('inspect', identifier))[0]
        if info['State']['Running'] or info['HostConfig']['RestartPolicy']['Name'] != 'no':
            raise RuntimeError('Synthetic quarantine failed')
    marker.unlink()


def main():
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise RuntimeError('Docker override is not allowed')
    context = json.loads(docker('context', 'inspect'))
    if not context[0]['Endpoints']['docker']['Host'].startswith('unix://'):
        raise RuntimeError('Only a local Unix Docker daemon is allowed')
    image_id = json.loads(docker('image', 'inspect', 'postgres:16'))[0]['Id']
    if not image_id.startswith('sha256:') or len(image_id) != 71:
        raise RuntimeError('Pinned local fixture image is required')
    prefix = 'asb-provider-rotation-fixture-' + uuid.uuid4().hex[:12]
    ids = []
    process = None
    cleanup_failed = False
    try:
        for slot in ('old-api', 'old-worker', 'new-api', 'new-worker'):
            label = 'synthetic-retired' if slot.startswith('old') else 'synthetic-candidate'
            identifier = docker('create', '--name', prefix + '-' + slot, '--network=none',
                '--restart=no', '--read-only', '--env', 'ASB_FIXTURE_LABEL=' + label,
                '--entrypoint', 'sleep', image_id, '600')
            ids.append(identifier)
            info = json.loads(docker('inspect', identifier))[0]
            if (info['Image'] != image_id or info['HostConfig']['NetworkMode'] != 'none'
                    or not info['HostConfig']['ReadonlyRootfs']):
                raise RuntimeError('Fixture container isolation mismatch')
        with tempfile.TemporaryDirectory(prefix='asb-provider-rotation-') as folder:
            root = Path(folder)
            marker, lockfile = root / 'recovery.marker', root / 'backup.lock'
            completed = []
            for phase in ('fenced', 'old_stopped', 'new_started', 'verified', 'restart_failed', 'probe_failed'):
                for identifier in ids[:2]:
                    docker('start', identifier)
                event = multiprocessing.get_context('fork').Event()
                process = multiprocessing.get_context('fork').Process(
                    target=_child, args=(marker, lockfile, ids, phase, event))
                process.start()
                if not event.wait(30):
                    raise RuntimeError('Fixture stage did not execute')
                lock = os.open(lockfile, os.O_RDWR)
                try:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        raise RuntimeError('Synthetic backup lock was not held')
                finally:
                    os.close(lock)
                process.kill()
                process.join(10)
                if process.is_alive() or not marker.is_file():
                    raise RuntimeError('Synthetic crash marker missing')
                process = None
                _recover(marker, ids)
                completed.append(phase)
        print(json.dumps({'status': 'SYNTHETIC_ROTATION_QUARANTINE_PASSED',
            'stages': completed, 'actual_boot': False, 'real_ingress': False,
            'provider_verified': False, 'deployment_authorized': False}))
    finally:
        if process is not None and process.is_alive():
            process.kill()
            process.join(10)
        for identifier in ids:
            try:
                docker('rm', '-f', identifier)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError('Owned fixture cleanup failed')


if __name__ == '__main__':
    main()
