#!/usr/bin/env python3
"""Exercise the real rotation quarantine against owned local Docker containers.

The fixture substitutes temporary marker paths and unique container names in
this Python process only. It uses no credentials, network, VM, ingress, or
production state; it does not test systemd boot or authorize deployment.
"""
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import backup_service_guard as backup
import narration_deploy_safety as narration
import provider_rotation_quarantine as rotation


def docker(*args):
    return subprocess.run(['docker', *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=90).stdout.strip()


class OwnedRuntime(narration.DockerRuntime):
    """Reject any Docker operation outside this fixture's pinned identities."""
    def __init__(self, owned, image_id, token):
        self.owned = owned
        self.image_id = image_id
        self.token = token

    def _check(self, identifier):
        if identifier not in self.owned:
            raise RuntimeError('Unowned fixture identity')
        item = json.loads(docker('inspect', identifier))[0]
        if (item['Id'] != identifier or item['Name'].lstrip('/') != self.owned[identifier]
                or item['Image'] != self.image_id
                or item['Config']['Labels'].get('asb-fixture-run') != self.token
                or item['HostConfig']['NetworkMode'] != 'none'):
            raise RuntimeError('Fixture identity or isolation mismatch')

    def inspect(self, identifier):
        self._check(identifier)
        return super().inspect(identifier)

    def stop(self, identifier):
        self._check(identifier)
        return super().stop(identifier)

    def disable_restart(self, identifier):
        self._check(identifier)
        return super().disable_restart(identifier)


def child(stage, state, backup_state, identities, images, runtime, ready):
    rotation.arm(state_dir=state, backup_state_dir=backup_state,
                 identities=identities, image_ids=images, runtime=runtime)
    if stage != 'armed':
        for slot in ('old_api', 'old_worker'):
            runtime.stop(identities[slot])
    if stage in ('partial', 'started', 'restart_enabled'):
        runtime._check(identities['new_api'])
        docker('start', identities['new_api'])
    if stage in ('started', 'restart_enabled'):
        runtime._check(identities['new_worker'])
        docker('start', identities['new_worker'])
    if stage == 'restart_enabled':
        runtime._check(identities['new_worker'])
        docker('update', '--restart=unless-stopped', identities['new_worker'])
    ready.set()
    while True:
        time.sleep(1)


def main():
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise RuntimeError('Docker override is not allowed')
    context = json.loads(docker('context', 'inspect'))
    if not context[0]['Endpoints']['docker']['Host'].startswith('unix://'):
        raise RuntimeError('Only a local Unix Docker daemon is allowed')
    image = json.loads(docker('image', 'inspect', 'postgres:16'))[0]['Id']
    if not image.startswith('sha256:') or len(image) != 71:
        raise RuntimeError('Local pinned fixture image is required')
    token = uuid.uuid4().hex
    prefix = 'asb-actual-guard-fixture-' + token[:12]
    identities, owned = {}, {}
    runtime = OwnedRuntime(owned, image, token)
    process = None
    try:
        for slot in ('old_api', 'old_worker', 'new_api', 'new_worker'):
            name = prefix + '-' + slot.replace('_', '-')
            identifier = docker('create', '--name', name, '--network=none', '--restart=no',
                '--read-only', '--label', 'asb-fixture-run=' + token,
                '--entrypoint', 'sh', image, '-c',
                "trap 'exit 0' TERM; while :; do sleep 1 & wait $!; done")
            identities[slot] = identifier
            owned[identifier] = name
        images = {slot: image for slot in identities}
        with tempfile.TemporaryDirectory(prefix='asb-actual-guard-') as folder:
            root = Path(folder)
            state = root / 'rotation'
            backup_state = root / 'backup'
            state.mkdir(mode=0o700)
            backup_state.mkdir(mode=0o700)
            backup.PROVIDER_ROTATION_RECOVERY_MARKER = state / 'recovery.json'
            backup.NARRATION_RECOVERY_MARKER = root / 'narration-recovery.json'
            narration.PRIVACY_RECOVERY_MARKER = root / 'privacy-recovery.json'
            narration.BACKUP_STATE = backup_state
            rotation._SLOTS = {slot: {owned[identifier]} for slot, identifier in identities.items()}
            completed = []
            for stage in ('armed', 'old_stopped', 'partial', 'started', 'restart_enabled'):
                for slot in ('old_api', 'old_worker'):
                    runtime._check(identities[slot])
                    docker('start', identities[slot])
                ctx = multiprocessing.get_context('fork')
                ready = ctx.Event()
                process = ctx.Process(target=child, args=(stage, state, backup_state,
                                      identities, images, runtime, ready))
                process.start()
                if not ready.wait(90):
                    raise RuntimeError('Fixture stage did not execute')
                try:
                    backup.assert_no_narration_recovery()
                except backup.GuardError:
                    pass
                else:
                    raise RuntimeError('Marker did not block legacy recovery')
                process.kill()
                process.join(10)
                if process.is_alive() or not backup.PROVIDER_ROTATION_RECOVERY_MARKER.is_file():
                    raise RuntimeError('Crash marker missing')
                process = None
                for _ in range(2):
                    result = rotation.quarantine(state_dir=state, runtime=runtime)
                    if result != {'status': 'ROTATION_QUARANTINED', 'production_authorized': False}:
                        raise RuntimeError('Unexpected quarantine result')
                    if not backup.PROVIDER_ROTATION_RECOVERY_MARKER.is_file():
                        raise RuntimeError('Quarantine cleared its marker')
                for identifier in identities.values():
                    item = runtime.inspect(identifier)
                    if item['running'] is not False or item['restart_policy'] != 'no':
                        raise RuntimeError('Fixture quarantine incomplete')
                backup.PROVIDER_ROTATION_RECOVERY_MARKER.unlink()
                completed.append(stage)
            # One lost fixture container must not make recovery report success
            # or prevent quarantine of the remaining verified containers.
            for slot in ('old_api', 'old_worker'):
                runtime._check(identities[slot])
                docker('start', identities[slot])
            rotation.arm(state_dir=state, backup_state_dir=backup_state,
                         identities=identities, image_ids=images, runtime=runtime)
            missing = identities['new_worker']
            runtime._check(missing)
            docker('rm', missing)
            identities.pop('new_worker')
            owned.pop(missing)
            try:
                rotation.quarantine(state_dir=state, runtime=runtime)
            except rotation.RotationGuardError:
                pass
            else:
                raise RuntimeError('Missing container did not block recovery')
            if not backup.PROVIDER_ROTATION_RECOVERY_MARKER.is_file():
                raise RuntimeError('Failed quarantine cleared its marker')
            for identifier in identities.values():
                item = runtime.inspect(identifier)
                if item['running'] is not False or item['restart_policy'] != 'no':
                    raise RuntimeError('Remaining containers were not quarantined')
            completed.append('missing_container_fail_closed')
            print(json.dumps({'status': 'ACTUAL_GUARD_FIXTURE_PASSED', 'stages': completed,
                'actual_boot': False, 'real_ingress': False, 'provider_verified': False,
                'deployment_authorized': False}))
    finally:
        if process is not None and process.is_alive():
            process.kill()
            process.join(10)
        failures = []
        for identifier in identities.values():
            try:
                runtime._check(identifier)
                docker('rm', '-f', identifier)
            except Exception:
                failures.append(identifier)
        if failures:
            raise RuntimeError('Owned fixture cleanup failed')


if __name__ == '__main__':
    main()
