"""Pinned production provider cutover entry point.

Default mode is read-only preflight. `--execute` creates stopped owned
candidates and runs the drained state machine. Any uncertain daemon operation
leaves its durable marker; the tool never falls back to the exposed old key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import urllib.request
import uuid

import provider_candidate_stage as stage
from provider_config_overlay import build_overlay
from provider_cutover import _absent, _lock, _sync_dir
from provider_cutover_drained import _run
from provider_cutover_journal import run_journaled
from provider_cutover_production_adapter import HTTPS_IP, KEY_PATH, OVERLAY_PATH, STATE, ProductionAdapter, _systemd_show
from provider_cutover_production_guards import verify_installed_guard_files, verify_loaded_units
from provider_cutover_production_runtime import API_IMAGE, OLD_API, OLD_WORKER, WORKER_IMAGE

INSTANCE = '1428786032988053776'
PROJECT = 'gen-lang-client-0308507618'
ZONE = 'us-central1-c'
VM_NAME = 'asb-free-test'
CONFIG_SHA256 = 'e687747a95308a4168609c415cc2e2c259e88e1c64fe0d9cc16d653fb3029f13'
ENV_FILE = Path('/etc/ai-story-book/pilot/private/pilot-privacy.env')
BACKUP = Path('/var/lib/ai-story-book/backup-state')
OTHER_MARKERS = [BACKUP / 'restart-required.json', Path('/var/lib/ai-story-book/privacy-deploy/rollback.json'),
                 Path('/var/lib/ai-story-book/narration-deploy/narration-recovery.json'), STATE / 'docker-mutation.json',
                 Path('/var/lib/ai-story-book/provider-install/activation.json')]


class EntryError(RuntimeError):
    pass


def _metadata(path):
    if path not in ('instance/id', 'instance/name', 'instance/zone', 'project/project-id',
                    'instance/network-interfaces/0/access-configs/0/external-ip'):
        raise EntryError('Unexpected instance identity field')
    try:
        request = urllib.request.Request('http://metadata.google.internal/computeMetadata/v1/' + path,
                                         headers={'Metadata-Flavor': 'Google'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            if response.status != 200 or response.headers.get('Metadata-Flavor') != 'Google':
                raise ValueError()
            return response.read(512).decode('ascii').strip()
    except Exception:
        raise EntryError('Google instance identity is unavailable') from None


def verify_instance():
    if (os.geteuid() != 0 or _metadata('instance/id') != INSTANCE or _metadata('instance/name') != VM_NAME
            or _metadata('project/project-id') != PROJECT
            or _metadata('instance/network-interfaces/0/access-configs/0/external-ip') != HTTPS_IP
            or _metadata('instance/zone').rsplit('/', 1)[-1] != ZONE):
        raise EntryError('Google instance identity does not match the pinned pilot')


def _read_env():
    fd = None
    try:
        fd = os.open(ENV_FILE, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0))
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_nlink != 1
                or before.st_mode & 0o077 or not 0 < before.st_size <= 512 * 1024):
            raise ValueError()
        data = bytearray()
        while True:
            part = os.read(fd, 65536)
            if not part:
                break
            data.extend(part)
            if len(data) > 512 * 1024:
                raise ValueError()
        after = os.fstat(fd)
        if (len(data) != before.st_size or any(getattr(before, field) != getattr(after, field) for field in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
            raise ValueError()
        stage._source_env(bytes(data))
        return bytes(data)
    except Exception:
        raise EntryError('Private pilot environment is unavailable') from None
    finally:
        if fd is not None:
            os.close(fd)


def _expected_overlay():
    try:
        result = subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
            'exec', OLD_API, 'cat', '/app/src/core/config.py'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=30, check=False, env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        if result.returncode or len(result.stdout) > 512 * 1024:
            raise ValueError()
        return build_overlay(result.stdout, CONFIG_SHA256)
    except Exception:
        raise EntryError('Pinned production config is unavailable') from None


def _install_overlay_if_absent(expected):
    """Publish a complete fsynced overlay without replacing any existing path."""
    path = Path(OVERLAY_PATH)
    digest = hashlib.sha256(expected).hexdigest()
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = '.config-' + uuid.uuid4().hex + '.tmp'
        created = False
        try:
            directory = os.fstat(directory_fd)
            if directory.st_uid != 0 or directory.st_mode & 0o077:
                raise ValueError()
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory_fd)
                created = True
                try:
                    os.fchown(fd, 1000, 1000)
                    data = memoryview(expected)
                    while data:
                        count = os.write(fd, data)
                        if count <= 0:
                            raise ValueError()
                        data = data[count:]
                    os.fsync(fd)
                finally:
                    os.close(fd)
                try:
                    # link creates the final name only if absent; it cannot
                    # replace an existing user/operation-owned configuration.
                    os.link(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                            follow_symlinks=False)
                    os.fsync(directory_fd)
                except FileExistsError:
                    pass
            finally:
                if created:
                    os.unlink(temporary, dir_fd=directory_fd)
                    os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        stage.capture_bound_file_evidence(overlay_path=OVERLAY_PATH, overlay_sha256=digest, key_path=KEY_PATH)
        return digest
    except Exception:
        raise EntryError('Provider key or config overlay is unavailable') from None


def _write_candidate_owner(record):
    path = STATE / 'candidate-owner.json'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        content = memoryview((json.dumps(record, sort_keys=True) + '\n').encode())
        while content:
            count = os.write(fd, content)
            if count <= 0:
                raise EntryError('Candidate ownership could not be recorded')
            content = content[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_dir(STATE)


def run(*, execute=False):
    verify_instance()
    verify_installed_guard_files()
    verify_loaded_units(_systemd_show)
    environment = _read_env()
    overlay = _expected_overlay()
    if not execute:
        # This mode intentionally does not install the overlay or start probes.
        return {'status': 'READ_ONLY_PREFLIGHT_PASSED', 'production_changed': False,
                'cutover_ready': False}
    transaction = uuid.uuid4().hex
    if not re.fullmatch(r'[0-9a-f]{32}', transaction):
        raise EntryError('Transaction identity is invalid')
    lock = _lock(BACKUP / 'backup.lock')
    results = {}
    stage_runtime = stage.DockerStageRuntime()
    images = {'api': API_IMAGE, 'worker': WORKER_IMAGE}
    try:
        _absent(Path('/var/lib/ai-story-book/provider-install/activation.json'))
        overlay_sha = _install_overlay_if_absent(overlay)
        def create():
            results['stage'] = stage.stage_candidates(runtime=stage_runtime,
                old_ids={'api': OLD_API, 'worker': OLD_WORKER}, image_ids=images,
                environment=environment, overlay_path=OVERLAY_PATH, overlay_sha256=overlay_sha,
                key_path=KEY_PATH, transaction_id=transaction, lock_fd=lock, journaled_create=True)
        def confirm():
            ids = results['stage']['ids']
            stage.verify_staged(runtime=stage_runtime, ids=ids, image_ids=images, environment=environment,
                overlay_path=OVERLAY_PATH, overlay_sha256=overlay_sha, key_path=KEY_PATH,
                transaction_id=transaction, lock_fd=lock, candidate_create_in_progress=True)
            _write_candidate_owner({'version': 1, 'transaction': transaction, 'containers': ids})
            return True
        run_journaled(STATE, transaction=transaction, action='candidate-create', container=OLD_API,
                      execute=create, verify=confirm)
    finally:
        os.close(lock)
    ids = results['stage']['ids']
    pinned_images = {'old_api': API_IMAGE, 'new_api': API_IMAGE, 'old_worker': WORKER_IMAGE, 'new_worker': WORKER_IMAGE}
    runtime = ProductionAdapter(ids=ids, transaction=transaction, environment=environment, overlay_sha256=overlay_sha)
    return _run(state_dir=STATE, backup_dir=BACKUP, ids=ids, images=pinned_images,
                other_markers=OTHER_MARKERS, runtime=runtime, production=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Run the pinned cutover after all checks pass')
    args = parser.parse_args()
    try:
        result = run(execute=args.execute)
    except BaseException:
        print(json.dumps({'status': 'FAILED_OR_INDETERMINATE', 'recovery_markers_must_be_preserved': True}))
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
