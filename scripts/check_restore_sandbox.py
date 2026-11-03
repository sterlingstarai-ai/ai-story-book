"""Check one offline Docker container's isolation configuration, read-only.

This is a point-in-time check, not a recovery authorization. A trusted local
Docker daemon, image provenance, continuous enforcement, secure input/output,
complete privacy history, and restored data validation remain separate gates.
"""
import argparse
import json
import os
import re
import subprocess
import sys


class SandboxError(RuntimeError):
    pass


def _tmpfs_ok(options):
    if not isinstance(options, str):
        return False
    parts = options.split(',')
    if len(parts) != len(set(parts)):
        return False
    required = {'rw', 'nosuid', 'nodev', 'noexec', 'uid=65534', 'gid=65534', 'mode=0700'}
    size = [part for part in parts if re.fullmatch(r'size=[1-9][0-9]{0,3}m', part)]
    return (len(size) == 1 and int(size[0][5:-1]) <= 2048
            and set(parts) == required | set(size))


def assess(container, *, container_id, image_id, token):
    if (not re.fullmatch('[0-9a-f]{64}', container_id)
            or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not re.fullmatch('[0-9a-f]{32}', token) or not isinstance(container, dict)):
        raise SandboxError('Invalid expected sandbox identity')
    try:
        config, host, state, network = (container[k] for k in ('Config', 'HostConfig', 'State', 'NetworkSettings'))
        labels = config.get('Labels') or {}
        if (container.get('Id') != container_id or container.get('Image') != image_id
                or labels.get('asb.restore.purpose') != 'offline-candidate'
                or labels.get('asb.restore.token') != token
                or config.get('User') != '65534:65534' or state.get('Running') is not True
                or state.get('Paused') is not False or state.get('Restarting') is not False
                or state.get('Dead') is not False):
            raise SandboxError('Sandbox identity does not match')
        if (host.get('NetworkMode') != 'none' or host.get('Privileged') is not False
                or host.get('ReadonlyRootfs') is not True or host.get('PublishAllPorts') is not False
                or host.get('PortBindings') not in ({}, None) or host.get('Binds') not in ([], None)
                or host.get('VolumesFrom') not in ([], None) or host.get('Devices') not in ([], None)
                or host.get('DeviceRequests') not in ([], None) or host.get('DeviceCgroupRules') not in ([], None)
                or host.get('CapAdd') not in ([], None) or host.get('CapDrop') != ['ALL']
                or host.get('PidMode') not in ('', 'private') or host.get('IpcMode') not in ('', 'private', 'none')
                or host.get('UsernsMode') not in ('', 'private') or host.get('Links') not in ([], None)):
            raise SandboxError('Sandbox has unsafe host access')
        if (host.get('SecurityOpt') not in (['no-new-privileges'], ['no-new-privileges:true'])
                or host.get('LogConfig', {}).get('Type') != 'none'
                or host.get('RestartPolicy', {}).get('Name') != 'no'
                or type(host.get('Memory')) is not int or host['Memory'] <= 0
                or host.get('MemorySwap') != host['Memory']
                or type(host.get('PidsLimit')) is not int or not 1 <= host['PidsLimit'] <= 256):
            raise SandboxError('Sandbox resource or security configuration is unsafe')
        tmpfs = host.get('Tmpfs')
        allowed_tmpfs = ({'/tmp', '/var/lib/asb-restore'},
                         {'/tmp', '/var/lib/asb-restore', '/var/lib/postgresql/data'})
        if (not isinstance(tmpfs, dict) or set(tmpfs) not in allowed_tmpfs
                or not all(_tmpfs_ok(value) for value in tmpfs.values()) or container.get('Mounts') != []):
            raise SandboxError('Sandbox storage is not isolated temporary memory')
        networks = network.get('Networks')
        if (not isinstance(networks, dict) or set(networks) != {'none'}
                or any(networks['none'].get(key) for key in ('IPAddress', 'GlobalIPv6Address', 'Gateway', 'IPv6Gateway'))
                or network.get('Ports') not in ({}, None)):
            raise SandboxError('Sandbox network is not isolated')
        return {'status': 'SANDBOX_CONFIGURATION_MATCHES', 'restore_authorized': False}
    except SandboxError:
        raise
    except Exception:
        raise SandboxError('Sandbox inspection could not be validated') from None


def docker(*args):
    try:
        return subprocess.run(['docker', *args], check=True, capture_output=True,
                              text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        raise SandboxError('Docker inspection failed') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container-id', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--token', required=True)
    args = parser.parse_args(argv)
    try:
        override = os.environ.get('DOCKER_HOST', '')
        endpoint = json.loads(docker('context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}'))
        if ((override and not override.startswith('unix://')) or not isinstance(endpoint, str)
                or not endpoint.startswith('unix://')):
            raise SandboxError('A local Docker endpoint is required')
        containers = json.loads(docker('inspect', args.container_id))
        if not isinstance(containers, list) or len(containers) != 1:
            raise SandboxError('Exactly one sandbox is required')
        print(json.dumps(assess(containers[0], container_id=args.container_id,
                                image_id=args.image_id, token=args.token), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'SANDBOX_NOT_VERIFIED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
