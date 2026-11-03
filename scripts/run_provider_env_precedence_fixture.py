"""Test Docker env-file overrides with synthetic values and owned containers.

This does not read a real env file, start an app, deploy a key or modify any
production container. The only created files and containers are task-owned.
"""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile

from provider_environment import sanitize_environment


class FixtureError(RuntimeError):
    pass


def command(arguments, *, timeout=30):
    result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise FixtureError('Docker fixture operation failed')
    return result.stdout


def main():
    token = secrets.token_hex(16)
    owned = []
    output = {'status': 'FAILED', 'production_changed': False, 'phase': 'check_daemon'}
    try:
        if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
            raise FixtureError('Only the local Docker daemon is allowed')
        context = json.loads(command(['docker', 'context', 'inspect']))
        if not context[0]['Endpoints']['docker']['Host'].startswith('unix://'):
            raise FixtureError('Only the local Docker daemon is allowed')
        with tempfile.TemporaryDirectory(prefix='asb-provider-env-') as temporary:
            path = Path(temporary) / 'fixture.env'
            path.write_bytes(sanitize_environment(b'LLM_API_KEY=synthetic-old-key\nIMAGE_API_KEY=synthetic-old-key\n'
                                                  b'DATABASE_URL=synthetic-database-credential\n'))
            path.chmod(0o600)
            for index, image in enumerate(('storybook-launch-api:c20d312', 'storybook-launch-worker:c20d312')):
                output['phase'] = 'create_container_' + str(index)
                name = 'asb-provider-env-' + token + '-' + str(index)
                result = command(['docker', 'create', '--name', name, '--network', 'none', '--restart=no',
                                  '--label', 'asb.fixture.token=' + token, '--env-file', str(path), image])
                identifier = result.decode().strip()
                if not re.fullmatch('[0-9a-f]{64}', identifier):
                    raise FixtureError('Invalid owned container identity')
                owned.append(identifier)
                output['phase'] = 'inspect_container_' + str(index)
                item = json.loads(command(['docker', 'inspect', identifier]))[0]
                if item.get('Config', {}).get('Labels', {}).get('asb.fixture.token') != token:
                    raise FixtureError('Owned container identity changed')
                entries = item.get('Config', {}).get('Env')
                if not isinstance(entries, list):
                    raise FixtureError('Container environment is unavailable')
                pairs = [entry.split('=', 1) for entry in entries]
                if any(len(pair) != 2 for pair in pairs):
                    raise FixtureError('Container environment is malformed')
                selected = {key: [value for current, value in pairs if current == key] for key in (
                    'LLM_API_KEY', 'IMAGE_API_KEY', 'LLM_API_KEY_FILE', 'IMAGE_API_KEY_FILE', 'DATABASE_URL')}
                if (selected['LLM_API_KEY'] != [] or selected['IMAGE_API_KEY'] != []
                        or selected['LLM_API_KEY_FILE'] != ['/run/asb-provider-keys/provider.key']
                        or selected['IMAGE_API_KEY_FILE'] != ['/run/asb-provider-keys/provider.key']
                        or selected['DATABASE_URL'] != ['synthetic-database-credential']
                        or any('synthetic-old-key' in item for item in entries)):
                    raise FixtureError('Raw provider key override was not applied')
        output = {'status': 'SYNTHETIC_ENV_PRECEDENCE_VERIFIED', 'containers_checked': len(owned),
                  'production_changed': False}
    except Exception:
        pass
    finally:
        cleanup = True
        for identifier in owned:
            try:
                item = json.loads(command(['docker', 'inspect', identifier]))[0]
                if (item.get('Id') != identifier
                        or item.get('Config', {}).get('Labels', {}).get('asb.fixture.token') != token):
                    cleanup = False
                    continue
                command(['docker', 'rm', '-f', identifier])
            except Exception:
                cleanup = False
        output['cleanup_verified'] = cleanup
    print(json.dumps(output, sort_keys=True))
    return 0 if output['status'] == 'SYNTHETIC_ENV_PRECEDENCE_VERIFIED' and cleanup else 1


if __name__ == '__main__':
    raise SystemExit(main())
