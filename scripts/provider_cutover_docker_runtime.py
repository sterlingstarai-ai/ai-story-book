"""Pinned Docker operations for disposable, network-isolated cutover fixtures.

This adapter is deliberately restricted to labelled network=none containers.
It does not implement ingress, worker drain, live-provider checks, daemon-wide
operation tracking, or a production rollout. Never use it as production proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
import threading


class DockerRuntimeError(RuntimeError):
    """A safe Docker operation could not be established."""


class UncertainDockerOperation(DockerRuntimeError):
    """The daemon may still apply an operation after the CLI loses contact."""


_ID = re.compile(r'[0-9a-f]{64}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_OWNER = re.compile(r'[0-9a-f]{32}\Z')
_LABEL = 'ai-story-book.cutover-fixture-owner'
_ALLOWED_LABELS = frozenset({_LABEL, 'asb.fixture.token', 'asb.provider.transaction'})
_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},"image_id":{{json .Image}},'
    '"running":{{json .State.Running}},"status":{{json .State.Status}},'
    '"paused":{{json .State.Paused}},"restart_policy":{{json .HostConfig.RestartPolicy.Name}},'
    '"network":{{json .HostConfig.NetworkMode}},"attachments":{{json .NetworkSettings.Networks}},'
    '"owner":{{json (index .Config.Labels LABEL_PLACEHOLDER)}}}'
)
_NETWORK_FORMAT = ('{"id":{{json .Id}},"name":{{json .Name}},"internal":{{json .Internal}},'
                   '"owner":{{json (index .Labels "ai-story-book.cutover-fixture-owner")}}}')


@dataclass(frozen=True)
class ContainerTarget:
    identifier: str
    image_id: str
    initial_name: str
    allowed_names: frozenset[str]
    owner_label: str = _LABEL


class DockerCutoverRuntime:
    """Track exact owned container identities and fail closed after uncertainty.

    daemon_quiescence is an optional external fixture callback. It must return
    exactly True to support assert_no_unresolved_daemon_operations; the adapter
    itself cannot prove there are no external or delayed daemon operations.
    """

    def __init__(self, targets, *, owner_token, daemon_quiescence=None,
                 internal_network_id=None, runner=subprocess.run, docker='docker', timeout=20):
        if (not isinstance(owner_token, str) or not _OWNER.fullmatch(owner_token)
                or not isinstance(targets, (tuple, list)) or not targets
                or not isinstance(docker, str) or not docker or not callable(runner)
                or (daemon_quiescence is not None and not callable(daemon_quiescence))
                or (internal_network_id is not None and (not isinstance(internal_network_id, str)
                                                         or not _ID.fullmatch(internal_network_id)))
                or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 120):
            raise ValueError('invalid fixture runtime configuration')
        by_id = {}
        names = set()
        for target in targets:
            if (not isinstance(target, ContainerTarget) or not isinstance(target.identifier, str)
                    or not _ID.fullmatch(target.identifier) or not isinstance(target.image_id, str)
                    or not _IMAGE.fullmatch(target.image_id) or not isinstance(target.initial_name, str)
                    or not isinstance(target.allowed_names, frozenset) or not target.allowed_names
                    or target.owner_label not in _ALLOWED_LABELS
                    or target.initial_name not in target.allowed_names
                    or any(not isinstance(n, str) or not _NAME.fullmatch(n) for n in target.allowed_names)
                    or target.identifier in by_id or target.initial_name in names):
                raise ValueError('invalid pinned fixture target')
            by_id[target.identifier] = target
            names.add(target.initial_name)
        self._targets = by_id
        self._names = {identifier: target.initial_name for identifier, target in by_id.items()}
        self._owner = owner_token
        self._internal_network_id = internal_network_id
        self._quiescence = daemon_quiescence
        self._run = runner
        self._docker = docker
        self._timeout = timeout
        self._unresolved = False
        self._lock = threading.RLock()

    def _target(self, identifier):
        if not isinstance(identifier, str) or identifier not in self._targets:
            raise DockerRuntimeError('container is not an owned pinned target')
        return self._targets[identifier]

    def _read(self, identifier, *, expected_name=None, allow_any_allowed=False):
        target = self._target(identifier)
        try:
            fmt = _FORMAT.replace('LABEL_PLACEHOLDER', json.dumps(target.owner_label))
            result = self._run([self._docker, 'inspect', '--format', fmt, identifier],
                               capture_output=True, text=True, timeout=self._timeout, check=False)
            if result.returncode != 0:
                raise ValueError()
            item = json.loads(result.stdout)
            if (not isinstance(item, dict) or set(item) != {'id', 'name', 'image_id', 'running', 'status',
                                                              'paused', 'restart_policy', 'network', 'attachments', 'owner'}
                    or item['id'] != identifier or item['image_id'] != target.image_id
                    or item['owner'] != self._owner
                    or not isinstance(item['name'], str) or not item['name'].startswith('/')
                    or type(item['running']) is not bool or item['paused'] is not False
                    or item['status'] not in {'created', 'running', 'exited'}
                    or item['running'] != (item['status'] == 'running')
                    or item['restart_policy'] not in {'no', 'unless-stopped'}):
                raise ValueError()
            if self._internal_network_id is None:
                if item['network'] != 'none':
                    raise ValueError()
            else:
                network_result = self._run([self._docker, 'network', 'inspect', '--format', _NETWORK_FORMAT,
                                            self._internal_network_id], capture_output=True, text=True,
                                           timeout=self._timeout, check=False)
                network = json.loads(network_result.stdout) if network_result.returncode == 0 else None
                if (not isinstance(network, dict) or set(network) != {'id', 'name', 'internal', 'owner'}
                        or network['id'] != self._internal_network_id or network['internal'] is not True
                        or network['owner'] != self._owner or not isinstance(network['name'], str)
                        or not _NAME.fullmatch(network['name']) or item['network'] != network['name']
                        or not isinstance(item['attachments'], dict)
                        or set(item['attachments']) != {network['name']}
                        or not isinstance(item['attachments'][network['name']], dict)
                        or (item['attachments'][network['name']].get('NetworkID') != self._internal_network_id
                            and not (item['status'] == 'created'
                                     and item['attachments'][network['name']].get('NetworkID') == ''))):
                    raise ValueError()
            name = item['name'][1:]
            if name not in target.allowed_names:
                raise ValueError()
            if not allow_any_allowed and name != (expected_name or self._names[identifier]):
                raise ValueError()
            return {'id': identifier, 'name': name, 'image_id': item['image_id'],
                    'running': item['running'], 'restart_policy': item['restart_policy']}
        except Exception:
            raise DockerRuntimeError('container identity or state cannot be confirmed') from None

    def inspect(self, identifier):
        with self._lock:
            return self._read(identifier, allow_any_allowed=self._unresolved)

    def _mutate(self, identifier, command, *, expected_name=None, expect_running=None, expect_restart=None,
                require_running=None, require_restart=None):
        self._target(identifier)
        if self._unresolved and command[0] not in {'stop', 'update-no'}:
            raise UncertainDockerOperation('prior daemon operation remains unresolved')
        before = self._read(identifier, allow_any_allowed=self._unresolved)
        if ((require_running is not None and before['running'] is not require_running)
                or (require_restart is not None and before['restart_policy'] != require_restart)):
            raise DockerRuntimeError('container precondition differs')
        args = {'stop': ['stop', '--time', '5'], 'start': ['start'],
                'update-no': ['update', '--restart=no'],
                'update-unless': ['update', '--restart=unless-stopped'],
                'rename': ['rename']}[command[0]]
        args = [self._docker, *args, identifier, *command[1:]]
        try:
            result = self._run(args, capture_output=True, text=True, timeout=self._timeout, check=False)
            if result.returncode != 0:
                raise ValueError()
            item = self._read(identifier, expected_name=expected_name,
                              allow_any_allowed=self._unresolved and expected_name is None)
            if ((expect_running is not None and item['running'] is not expect_running)
                    or (expect_restart is not None and item['restart_policy'] != expect_restart)):
                raise ValueError()
            return item
        except BaseException:
            # Even if a subsequent inspect observes the desired state, a CLI
            # timeout/error/interruption does not prove the daemon has no delayed work.
            self._unresolved = True
            try:
                self._read(identifier, allow_any_allowed=True)
            except BaseException:
                pass
            raise UncertainDockerOperation('Docker operation outcome requires reconciliation') from None

    def disable_restart(self, identifier):
        with self._lock:
            self._mutate(identifier, ['update-no'], expect_restart='no')

    def enable_restart(self, identifier):
        with self._lock:
            self._mutate(identifier, ['update-unless'], expect_restart='unless-stopped',
                         require_running=True, require_restart='no')

    def stop(self, identifier):
        with self._lock:
            self._mutate(identifier, ['stop'], expect_running=False, require_restart='no')

    def start(self, identifier):
        with self._lock:
            self._mutate(identifier, ['start'], expect_running=True, require_running=False, require_restart='no')

    def rename(self, identifier, name):
        with self._lock:
            target = self._target(identifier)
            if not isinstance(name, str) or name not in target.allowed_names:
                raise DockerRuntimeError('container name is outside the pinned target')
            if name == self._names[identifier]:
                self.inspect(identifier)
                return
            self._mutate(identifier, ['rename', name], expected_name=name, require_running=False, require_restart='no')
            self._names[identifier] = name

    def assert_no_unresolved_daemon_operations(self):
        with self._lock:
            if self._unresolved or self._quiescence is None:
                raise UncertainDockerOperation('daemon quiescence has not been independently proved')
            try:
                if self._quiescence() is not True:
                    raise ValueError()
            except Exception:
                raise UncertainDockerOperation('daemon quiescence has not been independently proved') from None
