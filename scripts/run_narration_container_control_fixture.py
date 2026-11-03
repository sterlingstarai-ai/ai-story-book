"""Exercise real Docker controls on four owned, network-isolated containers."""
import json
from pathlib import Path
import tempfile
import uuid

from build_narration_candidate import docker, ensure_local_daemon
import narration_container_controls as controls
import narration_deploy_safety as safety


def main():
    ensure_local_daemon()
    postgres_image = json.loads(docker('image', 'inspect', 'postgres:16'))[0]['Id']  # no pull
    prefix = 'asb-narration-control-fixture-' + uuid.uuid4().hex[:12]
    slots = ('old_api', 'old_worker', 'new_api', 'new_worker')
    names = {slot: prefix + '-' + slot.replace('_', '-') for slot in slots}
    safety._SLOTS = {slot: {names[slot]} for slot in slots}
    controls._ACTIVE_NAMES = {slot: names[slot] for slot in ('old_api', 'old_worker')}
    ids = {}
    cleanup_failed = False
    try:
        with tempfile.TemporaryDirectory(prefix='asb-control-fixture-') as folder:
            fake_celery = Path(folder) / 'celery'
            fake_celery.write_text('#!/bin/sh\nprintf \'{"worker@fixture": []}\\n\'\n')
            fake_celery.chmod(0o755)
            for slot in slots:
                mount = ['--mount', f'type=bind,src={fake_celery},dst=/usr/local/bin/celery,readonly'] if slot == 'old_worker' else []
                ids[slot] = docker('create', '--name', names[slot], '--init', '--network=none',
                                   '--restart=no', *mount, '--entrypoint', 'sleep',
                                   'postgres:16', '600').decode().strip()
            for slot in ('old_api', 'old_worker'):
                docker('update', '--restart=unless-stopped', ids[slot])
                docker('start', ids[slot])
            adapter = controls.NarrationContainerControls(safety.DockerRuntime())
            adapter.verify_pinned_images(ids, {slot: postgres_image for slot in slots})
            adapter.stop_and_drain(ids)
            adapter.disable_restart(ids)
            for slot in ('new_api', 'new_worker'):
                docker('start', ids[slot])
            adapter.enable_new_restart(ids)
            runtime = safety.DockerRuntime()
            for slot, identifier in ids.items():
                item = runtime.inspect(identifier)
                expected = 'unless-stopped' if slot.startswith('new_') else 'no'
                if item['restart_policy'] != expected or item['running'] != slot.startswith('new_'):
                    raise RuntimeError('Synthetic container final state mismatch')
    finally:
        for identifier in ids.values():
            try:
                docker('rm', '-f', identifier)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError('Owned synthetic container cleanup failed')
    print(json.dumps({'status': 'DOCKER_CONTAINER_CONTROLS_PASSED', 'synthetic_data_only': True,
                      'external_write_controls_verified': False, 'deployment_authorized': False}))


if __name__ == '__main__':
    main()
