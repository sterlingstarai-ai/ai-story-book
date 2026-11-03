"""Exercise the cutover Docker adapter on owned, isolated containers only.

No credentials, external network, production containers, or host services are
used. The selected image must already exist locally; this script never pulls it.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import uuid

from provider_cutover_docker_runtime import (
    ContainerTarget, DockerCutoverRuntime, DockerRuntimeError, UncertainDockerOperation,
)


def run(args, timeout=30):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError('fixture Docker operation failed')
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='locally present synthetic fixture image')
    parser.add_argument('--internal-network', action='store_true', help='use an owned internal-only network')
    args = parser.parse_args()
    owner = uuid.uuid4().hex
    label = 'ai-story-book.cutover-fixture-owner'
    before, after, extra = (f'asb-cutover-{owner[:12]}-{suffix}' for suffix in ('before', 'after', 'extra'))
    ids = []
    created_uncertain = False
    network_id = None
    network_name = f'asb-cutover-{owner[:12]}-net'
    succeeded = False
    try:
        image_id = run(['image', 'inspect', '--format', '{{.Id}}', args.image])
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
            raise RuntimeError('fixture image identity unavailable')
        if args.internal_network:
            try:
                network_id = run(['network', 'create', '--internal', '--label', f'{label}={owner}', network_name])
            except Exception:
                created_uncertain = True
                raise
            if not re.fullmatch(r'[0-9a-f]{64}', network_id):
                created_uncertain = True
                raise RuntimeError('fixture network creation is unconfirmed')
        container_labels = ('asb.fixture.token', 'asb.provider.transaction') if args.internal_network else (label, label)
        for name, container_label in zip((before, extra), container_labels):
            try:
                identifier = run(['create', '--pull=never', '--network', network_name if network_id else 'none',
                                  '--restart=no', '--label', f'{container_label}={owner}', '--name', name,
                                  '--entrypoint', '/bin/sh', args.image, '-c',
                                  'trap "exit 0" TERM; while :; do sleep 1; done'])
            except Exception:
                created_uncertain = True
                raise
            if not re.fullmatch(r'[0-9a-f]{64}', identifier):
                created_uncertain = True
                raise RuntimeError('fixture creation result is unconfirmed')
            ids.append((identifier, container_label))
        first, second = ids[0][0], ids[1][0]
        target = ContainerTarget(first, image_id, before, frozenset({before, after}), owner_label=container_labels[0])
        runtime = DockerCutoverRuntime([target], owner_token=owner, internal_network_id=network_id)
        if runtime.inspect(first)['running'] is not False:
            raise RuntimeError('fixture initial state differs')
        runtime.start(first)
        runtime.enable_restart(first)
        runtime.disable_restart(first)
        runtime.stop(first)
        runtime.rename(first, after)
        runtime.start(first)
        runtime.stop(first)
        final = runtime.inspect(first)
        if final['name'] != after or final['running'] is not False or final['restart_policy'] != 'no':
            raise RuntimeError('fixture final state differs')
        try:
            runtime.start(second)
            raise AssertionError('unregistered target was accepted')
        except DockerRuntimeError:
            pass
        try:
            runtime.assert_no_unresolved_daemon_operations()
            raise AssertionError('daemon quiescence was assumed')
        except UncertainDockerOperation:
            pass
        succeeded = True
    except Exception as exc:
        print(json.dumps({'status': 'FIXTURE_FAILED', 'error_type': type(exc).__name__,
                          'create_outcome_uncertain': created_uncertain}))
    finally:
        cleanup_confirmed = not created_uncertain
        for identifier, container_label in ids:
            try:
                fmt = '{{json (index .Config.Labels ' + json.dumps(container_label) + ')}}'
                current = run(['inspect', '--format', fmt, identifier])
                if json.loads(current) != owner:
                    raise RuntimeError('fixture ownership changed')
                run(['rm', '-f', identifier])
                remaining = run(['ps', '-a', '--no-trunc', '--quiet', '--filter', f'id={identifier}'], timeout=15)
                if remaining:
                    raise RuntimeError('fixture remains')
            except Exception:
                cleanup_confirmed = False
        if network_id:
            try:
                current = run(['network', 'inspect', '--format',
                               '{{json (index .Labels "ai-story-book.cutover-fixture-owner")}}', network_id])
                if json.loads(current) != owner:
                    raise RuntimeError('fixture network ownership changed')
                run(['network', 'rm', network_id])
                remaining = run(['network', 'ls', '--no-trunc', '--quiet', '--filter', f'id={network_id}'])
                if remaining:
                    raise RuntimeError('fixture network remains')
            except Exception:
                cleanup_confirmed = False
        print(json.dumps({'status': 'FIXTURE_PASSED' if succeeded and cleanup_confirmed else 'FIXTURE_INCOMPLETE',
                          'owned_cleanup_confirmed': cleanup_confirmed,
                          'production_authorized': False}))
    return 0 if succeeded and cleanup_confirmed else 1


if __name__ == '__main__':
    raise SystemExit(main())
