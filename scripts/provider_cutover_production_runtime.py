"""Pinned Docker lifecycle for the production provider cutover.

Requires independent, successful staging verification before admitting four
containers. Does not itself drain traffic, stage candidates, install guards,
run providers, or constitute an executable production cutover.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time

from provider_cutover_journal import run_journaled

OLD_API = '5ff656bcfe2401d57336218db888a7ae1099f532b63632017c03065b37661d71'
OLD_WORKER = 'c35b76ed95ff96b783b77ffcd4789e74bfeeb0f3498441aef80ff387c957170e'
API_IMAGE = 'sha256:47dcb13c52033638740a93463cded3d61c28bc9c85ccfd7ce4932e681be139b1'
WORKER_IMAGE = 'sha256:75a13c62b099d33f5d23ef4b56a6a41cde8ac0f5aff1b6828a65baf5c528f638'
_ID = re.compile(r'[0-9a-f]{64}\Z')
_NETWORK = 'asb-pilot-net'
_DOCKER_BIN = '/usr/bin/docker'
_NAME = {
    'old_api': {'asb-pilot-api', 'asb-pilot-api-before-provider'},
    'old_worker': {'asb-pilot-worker', 'asb-pilot-worker-before-provider'},
    'new_api': {'asb-provider-next-api', 'asb-pilot-api'},
    'new_worker': {'asb-provider-next-worker', 'asb-pilot-worker'},
}


class ProductionRuntimeError(RuntimeError):
    pass


def _ordered_mounts(mounts):
    """Canonicalize Docker's unordered mount list without relaxing its contents."""
    if not isinstance(mounts, list):
        raise ProductionRuntimeError('Docker mount list is invalid')
    destinations = []
    for mount in mounts:
        if not isinstance(mount, dict):
            raise ProductionRuntimeError('Docker mount list is invalid')
        destination = mount.get('Destination')
        if not isinstance(destination, str) or not destination.startswith('/'):
            raise ProductionRuntimeError('Docker mount destination is invalid')
        destinations.append(destination)
    if len(set(destinations)) != len(destinations):
        raise ProductionRuntimeError('Duplicate Docker mount destination')
    return sorted(mounts, key=lambda mount: mount['Destination'])


class ProductionDockerRuntime:
    """Only pinned, pre-verified container IDs may be inspected or mutated."""

    def __init__(self, *, ids, transaction, directory, stage_verify, runner=subprocess.run, clock=time.monotonic, sleep=time.sleep):
        if (not isinstance(ids, dict) or set(ids) != set(_NAME)
                or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in ids.values())
                or len(set(ids.values())) != 4 or ids['old_api'] != OLD_API or ids['old_worker'] != OLD_WORKER
                or not re.fullmatch(r'[0-9a-f]{32}', transaction) or not callable(stage_verify)):
            raise ProductionRuntimeError('Invalid pinned candidate identity')
        self.ids = dict(ids)
        self.slots = {value: key for key, value in ids.items()}
        self.transaction = transaction
        self.directory = directory
        self._stage_verify = stage_verify
        self._runner = runner
        self._clock = clock
        self._sleep = sleep
        self._fingerprints = None
        self._uncertain = False

    def _call(self, args, *, timeout=90):
        try:
            result = self._runner([_DOCKER_BIN, '--host', 'unix:///var/run/docker.sock', *args],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                                  env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
            if result.returncode != 0:
                raise ValueError()
            return result.stdout
        except BaseException:
            raise ProductionRuntimeError('Docker operation could not be confirmed') from None

    def _raw(self, identifier):
        if identifier not in self.slots:
            raise ProductionRuntimeError('Unknown container identity')
        try:
            result = json.loads(self._call(['inspect', identifier]))
            if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
                raise ValueError()
            value = result[0]
            slot = self.slots[identifier]
            image = API_IMAGE if slot.endswith('api') else WORKER_IMAGE
            if (value['Id'] != identifier or value['Image'] != image
                    or value['Name'].lstrip('/') not in _NAME[slot]
                    or type(value['State']['Running']) is not bool
                    or value['HostConfig']['RestartPolicy']['Name'] not in ('no', 'unless-stopped')
                    or set(value['NetworkSettings']['Networks']) != {_NETWORK}):
                raise ValueError()
            if slot.startswith('new_') and (value['Config'].get('Labels') or {}).get('asb.provider.transaction') != self.transaction:
                raise ValueError()
            if self._fingerprints is not None and self._fingerprint(value) != self._fingerprints[slot]:
                raise ValueError()
            return value
        except Exception:
            raise ProductionRuntimeError('Pinned container configuration differs') from None

    @staticmethod
    def _fingerprint(value):
        host = dict(value['HostConfig'])
        host.pop('RestartPolicy', None)
        # Docker reports the default OOM-kill setting as false at creation and
        # null after first start; both represent the default, not disabled OOM.
        if host.get('OomKillDisable') is None:
            host['OomKillDisable'] = False
        snapshot = {'config': value['Config'], 'host': host, 'mounts': _ordered_mounts(value['Mounts']),
                    'network': sorted(value['NetworkSettings']['Networks'])}
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).digest()

    def assert_candidate_and_interlocks(self, ids, images, *, lock_fd, old_restart):
        if ids != self.ids or images != {'old_api': API_IMAGE, 'new_api': API_IMAGE,
                                         'old_worker': WORKER_IMAGE, 'new_worker': WORKER_IMAGE}:
            raise ProductionRuntimeError('Expected pinned identities differ')
        # The production caller must pass provider_candidate_stage.verify_staged
        # with its full verified env/mount/lock arguments and guard checks.
        self._stage_verify(ids, lock_fd=lock_fd, old_restart=old_restart)
        items = {slot: self._raw(identifier) for slot, identifier in self.ids.items()}
        if self._fingerprints is None:
            self._fingerprints = {slot: self._fingerprint(item) for slot, item in items.items()}

    def inspect(self, identifier):
        item = self._raw(identifier)
        return {'id': item['Id'], 'name': item['Name'].lstrip('/'), 'image_id': item['Image'],
                'running': item['State']['Running'], 'restart_policy': item['HostConfig']['RestartPolicy']['Name']}

    def _operate(self, identifier, action, args, verify):
        if self._fingerprints is None or self._uncertain:
            raise ProductionRuntimeError('Staging or previous daemon operation is unresolved')
        self._raw(identifier)
        try:
            run_journaled(self.directory, transaction=self.transaction, action=action, container=identifier,
                          execute=lambda: self._call(args), verify=verify)
        except BaseException:
            self._uncertain = True
            raise ProductionRuntimeError('Docker operation remains unresolved') from None

    def disable_restart(self, identifier):
        self._operate(identifier, 'restart-no', ['update', '--restart=no', identifier],
                      lambda: self.inspect(identifier)['restart_policy'] == 'no')

    def enable_restart(self, identifier):
        item = self.inspect(identifier)
        if not item['running'] or item['restart_policy'] != 'no' or not self.slots[identifier].startswith('new_'):
            raise ProductionRuntimeError('Restart enable precondition failed')
        self._operate(identifier, 'restart-unless-stopped', ['update', '--restart=unless-stopped', identifier],
                      lambda: self.inspect(identifier)['restart_policy'] == 'unless-stopped')

    def stop(self, identifier):
        item = self.inspect(identifier)
        if item['restart_policy'] != 'no':
            raise ProductionRuntimeError('Stop requires restart disabled')

        def exited_cleanly():
            state = self._raw(identifier)['State']
            if state['Running']:
                return False
            if (state.get('ExitCode') != 0 or state.get('OOMKilled') is not False
                    or state.get('Error') != ''):
                raise ProductionRuntimeError('Container exit was not confirmed clean')
            return True

        if not item['running']:
            exited_cleanly()
            return

        def exited():
            deadline = self._clock() + 90
            while self._clock() < deadline:
                if exited_cleanly():
                    return True
                self._sleep(0.25)
            return False
        # `docker stop --time` can escalate to SIGKILL. Send only SIGTERM;
        # a slow, nonzero or indeterminate exit retains the durable journal.
        self._operate(identifier, 'stop', ['kill', '--signal=TERM', identifier], exited)

    def start(self, identifier):
        item = self.inspect(identifier)
        if item['running'] or item['restart_policy'] != 'no' or not self.slots[identifier].startswith('new_'):
            raise ProductionRuntimeError('Start precondition failed')
        self._operate(identifier, 'start', ['start', identifier], lambda: self.inspect(identifier)['running'])

    def rename(self, identifier, name):
        item = self.inspect(identifier)
        if item['running'] or item['restart_policy'] != 'no' or name not in _NAME[self.slots[identifier]]:
            raise ProductionRuntimeError('Rename precondition failed')
        self._operate(identifier, 'rename', ['rename', identifier, name],
                      lambda: self.inspect(identifier)['name'] == name)

    def assert_no_unresolved_daemon_operations(self):
        if self._uncertain:
            raise ProductionRuntimeError('An earlier daemon operation is indeterminate')
        try:
            (self.directory / 'docker-mutation.json').lstat()
        except FileNotFoundError:
            return
        except OSError:
            raise ProductionRuntimeError('Daemon operation journal cannot be checked') from None
        raise ProductionRuntimeError('A daemon operation remains unresolved')
