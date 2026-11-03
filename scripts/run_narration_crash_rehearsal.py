"""Disposable Docker SIGKILL rehearsal; no real DB, provider or reboot.

Four random-name local containers and a private temporary marker directory are
owned by this run. This exercises orchestration and quarantine around fake
backup/migration callbacks; it does not prove systemd boot ordering or a real
database migration. It refuses non-local Docker contexts and image pulling.
"""
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import backup_service_guard
import narration_deploy_safety as safety
import narration_release_orchestrator as release


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True,
                          text=True, timeout=90).stdout.strip()


class SyntheticOperations:
    def __init__(self, runtime, identities, target, reached):
        self.runtime = runtime
        self.identities = identities
        self.target = target
        self.reached = reached

    def __getattr__(self, name):
        allowed = {'preflight', 'stop_and_drain', 'disable_restart', 'backup_and_restore_verify',
                   'migrate', 'start_isolated', 'verify_isolated', 'enable_new_restart',
                   'publish', 'verify_published'}
        if name not in allowed:
            raise AttributeError(name)

        def perform(*_args):
            if name == self.target:
                self.reached.set()
                while True:
                    time.sleep(1)
            if name == 'stop_and_drain':
                for slot in ('old_api', 'old_worker'):
                    self.runtime.stop(self.identities[slot])
            if name == 'disable_restart':
                for identifier in self.identities.values():
                    self.runtime.disable_restart(identifier)
            if name == 'start_isolated':
                for slot in ('new_api', 'new_worker'):
                    docker('start', self.identities[slot])
            return True
        return perform


def _child(state, identities, target, reached):
    runtime = safety.DockerRuntime()
    image_ids = {slot: runtime.inspect(identifier)['image_id'] for slot, identifier in identities.items()}
    release.release(state_dir=state, backup_state_dir=state, identities=identities,
                    image_ids=image_ids, runtime=runtime,
                    operations=SyntheticOperations(runtime, identities, target, reached))


def main():
    # Docker CLI's host override can silently target a real remote daemon.
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise RuntimeError('Explicit Docker host/context is not allowed')
    context = docker('context', 'inspect')
    endpoint = json.loads(context)[0]['Endpoints']['docker']['Host']
    if not endpoint.startswith('unix://'):
        raise RuntimeError('A local Unix Docker daemon is required')
    docker('image', 'inspect', 'postgres:16')  # no implicit pull
    prefix = 'asb-narration-crash-' + uuid.uuid4().hex[:12]
    slots = ['old_api', 'old_worker', 'new_api', 'new_worker']
    identities = {}
    results = []
    child = None
    cleanup_failed = False
    try:
        names = {slot: prefix + '-' + slot.replace('_', '-') for slot in slots}
        safety._SLOTS = {slot: {names[slot]} for slot in slots}
        for slot in slots:
            identities[slot] = docker('create', '--name', names[slot], '--init', '--network', 'none',
                                      '--restart=no', '--tmpfs', '/var/lib/postgresql/data:rw,size=16m',
                                      '--entrypoint', 'sleep', 'postgres:16', '600')
        with tempfile.TemporaryDirectory(prefix='asb-narration-crash-') as directory:
            state = Path(directory)
            safety.BACKUP_STATE = state
            safety.PRIVACY_RECOVERY_MARKER = state / 'privacy-rollback.json'
            release.PRIVACY_RECOVERY_MARKER = safety.PRIVACY_RECOVERY_MARKER
            backup_service_guard.NARRATION_RECOVERY_MARKER = state / 'narration-recovery.json'
            runtime = safety.DockerRuntime()
            for target in ('stop_and_drain', 'backup_and_restore_verify', 'migrate', 'publish'):
                for slot in ('old_api', 'old_worker'):
                    docker('start', identities[slot])
                    docker('update', '--restart=unless-stopped', identities[slot])
                for slot in ('new_api', 'new_worker'):
                    docker('update', '--restart=no', identities[slot])
                reached = multiprocessing.get_context('fork').Event()
                child = multiprocessing.get_context('fork').Process(
                    target=_child, args=(state, identities, target, reached))
                child.start()
                if not reached.wait(60):
                    child.kill()
                    child.join(10)
                    raise RuntimeError('Synthetic stage was not reached')
                child.kill()  # simulate an uncatchable process loss
                child.join(10)
                if child.is_alive() or not (state / 'narration-recovery.json').is_file():
                    raise RuntimeError('Interrupted release marker was not retained')
                child = None
                outcome = safety.recover_if_armed(state, runtime)
                if outcome['status'] != 'QUARANTINED':
                    raise RuntimeError('Quarantine failed')
                for identifier in identities.values():
                    container = json.loads(docker('inspect', identifier))[0]
                    if container['State']['Running'] or container['HostConfig']['RestartPolicy']['Name'] != 'no':
                        raise RuntimeError('Synthetic container was not stopped and disarmed')
                # Owned synthetic marker only; real recovery markers require an
                # operator's verified recovery workflow and are never cleared.
                (state / 'narration-recovery.json').unlink()
                results.append(target)
    finally:
        if child is not None and child.is_alive():
            child.kill()
            child.join(10)
            if child.is_alive():
                cleanup_failed = True
        for identifier in identities.values():
            try:
                docker('rm', '-f', identifier)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError('Owned fixture cleanup failed')
    print(json.dumps({'status': 'SIGKILL_QUARANTINE_PASSED', 'stages': results,
                      'real_database': False, 'actual_reboot': False, 'restore_authorized': False}))


if __name__ == '__main__':
    # Spawn support is not needed: this fixture deliberately uses local fork
    # so the child's test-only slot names are not exposed as production inputs.
    main()
