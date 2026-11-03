"""Create stopped, inspected provider candidates without putting keys in argv.

This component never starts or swaps a container. A caller must hold the
shared backup lock, ensure all recovery markers are absent, and durably record
the transaction ID before calling it. It does not prove boot-time safety.
"""
from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess

from provider_cutover_journal import run_journaled
from provider_environment import create_environment_memfd, sanitize_environment


class StageError(RuntimeError):
    pass


_ROLES = {
    'api': {'old': 'asb-pilot-api', 'new': 'asb-provider-next-api',
            'cmd': ['/guard/entry.py', 'uvicorn', 'src.main:app', '--host', '0.0.0.0', '--port', '8000', '--no-access-log']},
    'worker': {'old': 'asb-pilot-worker', 'new': 'asb-provider-next-worker',
               'cmd': ['/guard/entry.py', 'celery', '-A', 'src.worker', 'worker', '--loglevel=warning', '--concurrency=1']},
}
_BASE_MOUNTS = {
    '/run/storybook-certs/neon-ca.pem': ('/etc/ai-story-book/pilot/private/neon-ca.pem', False),
    '/guard': ('/etc/ai-story-book/pilot/guard', True),
    '/run/storybook-secrets/journal.key': ('/etc/ai-story-book/pilot/private/privacy-journal-app.key', False),
}
_OVERLAY_PATH = '/etc/ai-story-book/pilot/private/provider-rotation/config.py'
_KEY_PATH = '/etc/ai-story-book/pilot/private/provider-rotation/provider.key'
_NETWORK = 'asb-pilot-net'
_API_PORT_BIND = '127.0.0.1:18081:8000'
_DOCKER_BIN = '/usr/bin/docker'
_DOCKER_HOST = 'unix:///var/run/docker.sock'
_PROBE_CODE = 'import signal,sys,time; signal.signal(signal.SIGTERM,lambda *_: sys.exit(0)); time.sleep(600)'
_PROVIDER_STATE = '/var/lib/ai-story-book/provider-rotation'
_COMPARE_CONFIG = ('User', 'WorkingDir', 'StopSignal', 'StopTimeout', 'Healthcheck', 'Shell',
                   'OpenStdin', 'Tty', 'StdinOnce', 'OnBuild', 'ExposedPorts')
_COMPARE_HOST = ('NetworkMode', 'Privileged', 'ReadonlyRootfs', 'CapAdd', 'CapDrop', 'SecurityOpt',
                 'UsernsMode', 'PidMode', 'IpcMode', 'Dns', 'DnsSearch', 'ExtraHosts', 'Memory',
                 'MemorySwap', 'NanoCpus', 'PidsLimit', 'LogConfig', 'PortBindings')
_BACKUP_LOCK = '/var/lib/ai-story-book/backup-state/backup.lock'
_PENDING = ('/var/lib/ai-story-book/provider-install/activation.json',
            '/var/lib/ai-story-book/backup-state/restart-required.json',
            '/var/lib/ai-story-book/privacy-deploy/rollback.json',
            '/var/lib/ai-story-book/narration-deploy/narration-recovery.json',
            '/var/lib/ai-story-book/provider-rotation/docker-mutation.json',
            '/var/lib/ai-story-book/provider-rotation/recovery.json')


def _verify_provider_marker(marker, expected_ids, *, owner):
    fd = None
    try:
        fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o077
                or info.st_size > 4096):
            raise ValueError()
        data = os.read(fd, 4097)
        after = os.fstat(fd)
        value = json.loads(data)
        if (len(data) != info.st_size or any(getattr(info, field) != getattr(after, field) for field in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_mode'))
                or not isinstance(value, dict) or type(value.get('version')) is not int
                or value != {'version': 1, 'containers': expected_ids}):
            raise ValueError()
    except Exception:
        raise StageError('Provider recovery marker could not be verified') from None
    finally:
        if fd is not None:
            os.close(fd)


def _verify_backup_lock_fd(fd):
    if type(fd) is not int or fd < 0:
        raise ValueError()
    descriptor, path = os.fstat(fd), os.lstat(_BACKUP_LOCK)
    if (not stat.S_ISREG(descriptor.st_mode) or not stat.S_ISREG(path.st_mode)
            or descriptor.st_uid != 0 or descriptor.st_mode & 0o077 or descriptor.st_nlink != 1
            or (descriptor.st_dev, descriptor.st_ino) != (path.st_dev, path.st_ino)):
        raise ValueError()
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _read_owned_record(path, expected):
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_mode & 0o077 or before.st_nlink != 1 or before.st_size > 4096):
            raise ValueError()
        raw = os.read(fd, 4097)
        after = os.fstat(fd)
        value = json.loads(raw)
        if (len(raw) != before.st_size or any(getattr(before, name) != getattr(after, name) for name in
                ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
                or not isinstance(value, dict) or type(value.get('version')) is not int or value != expected):
            raise ValueError()
        return before.st_dev, before.st_ino
    except Exception:
        raise StageError('Probe ownership or mutation record cannot be verified') from None
    finally:
        if fd is not None:
            os.close(fd)


def _probe_owner_record(*, transaction_id, candidate_id, probe_id, image_id):
    if (not isinstance(transaction_id, str) or not re.fullmatch('[0-9a-f]{32}', transaction_id)
            or not isinstance(candidate_id, str) or not re.fullmatch('[0-9a-f]{64}', candidate_id)
            or not isinstance(probe_id, str) or not re.fullmatch('[0-9a-f]{64}', probe_id)
            or probe_id == candidate_id or not isinstance(image_id, str)
            or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)):
        raise StageError('Probe owner identity is invalid')
    return {'version': 1, 'transaction': transaction_id, 'candidate': candidate_id,
            'probe': probe_id, 'image': image_id}



def _candidate_owner_record(*, transaction_id, ids):
    slots = {'old_api', 'old_worker', 'new_api', 'new_worker'}
    if (not isinstance(transaction_id, str) or not re.fullmatch('[0-9a-f]{32}', transaction_id)
            or not isinstance(ids, dict) or set(ids) != slots
            or any(not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{64}', identifier)
                   for identifier in ids.values()) or len(set(ids.values())) != 4):
        raise StageError('Candidate owner identity is invalid')
    return {'version': 1, 'transaction': transaction_id, 'containers': dict(ids)}


def _verify_lock(fd, *, expected_provider_ids=None, expected_probe_owner=None, expected_mutation=None,
                 expected_candidate_owner=None):
    """Verify the shared lock and reject every unowned pending recovery."""
    try:
        _verify_backup_lock_fd(fd)
        found_owned = False
        found_mutation = False
        for marker in _PENDING:
            try:
                os.lstat(marker)
            except FileNotFoundError:
                continue
            if (marker == os.path.join(_PROVIDER_STATE, 'docker-mutation.json')
                    and expected_mutation is not None):
                _read_owned_record(marker, expected_mutation)
                found_mutation = True
                continue
            if marker == _PENDING[-1] and expected_provider_ids is not None:
                _verify_provider_marker(marker, expected_provider_ids, owner=0)
                found_owned = True
                continue
            raise ValueError()
        if ((expected_provider_ids is not None and not found_owned)
                or (expected_mutation is not None and not found_mutation)):
            raise ValueError()
        probe_marker = os.path.join(_PROVIDER_STATE, 'probe-owner.json')
        try:
            os.lstat(probe_marker)
        except FileNotFoundError:
            if expected_probe_owner is not None:
                raise ValueError()
        else:
            if expected_probe_owner is None:
                raise ValueError()
            _read_owned_record(probe_marker, expected_probe_owner)
        candidate_marker = os.path.join(_PROVIDER_STATE, 'candidate-owner.json')
        try:
            os.lstat(candidate_marker)
        except FileNotFoundError:
            if expected_candidate_owner is not None:
                raise ValueError()
        else:
            if expected_candidate_owner is None:
                raise ValueError()
            _read_owned_record(candidate_marker, expected_candidate_owner)
    except Exception:
        raise StageError('Backup lock or recovery state could not be verified') from None

def _env_map(lines):
    if not isinstance(lines, list) or any(not isinstance(line, str) or '=' not in line for line in lines):
        raise StageError('Container environment is invalid')
    result = {}
    for line in lines:
        key, value = line.split('=', 1)
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', key) or key in result or '\n' in value or '\r' in value:
            raise StageError('Container environment is ambiguous')
        result[key] = value
    return result


def _source_env(environment):
    try:
        sanitize_environment(environment)
        return _env_map([line.decode('utf-8') for line in environment.splitlines()
                         if line and not line.startswith(b'#')])
    except Exception:
        # Unicode errors may otherwise include the private input bytes.
        raise StageError('Private environment could not be validated') from None


@dataclass(frozen=True, repr=False)
class _FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    uid: int
    gid: int
    mode: int
    digest: bytes = field(repr=False)


@dataclass(frozen=True, repr=False)
class BoundFileEvidence:
    """Private in-memory evidence; never serialize or log provider-key hashes."""
    overlay: _FileIdentity = field(repr=False)
    key: _FileIdentity = field(repr=False)


def _identity(fd, *, owner, maximum, digest=None):
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner or before.st_gid != 1000
            or stat.S_IMODE(before.st_mode) not in (0o400, 0o600)
            or before.st_size < 1 or before.st_size > maximum):
        raise ValueError()
    hash_value = hashlib.sha256()
    count = 0
    for chunk in iter(lambda: os.read(fd, 65536), b''):
        count += len(chunk)
        if count > maximum:
            raise ValueError()
        hash_value.update(chunk)
    after = os.fstat(fd)
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_gid', 'st_mode')
    if (count != before.st_size or any(getattr(before, name) != getattr(after, name) for name in fields)
            or (digest is not None and hash_value.hexdigest() != digest)):
        raise ValueError()
    return _FileIdentity(before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                         before.st_ctime_ns, before.st_uid, before.st_gid,
                         stat.S_IMODE(before.st_mode), hash_value.digest())


def _file(path, *, owner, maximum, digest=None):
    """Read and verify one fixed file; only its private in-memory identity is returned."""
    descriptors = []
    try:
        if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
                or os.path.normpath(path) != path or path == '/'):
            raise ValueError()
        parts = path[1:].split('/')
        dflags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        descriptors.append(os.open('/', dflags))
        for part in parts[:-1]:
            descriptors.append(os.open(part, dflags, dir_fd=descriptors[-1]))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0),
                     dir_fd=descriptors[-1])
        descriptors.append(fd)
        return _identity(fd, owner=owner, maximum=maximum, digest=digest)
    except Exception:
        raise StageError('Candidate file is unavailable or unsafe') from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def capture_bound_file_evidence(*, overlay_path, overlay_sha256, key_path):
    """Capture source identities before a candidate can start; keep only in memory."""
    if (overlay_path != _OVERLAY_PATH or key_path != _KEY_PATH or not isinstance(overlay_sha256, str)
            or not re.fullmatch('[0-9a-f]{64}', overlay_sha256)):
        raise StageError('Candidate file configuration is invalid')
    return BoundFileEvidence(_file(overlay_path, owner=1000, maximum=512 * 1024, digest=overlay_sha256),
                             _file(key_path, owner=1000, maximum=4096))


def _container_file(pid, path, *, maximum):
    fd = None
    try:
        if type(pid) is not int or pid < 2 or path not in ('/app/src/core/config.py',
                                                            '/run/asb-provider-keys/provider.key'):
            raise ValueError()
        # /proc/PID/root intentionally resolves the process mount namespace.
        # The final file itself must not be a symlink and must match the source.
        fd = os.open('/proc/' + str(pid) + '/root' + path,
                     os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0))
        return _identity(fd, owner=1000, maximum=maximum)
    except Exception:
        raise StageError('Candidate bound file cannot be verified') from None
    finally:
        if fd is not None:
            os.close(fd)


def verify_running_bound_files(*, runtime, identifier, image_id, transaction_id, evidence,
                               overlay_path, overlay_sha256, key_path):
    """Compare a running container's real bind inodes and bytes to pre-start evidence.

    Must run on the Linux Docker host, while ingress is fenced, after each new
    candidate starts and before provider requests or worker admission. A
    separate host policy must prevent changes after this check. This function
    never prints key material, its digest, or container environment.
    """
    if (not isinstance(evidence, BoundFileEvidence) or not isinstance(identifier, str)
            or not re.fullmatch('[0-9a-f]{64}', identifier) or not isinstance(image_id, str)
            or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(transaction_id, str) or not re.fullmatch('[0-9a-f]{32}', transaction_id)):
        raise StageError('Candidate file verification configuration is invalid')
    expected_mounts = {'/app/src/core/config.py': (overlay_path, False),
                       '/run/asb-provider-keys/provider.key': (key_path, False)}
    try:
        if capture_bound_file_evidence(overlay_path=overlay_path, overlay_sha256=overlay_sha256,
                                       key_path=key_path) != evidence:
            raise ValueError()
        before = runtime.inspect(identifier)
        state = before['State']
        pid = state['Pid']
        started_at = state['StartedAt']
        if (before['Id'] != identifier or before['Image'] != image_id
                or (before['Config'].get('Labels') or {}).get('asb.provider.transaction') != transaction_id
                or state['Running'] is not True or state.get('Restarting') is not False
                or type(pid) is not int or pid < 2 or not isinstance(started_at, str) or not started_at
                or any(_mounts(before).get(dst) != source for dst, source in expected_mounts.items())):
            raise ValueError()
        if (_container_file(pid, '/app/src/core/config.py', maximum=512 * 1024) != evidence.overlay
                or _container_file(pid, '/run/asb-provider-keys/provider.key', maximum=4096) != evidence.key):
            raise ValueError()
        after = runtime.inspect(identifier)
        if (after['Id'] != identifier or after['Image'] != image_id
                or after['State']['Running'] is not True or after['State']['Pid'] != pid
                or after['State']['StartedAt'] != started_at
                or capture_bound_file_evidence(overlay_path=overlay_path, overlay_sha256=overlay_sha256,
                                               key_path=key_path) != evidence):
            raise ValueError()
        return True
    except Exception:
        raise StageError('Candidate bound file identity is not confirmed') from None

def _mounts(item):
    mounts = item.get('Mounts')
    if not isinstance(mounts, list):
        raise StageError('Container mounts are unavailable')
    out = {}
    for mount in mounts:
        if (not isinstance(mount, dict) or mount.get('Type') != 'bind'
                or not isinstance(mount.get('Destination'), str) or not isinstance(mount.get('Source'), str)
                or type(mount.get('RW')) is not bool or mount['Destination'] in out):
            raise StageError('Container mounts are invalid')
        out[mount['Destination']] = (mount['Source'], mount['RW'])
    return out


def _inspect_contract(item, role, *, identifier, image, old, transaction=None, old_restart='unless-stopped',
                      expected_old_running=True):
    spec = _ROLES[role]
    try:
        config, host, state = item['Config'], item['HostConfig'], item['State']
        if (item['Id'] != identifier or item['Image'] != image
                or item['Name'].lstrip('/') != spec['old' if old else 'new']
                or config['Entrypoint'] != ['python'] or config['Cmd'] != spec['cmd']
                or config['User'] not in ('appuser', '1000:1000')
                or host['NetworkMode'] != _NETWORK
                or host['RestartPolicy']['Name'] != (old_restart if old else 'no')
                or state['Running'] is not (expected_old_running if old else False)):
            raise ValueError()
        if not old and (config.get('Labels') or {}).get('asb.provider.transaction') != transaction:
            raise ValueError()
        return _env_map(config['Env'])
    except Exception:
        raise StageError('Candidate container identity or configuration is invalid') from None


class DockerStageRuntime:
    """Local Docker CLI; output containing environment stays in process memory."""

    def _run(self, command, *, pass_fds=()):
        try:
            # Do not inherit Docker contexts, certificate paths, API versions,
            # or plugin settings that could redirect a credential-bearing call.
            env = {key: value for key, value in os.environ.items() if not key.startswith('DOCKER_')}
            result = subprocess.run([_DOCKER_BIN, '--host', _DOCKER_HOST, *command],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                    pass_fds=pass_fds, timeout=90)
            if result.returncode:
                raise ValueError()
            return result.stdout.decode('utf-8')
        except Exception:
            raise StageError('Docker operation was not confirmed') from None

    def inspect(self, identifier):
        try:
            result = json.loads(self._run(['inspect', identifier]))
            if not isinstance(result, list) or len(result) != 1:
                raise ValueError()
            return result[0]
        except Exception:
            raise StageError('Container identity could not be inspected') from None

    def create(self, args, fd):
        return self._run(['create', *args], pass_fds=(fd,)).strip()

    def remove(self, identifier):
        self._run(['rm', identifier])

    def exists(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{64}', identifier):
            raise StageError('Container identity is invalid')
        rows = self._run(['ps', '-a', '--no-trunc', '--filter', 'id=' + identifier,
                          '--format', '{{.ID}}']).splitlines()
        if any(not re.fullmatch('[0-9a-f]{64}', row) for row in rows) or len(rows) > 1:
            raise StageError('Container presence is ambiguous')
        return bool(rows) and rows[0] == identifier


def verify_staged(*, runtime, ids, image_ids, environment, overlay_path, overlay_sha256, key_path, transaction_id,
                  lock_fd, old_restart='unless-stopped', marker_state='absent', expected_probe_owner=None,
                  candidate_create_in_progress=False, expected_candidate_owner=None, old_running=None):
    """Recheck all four identities while the caller holds the shared lock."""
    required = {'old_api', 'old_worker', 'new_api', 'new_worker'}
    if (not isinstance(ids, dict) or set(ids) != required
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in ids.values())
            or len(set(ids.values())) != 4 or not isinstance(image_ids, dict) or set(image_ids) != set(_ROLES)
            or any(not isinstance(value, str) or not re.fullmatch('sha256:[0-9a-f]{64}', value)
                   for value in image_ids.values())
            or not isinstance(transaction_id, str) or not re.fullmatch('[0-9a-f]{32}', transaction_id)
            or not isinstance(overlay_sha256, str) or not re.fullmatch('[0-9a-f]{64}', overlay_sha256)
            or old_restart not in ('unless-stopped', 'no')
            or marker_state not in ('absent', 'owned') or type(candidate_create_in_progress) is not bool
            or (candidate_create_in_progress and (marker_state != 'absent' or expected_probe_owner is not None
                                                  or expected_candidate_owner is not None))
            or (old_running is not None and (not isinstance(old_running, dict)
                                             or set(old_running) != {'api', 'worker'}
                                             or old_running.get('api') is not False
                                             or old_running.get('worker') is not True
                                             or marker_state != 'owned' or old_restart != 'no'
                                             or expected_probe_owner is None or expected_candidate_owner is None))
            or overlay_path != _OVERLAY_PATH or key_path != _KEY_PATH):
        raise StageError('Candidate verification configuration is invalid')
    if expected_probe_owner is not None:
        try:
            if (not isinstance(expected_probe_owner, dict)
                    or expected_probe_owner != _probe_owner_record(
                        transaction_id=transaction_id, candidate_id=ids['new_api'],
                        probe_id=expected_probe_owner['probe'], image_id=image_ids['api'])
                    or expected_probe_owner['probe'] in ids.values()):
                raise ValueError()
        except Exception:
            raise StageError('Probe owner identity is invalid') from None
    if (expected_candidate_owner is not None
            and expected_candidate_owner != _candidate_owner_record(transaction_id=transaction_id, ids=ids)):
        raise StageError('Candidate owner identity is invalid')
    mutation = ({'version': 1, 'transaction': transaction_id, 'action': 'candidate-create',
                 'container': ids['old_api']} if candidate_create_in_progress else None)
    _verify_lock(lock_fd, expected_provider_ids=ids if marker_state == 'owned' else None,
                 expected_probe_owner=expected_probe_owner, expected_mutation=mutation,
                 expected_candidate_owner=expected_candidate_owner)
    _file(overlay_path, owner=1000, maximum=512 * 1024, digest=overlay_sha256)
    _file(key_path, owner=1000, maximum=4096)
    source_env = _source_env(environment)
    for role in _ROLES:
        old = runtime.inspect(ids['old_' + role])
        new = runtime.inspect(ids['new_' + role])
        old_env = _inspect_contract(old, role, identifier=ids['old_' + role], image=image_ids[role], old=True,
                                    old_restart=old_restart,
                                    expected_old_running=old_running[role] if old_running is not None else True)
        new_env = _inspect_contract(new, role, identifier=ids['new_' + role], image=image_ids[role],
                                    old=False, transaction=transaction_id)
        expected = dict(old_env)
        expected.pop('LLM_API_KEY', None)
        expected.pop('IMAGE_API_KEY', None)
        expected['LLM_API_KEY_FILE'] = '/run/asb-provider-keys/provider.key'
        expected['IMAGE_API_KEY_FILE'] = '/run/asb-provider-keys/provider.key'
        expected_mounts = dict(_BASE_MOUNTS)
        expected_mounts.update({'/app/src/core/config.py': (overlay_path, False),
                                '/run/asb-provider-keys/provider.key': (key_path, False)})
        if (_mounts(old) != _BASE_MOUNTS or any(old_env.get(k) != v for k, v in source_env.items())
                or new_env != expected or _mounts(new) != expected_mounts
                or any(new['Config'].get(k) != old['Config'].get(k) for k in _COMPARE_CONFIG)
                or any(new['HostConfig'].get(k) != old['HostConfig'].get(k) for k in _COMPARE_HOST)):
            raise StageError('Candidate differs from the running deployment')
    return {'status': 'STOPPED_CANDIDATES_VERIFIED', 'ids': dict(ids), 'transaction_id': transaction_id}



def _probe_name(transaction_id):
    return 'asb-provider-probe-' + transaction_id


def _probe_contract(item, *, identifier, image_id, transaction_id, candidate, overlay_path, key_path):
    try:
        config, host, state = item['Config'], item['HostConfig'], item['State']
        expected_mounts = dict(_BASE_MOUNTS)
        expected_mounts.update({'/app/src/core/config.py': (overlay_path, False),
                                '/run/asb-provider-keys/provider.key': (key_path, False)})
        labels = config.get('Labels') or {}
        candidate_config = candidate['Config']
        if (item['Id'] != identifier or item['Image'] != image_id
                or item['Name'].lstrip('/') != _probe_name(transaction_id)
                or labels.get('asb.provider.transaction') != transaction_id
                or labels.get('asb.provider.role') != 'isolated-probe'
                or config['Entrypoint'] != ['python'] or config['Cmd'] != ['-c', _PROBE_CODE]
                or any(config.get(k) != candidate_config.get(k) for k in _COMPARE_CONFIG)
                or _env_map(config['Env']) != _env_map(candidate_config['Env'])
                or host['NetworkMode'] != _NETWORK or host['RestartPolicy']['Name'] != 'no'
                or host.get('PortBindings') not in (None, {})
                or host.get('PublishAllPorts') is not False
                or state['Running'] is not False or _mounts(item) != expected_mounts
                or any(host.get(k) != candidate['HostConfig'].get(k)
                       for k in _COMPARE_HOST if k != 'PortBindings')):
            raise ValueError()
    except Exception:
        raise StageError('Probe identity or configuration is invalid') from None



def _write_probe_owner(directory, record):
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(directory_fd)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError()
            fd = os.open('probe-owner.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory_fd)
            try:
                data = (json.dumps(record, sort_keys=True) + '\n').encode()
                view = memoryview(data)
                while view:
                    count = os.write(fd, view)
                    if count <= 0:
                        raise ValueError()
                    view = view[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        raise StageError('Probe ownership could not be durably recorded') from None


def clear_probe_owner_after_compound(*, runtime, probe_id, candidate_id, image_id, transaction_id,
                                     lock_fd, action='provider-probe', state_dir=_PROVIDER_STATE):
    """Clear ownership only while an exact durable mutation intent remains.

    Call from the compound journal's verification callback after stop/remove
    and independent absence confirmation. The journal itself is cleared by
    its owner only after this function succeeds.
    """
    if state_dir != _PROVIDER_STATE or action not in ('provider-probe', 'probe-remove'):
        raise StageError('Probe cleanup configuration is invalid')
    record = _probe_owner_record(transaction_id=transaction_id, candidate_id=candidate_id,
                                 probe_id=probe_id, image_id=image_id)
    journal_container = probe_id if action == 'provider-probe' else candidate_id
    mutation = {'version': 1, 'transaction': transaction_id, 'action': action, 'container': journal_container}
    try:
        _verify_backup_lock_fd(lock_fd)
        owner_path = os.path.join(state_dir, 'probe-owner.json')
        owner_identity = _read_owned_record(owner_path, record)
        _read_owned_record(os.path.join(state_dir, 'docker-mutation.json'), mutation)
        if runtime.exists(probe_id) is not False:
            raise ValueError()
        directory_fd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            current = os.stat('probe-owner.json', dir_fd=directory_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != owner_identity:
                raise ValueError()
            os.unlink('probe-owner.json', dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    except Exception:
        raise StageError('Probe cleanup ownership is unresolved') from None


def create_stopped_probe(*, runtime, ids, image_ids, environment, overlay_path, overlay_sha256,
                         key_path, transaction_id, lock_fd, evidence, state_dir=_PROVIDER_STATE,
                         expected_candidate_owner=None):
    """Create a port-free sleeping probe from the exact stopped candidate configuration.

    Caller holds the backup lock and keeps ingress requirements separate. A
    durable daemon journal remains if creation or verification is uncertain.
    A successful result is a stopped container ID; start, provider execution,
    stop, and deletion need their own journalled operations and inode checks.
    """
    if state_dir != _PROVIDER_STATE or not isinstance(evidence, BoundFileEvidence):
        raise StageError('Probe state configuration is invalid')
    verify_staged(runtime=runtime, ids=ids, image_ids=image_ids, environment=environment,
                  overlay_path=overlay_path, overlay_sha256=overlay_sha256, key_path=key_path,
                  transaction_id=transaction_id, lock_fd=lock_fd,
                  expected_candidate_owner=expected_candidate_owner)
    if capture_bound_file_evidence(overlay_path=overlay_path, overlay_sha256=overlay_sha256,
                                   key_path=key_path) != evidence:
        raise StageError('Probe source files changed')
    candidate_id, image_id = ids['new_api'], image_ids['api']
    candidate = runtime.inspect(candidate_id)
    result = {'id': None}

    def create():
        fd = create_environment_memfd(environment)
        try:
            args = ['--name', _probe_name(transaction_id), '--restart=no', '--network', _NETWORK,
                    '--label', 'asb.provider.transaction=' + transaction_id,
                    '--label', 'asb.provider.role=isolated-probe', '--env-file', '/proc/self/fd/' + str(fd)]
            for destination, (source, rw) in _BASE_MOUNTS.items():
                args += ['--mount', f'type=bind,src={source},dst={destination}' + ('' if rw else ',readonly')]
            args += ['--mount', f'type=bind,src={overlay_path},dst=/app/src/core/config.py,readonly',
                     '--mount', f'type=bind,src={key_path},dst=/run/asb-provider-keys/provider.key,readonly',
                     '--entrypoint', 'python', image_id, '-c', _PROBE_CODE]
            result['id'] = runtime.create(args, fd)
        finally:
            os.close(fd)

    def verified():
        identifier = result['id']
        if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{64}', identifier) or identifier in ids.values():
            return False
        _probe_contract(runtime.inspect(identifier), identifier=identifier, image_id=image_id,
                        transaction_id=transaction_id, candidate=candidate,
                        overlay_path=overlay_path, key_path=key_path)
        if capture_bound_file_evidence(overlay_path=overlay_path, overlay_sha256=overlay_sha256,
                                       key_path=key_path) != evidence:
            return False
        record = _probe_owner_record(transaction_id=transaction_id, candidate_id=candidate_id,
                                     probe_id=identifier, image_id=image_id)
        _write_probe_owner(state_dir, record)
        _read_owned_record(os.path.join(state_dir, 'probe-owner.json'), record)
        return True

    try:
        from pathlib import Path
        run_journaled(Path(state_dir), transaction=transaction_id, action='probe-create', container=candidate_id,
                      execute=create, verify=verified)
        return {'status': 'STOPPED_PROBE_VERIFIED', 'probe_id': result['id']}
    except Exception:
        raise StageError('Probe creation is unresolved; retain the daemon journal') from None


def remove_stopped_probe(*, runtime, probe_id, candidate_id, image_id, transaction_id, lock_fd,
                         overlay_path, key_path, state_dir=_PROVIDER_STATE, expected_candidate_owner=None):
    """Delete only the exact stopped probe; absence or timeout never means success."""
    if (state_dir != _PROVIDER_STATE or not isinstance(probe_id, str)
            or not re.fullmatch('[0-9a-f]{64}', probe_id) or not isinstance(candidate_id, str)
            or not re.fullmatch('[0-9a-f]{64}', candidate_id) or probe_id == candidate_id
            or not isinstance(image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image_id)
            or not isinstance(transaction_id, str) or not re.fullmatch('[0-9a-f]{32}', transaction_id)
            or overlay_path != _OVERLAY_PATH or key_path != _KEY_PATH):
        raise StageError('Probe cleanup identity is invalid')
    owner = _probe_owner_record(transaction_id=transaction_id, candidate_id=candidate_id,
                                probe_id=probe_id, image_id=image_id)
    if expected_candidate_owner is not None:
        try:
            if (expected_candidate_owner != _candidate_owner_record(
                    transaction_id=transaction_id, ids=expected_candidate_owner['containers'])
                    or expected_candidate_owner['containers']['new_api'] != candidate_id):
                raise ValueError()
        except Exception:
            raise StageError('Candidate owner identity is invalid') from None
    _verify_lock(lock_fd, expected_probe_owner=owner, expected_candidate_owner=expected_candidate_owner)
    candidate = runtime.inspect(candidate_id)
    if (candidate.get('Id') != candidate_id or candidate.get('Image') != image_id
            or (candidate.get('Config', {}).get('Labels') or {}).get('asb.provider.transaction') != transaction_id):
        raise StageError('Candidate identity is invalid')
    _probe_contract(runtime.inspect(probe_id), identifier=probe_id, image_id=image_id,
                    transaction_id=transaction_id, candidate=candidate, overlay_path=overlay_path, key_path=key_path)
    try:
        from pathlib import Path
        run_journaled(Path(state_dir), transaction=transaction_id, action='probe-remove', container=candidate_id,
                      execute=lambda: runtime.remove(probe_id),
                      verify=lambda: clear_probe_owner_after_compound(
                          runtime=runtime, probe_id=probe_id, candidate_id=candidate_id, image_id=image_id,
                          transaction_id=transaction_id, lock_fd=lock_fd, action='probe-remove', state_dir=state_dir))
        return True
    except Exception:
        raise StageError('Probe cleanup is unresolved; retain the daemon journal') from None

def stage_candidates(*, runtime, old_ids, image_ids, environment, overlay_path, overlay_sha256,
                     key_path, transaction_id, lock_fd, journaled_create=False):
    """Stage two stopped candidates; caller must hold the shared backup lock."""
    if (not isinstance(old_ids, dict) or not isinstance(image_ids, dict)
            or set(old_ids) != set(_ROLES) or set(image_ids) != set(_ROLES)
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
                   for value in old_ids.values())
            or len(set(old_ids.values())) != 2
            or any(not isinstance(value, str) or not re.fullmatch('sha256:[0-9a-f]{64}', value)
                   for value in image_ids.values())
            or not isinstance(transaction_id, str) or not re.fullmatch('[0-9a-f]{32}', transaction_id)
            or not isinstance(overlay_sha256, str) or not re.fullmatch('[0-9a-f]{64}', overlay_sha256)
            or overlay_path != _OVERLAY_PATH or key_path != _KEY_PATH or type(journaled_create) is not bool):
        raise StageError('Candidate configuration is invalid')
    mutation = ({'version': 1, 'transaction': transaction_id, 'action': 'candidate-create',
                 'container': old_ids['api']} if journaled_create else None)
    _verify_lock(lock_fd, expected_mutation=mutation)
    _file(overlay_path, owner=1000, maximum=512 * 1024, digest=overlay_sha256)
    _file(key_path, owner=1000, maximum=4096)
    source_env = _source_env(environment)
    expected = {}
    originals = {}
    for role in _ROLES:
        item = runtime.inspect(old_ids[role])
        old_env = _inspect_contract(item, role, identifier=old_ids[role], image=image_ids[role], old=True)
        if _mounts(item) != _BASE_MOUNTS or any(old_env.get(k) != v for k, v in source_env.items()):
            raise StageError('Running container does not match the expected deployment')
        target = dict(old_env)
        target.pop('LLM_API_KEY', None)
        target.pop('IMAGE_API_KEY', None)
        target['LLM_API_KEY_FILE'] = '/run/asb-provider-keys/provider.key'
        target['IMAGE_API_KEY_FILE'] = '/run/asb-provider-keys/provider.key'
        expected[role], originals[role] = target, item
    ids = {}
    try:
        for role, spec in _ROLES.items():
            fd = create_environment_memfd(environment)
            try:
                args = ['--name', spec['new'], '--restart=no', '--network', _NETWORK,
                        '--label', 'asb.provider.transaction=' + transaction_id,
                        '--env-file', '/proc/self/fd/' + str(fd)]
                for destination, (source, rw) in _BASE_MOUNTS.items():
                    args += ['--mount', f'type=bind,src={source},dst={destination}' + ('' if rw else ',readonly')]
                args += ['--mount', f'type=bind,src={overlay_path},dst=/app/src/core/config.py,readonly',
                         '--mount', f'type=bind,src={key_path},dst=/run/asb-provider-keys/provider.key,readonly']
                if role == 'api':
                    args += ['-p', _API_PORT_BIND]
                args += ['--entrypoint', 'python', image_ids[role], *spec['cmd']]
                identifier = runtime.create(args, fd)
            finally:
                os.close(fd)
            if not re.fullmatch('[0-9a-f]{64}', identifier or ''):
                raise StageError('Candidate creation was not confirmed')
            ids[role] = identifier
            item = runtime.inspect(identifier)
            env = _inspect_contract(item, role, identifier=identifier, image=image_ids[role],
                                    old=False, transaction=transaction_id)
            expected_mounts = dict(_BASE_MOUNTS)
            expected_mounts.update({'/app/src/core/config.py': (overlay_path, False),
                                    '/run/asb-provider-keys/provider.key': (key_path, False)})
            if (env != expected[role] or _mounts(item) != expected_mounts
                    or any(item['Config'].get(k) != originals[role]['Config'].get(k) for k in _COMPARE_CONFIG)
                    or any(item['HostConfig'].get(k) != originals[role]['HostConfig'].get(k)
                           for k in _COMPARE_HOST)):
                raise StageError('Candidate differs from the running deployment')
        combined = {'old_api': old_ids['api'], 'old_worker': old_ids['worker'],
                    'new_api': ids['api'], 'new_worker': ids['worker']}
        return verify_staged(runtime=runtime, ids=combined, image_ids=image_ids, environment=environment,
                             overlay_path=overlay_path, overlay_sha256=overlay_sha256, key_path=key_path,
                             transaction_id=transaction_id, lock_fd=lock_fd,
                             candidate_create_in_progress=journaled_create)
    except Exception:
        # Failure is intentionally reported as unresolved: even a timed-out
        # Docker create may finish later, and only the durable caller can
        # reconcile exact transaction-labelled stopped candidates.
        raise StageError('Candidate stage incomplete; reconcile the transaction before retrying') from None
