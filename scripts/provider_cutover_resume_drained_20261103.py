"""Resume the pinned 2026-11-03 cutover after API and nginx were drained.

This accepts only the owned recovery marker and exact stopped candidates. It
never creates candidates or restarts an old container. The default verifies
only the recovery record; --execute holds both locks for the full continuation.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile

import provider_candidate_stage as stage
import provider_cutover_portless_exec as portless
from provider_cutover import _POST_NAMES, _PRE_NAMES, _absent, _assert_slot, _lock, _read_marker, _sync_dir
from provider_cutover_production_adapter import KEY_PATH, OVERLAY_PATH, STATE, ProductionAdapter, _systemd_show
from provider_config_overlay import build_overlay
from provider_cutover_production_entry import BACKUP, CONFIG_SHA256, OTHER_MARKERS, _read_env, verify_instance
from provider_cutover_production_guards import verify_installed_guard_files, verify_loaded_units
from provider_cutover_production_runtime import API_IMAGE, OLD_API, OLD_WORKER, WORKER_IMAGE
from provider_cutover_resume_owned_20261103 import NEW_API, NEW_WORKER


class ResumeError(RuntimeError):
    pass


def _expected_overlay_from_stopped_api():
    """Read, never execute or extract, the pinned original config from Docker."""
    try:
        result = subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
            'cp', OLD_API + ':/app/src/core/config.py', '-'], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=30, check=False, env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        if result.returncode or not 0 < len(result.stdout) <= 1024 * 1024:
            raise ValueError()
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:') as archive:
            members = archive.getmembers()
            if (len(members) != 1 or members[0].name != 'config.py' or not members[0].isfile()
                    or not 0 < members[0].size <= 512 * 1024):
                raise ValueError()
            fileobj = archive.extractfile(members[0])
            if fileobj is None:
                raise ValueError()
            source = fileobj.read(512 * 1024 + 1)
        return build_overlay(source, CONFIG_SHA256)
    except Exception:
        raise ResumeError('Pinned original config is unavailable') from None


class DrainedRecoveryAdapter(ProductionAdapter):
    """Admit only the specific pre-worker-stop recovery state."""

    def _verify_stage(self, ids, *, lock_fd, old_restart):
        if old_restart != 'no' or ids != self.ids:
            raise ResumeError('Recovery state does not match')
        verify_installed_guard_files()
        verify_loaded_units(_systemd_show)
        portless._source('provider_cutover_probe.py', portless.PROBE_SHA256)
        portless._source('provider_cutover_queue_probe.py', portless.QUEUE_SHA256)
        stage.verify_staged(runtime=self.stage_runtime, ids=ids, image_ids=self.image_ids,
            environment=self.environment, overlay_path=OVERLAY_PATH, overlay_sha256=self.overlay_sha256,
            key_path=KEY_PATH, transaction_id=self.transaction, lock_fd=lock_fd, old_restart='no',
            marker_state='owned', expected_candidate_owner=self.candidate_owner,
            expected_probe_owner=self.probe_owner, old_running={'api': False, 'worker': True})
        old_api = self.stage_runtime.inspect(ids['old_api'])
        if (old_api['State'].get('ExitCode') != 0 or old_api['State'].get('OOMKilled') is not False
                or old_api['State'].get('Error') != ''):
            raise ResumeError('Old API did not stop cleanly')
        worker = self.stage_runtime.inspect(ids['old_worker'])
        # A timed-out docker exec can continue inside the worker. Its completion
        # must be known before creating another queue probe.
        if 'ExecIDs' not in worker or worker['ExecIDs'] not in (None, []):
            raise ResumeError('An earlier worker exec is still present')
        candidate = self.stage_runtime.inspect(ids['new_api'])
        probe = self.stage_runtime.inspect(self.probe_id)
        stage._probe_contract(probe, identifier=self.probe_id, image_id=API_IMAGE,
            transaction_id=self.transaction, candidate=candidate, overlay_path=OVERLAY_PATH, key_path=KEY_PATH)
        proxy = self._proxy()
        if proxy['running'] is not False or proxy['restart_policy'] != 'no':
            raise ResumeError('Public ingress is not stopped')


def _finish(runtime, ids, images):
    """Continue after the old API stopped; caller owns both locks and marker."""
    runtime.drain_worker_and_queues()
    runtime.stop(ids['old_worker'])
    _assert_slot(runtime, ids['old_worker'], name=_PRE_NAMES['old_worker'], image=images['old_worker'],
                 running=False, restart='no')
    runtime.probe_equivalent_provider(ids['new_api'])
    runtime.assert_no_unresolved_daemon_operations()
    for slot in ('old_api', 'old_worker', 'new_api', 'new_worker'):
        runtime.rename(ids[slot], _POST_NAMES[slot])
        _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot], running=False, restart='no')
    runtime.start(ids['new_api'])
    _assert_slot(runtime, ids['new_api'], name=_POST_NAMES['new_api'], image=images['new_api'],
                 running=True, restart='no')
    runtime.assert_api_ready(ids['new_api'])
    runtime.start(ids['new_worker'])
    _assert_slot(runtime, ids['new_worker'], name=_POST_NAMES['new_worker'], image=images['new_worker'],
                 running=True, restart='no')
    runtime.assert_worker_healthy(ids['new_worker'])
    runtime.assert_no_unresolved_daemon_operations()
    for slot in ('new_api', 'new_worker'):
        runtime.enable_restart(ids[slot])
        _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot],
                     running=True, restart='unless-stopped')
    runtime.reload_proxy()
    runtime.open_ingress()
    runtime.assert_live_candidate(ids['new_api'], ids['new_worker'])
    runtime.assert_no_unresolved_daemon_operations()
    for slot in ('old_api', 'old_worker'):
        _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot], running=False, restart='no')
    for slot in ('new_api', 'new_worker'):
        _assert_slot(runtime, ids[slot], name=_POST_NAMES[slot], image=images[slot],
                     running=True, restart='unless-stopped')
    runtime.complete_candidate_owner()
    (STATE / 'recovery.json').unlink()
    _sync_dir(STATE)
    return {'status': 'PRODUCTION_CUTOVER_PASSED', 'production_authorized': True}


def run(*, transaction, probe_id, execute=False):
    if (not isinstance(transaction, str) or not re.fullmatch(r'[0-9a-f]{32}', transaction)
            or not isinstance(probe_id, str) or not re.fullmatch(r'[0-9a-f]{64}', probe_id)):
        raise ResumeError('Recovery identity is invalid')
    ids = {'old_api': OLD_API, 'old_worker': OLD_WORKER, 'new_api': NEW_API, 'new_worker': NEW_WORKER}
    images = {'old_api': API_IMAGE, 'new_api': API_IMAGE, 'old_worker': WORKER_IMAGE, 'new_worker': WORKER_IMAGE}
    if probe_id in ids.values():
        raise ResumeError('Probe identity is invalid')
    verify_instance()
    verify_installed_guard_files()
    verify_loaded_units(_systemd_show)
    if _read_marker(STATE) != ids:
        raise ResumeError('Recovery marker does not match')
    owner = stage._candidate_owner_record(transaction_id=transaction, ids=ids)
    probe_owner = stage._probe_owner_record(transaction_id=transaction, candidate_id=NEW_API,
                                             probe_id=probe_id, image_id=API_IMAGE)
    stage._read_owned_record(STATE / 'candidate-owner.json', owner)
    stage._read_owned_record(STATE / 'probe-owner.json', probe_owner)
    environment = _read_env()
    overlay_sha = hashlib.sha256(_expected_overlay_from_stopped_api()).hexdigest()
    evidence = stage.capture_bound_file_evidence(overlay_path=OVERLAY_PATH, overlay_sha256=overlay_sha, key_path=KEY_PATH)
    if not execute:
        return {'status': 'RECOVERY_RECORD_READ_ONLY_CHECK_PASSED', 'production_changed': False,
                'cutover_ready': False}
    backup_lock = _lock(BACKUP / 'backup.lock')
    recovery_lock = None
    runtime = None
    started = False
    try:
        recovery_lock = _lock(STATE / 'recovery.lock')
        for marker in OTHER_MARKERS:
            _absent(marker)
        if _read_marker(STATE) != ids:
            raise ResumeError('Recovery marker changed')
        runtime = DrainedRecoveryAdapter(ids=ids, transaction=transaction, environment=environment,
                                         overlay_sha256=overlay_sha)
        runtime.probe_id, runtime.probe_owner = probe_id, probe_owner
        runtime.lock_fd, runtime.evidence = backup_lock, evidence
        runtime.assert_candidate_and_interlocks(ids, images, lock_fd=backup_lock, old_restart='no')
        runtime.assert_no_unresolved_daemon_operations()
        started = True
        return _finish(runtime, ids, images)
    except BaseException:
        if started:
            try:
                runtime.preserve_accepted_work_and_quarantine(ids)
            except Exception:
                pass
        raise ResumeError('Recovery failed; durable markers must be preserved') from None
    finally:
        if recovery_lock is not None:
            os.close(recovery_lock)
        os.close(backup_lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transaction', required=True)
    parser.add_argument('--probe-id', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        result = run(transaction=args.transaction, probe_id=args.probe_id, execute=args.execute)
    except BaseException:
        print(json.dumps({'status': 'FAILED_OR_INDETERMINATE', 'recovery_markers_must_be_preserved': True}))
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
