"""Exercise the rotation quarantine with owned, disconnected Docker containers.

This does not execute a real boot, ingress drain or provider call, and cannot
authorize a production change. It never reads real credentials or .env files.
"""
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

import backup_service_guard as backup
import narration_deploy_safety as narration
import provider_rotation_quarantine as rotation


def docker(*args):
    return subprocess.run(['docker', *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, timeout=60).stdout.strip()


class FixtureRuntime:
    def __init__(self, mapping):
        self.mapping = mapping

    def inspect(self, identifier):
        if identifier not in self.mapping:
            raise ValueError('Unowned container')
        item = json.loads(docker('inspect', identifier))[0]
        logical, physical = self.mapping[identifier]
        if item['Id'] != identifier or item['Name'] != '/' + physical:
            raise ValueError('Fixture identity changed')
        return {'id': item['Id'], 'name': logical, 'image_id': item['Image'],
                'running': item['State']['Running'],
                'restart_policy': item['HostConfig']['RestartPolicy']['Name']}

    def disable_restart(self, identifier):
        if identifier not in self.mapping:
            raise ValueError('Unowned container')
        docker('update', '--restart=no', identifier)

    def stop(self, identifier):
        if identifier not in self.mapping:
            raise ValueError('Unowned container')
        docker('stop', '--time', '0', identifier)


def _crash(path, identities, images, runtime, stage, ready):
    rotation.arm(state_dir=path, backup_state_dir=path, identities=identities,
                 image_ids=images, runtime=runtime)
    if stage in ('old_stopped', 'candidate_started'):
        for slot in ('old_api', 'old_worker'):
            runtime.stop(identities[slot])
    if stage == 'candidate_started':
        for slot in ('new_api', 'new_worker'):
            docker('start', identities[slot])
    ready.set()
    # Parent kills this process at a deterministic point.
    import time
    while True:
        time.sleep(1)


def main():
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise RuntimeError('Docker override is not allowed')
    context = json.loads(docker('context', 'inspect'))
    if not context[0]['Endpoints']['docker']['Host'].startswith('unix://'):
        raise RuntimeError('Only a local Unix Docker daemon is allowed')
    image_id = json.loads(docker('image', 'inspect', 'postgres:16'))[0]['Id']
    if not image_id.startswith('sha256:') or len(image_id) != 71:
        raise RuntimeError('Pinned local fixture image is required')
    prefix = 'asb-provider-guard-fixture-' + uuid.uuid4().hex[:12]
    identities, mapping = {}, {}
    process = None
    cleanup_failed = False
    try:
        logical_names = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
                         'new_api': 'asb-provider-next-api', 'new_worker': 'asb-provider-next-worker'}
        for slot, logical in logical_names.items():
            name = prefix + '-' + slot.replace('_', '-')
            identifier = docker('create', '--name', name, '--network=none', '--restart=no',
                                '--read-only', '--entrypoint', 'sleep', image_id, '600')
            identities[slot] = identifier
            mapping[identifier] = (logical, name)
        runtime = FixtureRuntime(mapping)
        with tempfile.TemporaryDirectory(prefix='asb-provider-guard-') as folder:
            path = Path(folder)
            backup.PROVIDER_ROTATION_RECOVERY_MARKER = path / 'recovery.json'
            backup.NARRATION_RECOVERY_MARKER = path / 'narration.json'
            narration.PRIVACY_RECOVERY_MARKER = path / 'privacy.json'
            narration.BACKUP_STATE = path
            images = {slot: image_id for slot in identities}
            stages = []
            for stage in ('armed', 'old_stopped', 'candidate_started'):
                for slot in ('old_api', 'old_worker'):
                    docker('start', identities[slot])
                ready = multiprocessing.get_context('fork').Event()
                process = multiprocessing.get_context('fork').Process(
                    target=_crash, args=(path, identities, images, runtime, stage, ready))
                process.start()
                if not ready.wait(45):
                    raise RuntimeError('Fixture stage did not complete')
                process.kill()
                process.join(10)
                if process.is_alive() or not (path / 'recovery.json').is_file():
                    raise RuntimeError('Fixture crash marker is missing')
                process = None
                # Simulates a boot recovery invocation, not an actual host reboot.
                if rotation.quarantine(state_dir=path, runtime=runtime)['status'] != 'ROTATION_QUARANTINED':
                    raise RuntimeError('Fixture quarantine failed')
                for identifier in identities.values():
                    item = runtime.inspect(identifier)
                    if item['running'] or item['restart_policy'] != 'no':
                        raise RuntimeError('Fixture container was not quarantined')
                # Test-owned marker is removed only after verifying all four.
                (path / 'recovery.json').unlink()
                stages.append(stage)
        print(json.dumps({'status': 'SYNTHETIC_QUARANTINE_PASSED', 'stages': stages,
                          'actual_boot': False, 'real_ingress': False,
                          'production_authorized': False}))
    finally:
        if process is not None and process.is_alive():
            process.kill()
            process.join(10)
        for identifier in identities.values():
            try:
                docker('rm', '-f', identifier)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError('Owned fixture cleanup failed')


if __name__ == '__main__':
    main()
