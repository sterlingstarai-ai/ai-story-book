"""Production adapter for the drained, portless-provider cutover sequence.

This class is not an entry point. It requires already-created, durably owned
candidates and an exclusive backup lock supplied by the state machine. Public
nginx is drained; local and Docker-network access to a newly started API may
resume before nginx. No claim of zero interruption or lost-work recovery is made.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

import provider_candidate_stage as stage
import provider_cutover_portless_exec as portless
from provider_cutover import _absent, _sync_dir
from provider_cutover_ingress import drain_public_proxy
from provider_cutover_journal import run_journaled
from provider_cutover_production_guards import _verify_file, verify_installed_guard_files, verify_loaded_units
from provider_cutover_production_runtime import API_IMAGE, WORKER_IMAGE, ProductionDockerRuntime, _ordered_mounts

STATE = Path('/var/lib/ai-story-book/provider-rotation')
NGINX_ID = '59820ef705360249024bd6a3d0fc54c16549f424d5ef6b3097138c94f05deb66'
HTTPS_IP = '35.209.174.246'
NGINX_CONF_SHA = '8fe468e4878b9fc9d2c6c23942152c1288a6eb479fc27125d05c6b7cf281917a'
NGINX_IMAGE = 'sha256:6769dc3a703c719c1d2756bda113659be28ae16cf0da58dd5fd823d6b9a050ea'
OVERLAY_PATH = '/etc/ai-story-book/pilot/private/provider-rotation/config.py'
KEY_PATH = '/etc/ai-story-book/pilot/private/provider-rotation/provider.key'
_UNIT_PROPERTIES = ('LoadState', 'UnitFileState', 'FragmentPath', 'DropInPaths', 'NeedDaemonReload',
                    'KillMode', 'Requires', 'After', 'Wants', 'ExecStart')


class AdapterError(RuntimeError):
    pass


class QueueDrainPending(AdapterError):
    """The completed probe reported that drain cannot yet be confirmed."""


def _systemd_show(unit):
    if unit not in {'asb-provider-rotation-quarantine.service', 'asb-backup-recover.service',
                    'asb-privacy-deploy-recover.service'}:
        raise AdapterError('Unexpected service')
    try:
        command = ['/usr/bin/systemctl', 'show', unit, *[f'--property={p}' for p in _UNIT_PROPERTIES]]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False,
                                env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        if result.returncode or len(result.stdout) > 65536:
            raise ValueError()
        values = {}
        for line in result.stdout.decode().splitlines():
            name, value = line.split('=', 1)
            if name not in _UNIT_PROPERTIES or name in values:
                raise ValueError()
            values[name] = value
        return values
    except Exception:
        raise AdapterError('Systemd guard state is unavailable') from None


class ProductionAdapter(ProductionDockerRuntime):
    def __init__(self, *, ids, transaction, environment, overlay_sha256):
        if not isinstance(environment, bytes) or not environment or not isinstance(overlay_sha256, str):
            raise AdapterError('Private configuration is unavailable')
        self.environment = environment
        self.overlay_sha256 = overlay_sha256
        self.stage_runtime = stage.DockerStageRuntime()
        self.image_ids = {'api': API_IMAGE, 'worker': WORKER_IMAGE}
        self.candidate_owner = {'version': 1, 'transaction': transaction, 'containers': dict(ids)}
        self.probe_id = None
        self.probe_owner = None
        self.lock_fd = None
        self.evidence = None
        self._nginx_fingerprint = None
        super().__init__(ids=ids, transaction=transaction, directory=STATE, stage_verify=self._verify_stage)

    def _verify_stage(self, ids, *, lock_fd, old_restart):
        _absent(Path('/var/lib/ai-story-book/provider-install/activation.json'))
        verify_installed_guard_files()
        verify_loaded_units(_systemd_show)
        # Validate pinned source bytes before any proxy interruption.
        portless._source('provider_cutover_probe.py', portless.PROBE_SHA256)
        portless._source('provider_cutover_queue_probe.py', portless.QUEUE_SHA256)
        stage.verify_staged(runtime=self.stage_runtime, ids=ids, image_ids=self.image_ids,
            environment=self.environment, overlay_path=OVERLAY_PATH, overlay_sha256=self.overlay_sha256,
            key_path=KEY_PATH, transaction_id=self.transaction, lock_fd=lock_fd, old_restart=old_restart,
            expected_candidate_owner=self.candidate_owner, expected_probe_owner=self.probe_owner)
        self._proxy()

    def prepare_equivalent_probe(self, identifier, *, lock_fd):
        if identifier != self.ids['new_api'] or self.probe_id is not None:
            raise AdapterError('Probe preparation state differs')
        self.lock_fd = lock_fd
        self.evidence = stage.capture_bound_file_evidence(overlay_path=OVERLAY_PATH,
            overlay_sha256=self.overlay_sha256, key_path=KEY_PATH)
        result = stage.create_stopped_probe(runtime=self.stage_runtime, ids=self.ids, image_ids=self.image_ids,
            environment=self.environment, overlay_path=OVERLAY_PATH, overlay_sha256=self.overlay_sha256,
            key_path=KEY_PATH, transaction_id=self.transaction, lock_fd=lock_fd, evidence=self.evidence,
            state_dir=str(STATE), expected_candidate_owner=self.candidate_owner)
        self.probe_id = result['probe_id']
        self.probe_owner = stage._probe_owner_record(transaction_id=self.transaction,
            candidate_id=self.ids['new_api'], probe_id=self.probe_id, image_id=API_IMAGE)

    def _verify_running_proxy_bind(self, value, source):
        state = value['State']
        if state['Running'] is not True:
            return
        pid, started = state['Pid'], state['StartedAt']
        if type(pid) is not int or pid < 2 or not isinstance(started, str) or not started:
            raise AdapterError('Proxy process identity is unavailable')
        paths = (source, '/proc/' + str(pid) + '/root/etc/nginx/nginx.conf')
        descriptors = []
        try:
            identities = []
            for path in paths:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0))
                descriptors.append(fd)
                before = os.fstat(fd)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_mode & 0o022
                        or before.st_nlink != 1 or before.st_size > 1024 * 1024):
                    raise ValueError()
                digest = hashlib.sha256()
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    digest.update(chunk)
                after = os.fstat(fd)
                if (any(getattr(before, field) != getattr(after, field) for field in
                        ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))
                        or digest.hexdigest() != NGINX_CONF_SHA):
                    raise ValueError()
                identities.append((before.st_dev, before.st_ino))
            if identities[0] != identities[1]:
                raise ValueError()
            after = json.loads(self._call(['inspect', NGINX_ID]))
            if (len(after) != 1 or after[0]['Id'] != NGINX_ID or after[0]['State']['Running'] is not True
                    or after[0]['State']['Pid'] != pid or after[0]['State']['StartedAt'] != started):
                raise ValueError()
        except Exception:
            raise AdapterError('Proxy live bind identity differs') from None
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def _proxy(self):
        try:
            rows = json.loads(self._call(['inspect', NGINX_ID]))
            value = rows[0]
            if (len(rows) != 1 or value['Id'] != NGINX_ID or value['Image'] != NGINX_IMAGE
                    or value['Name'].lstrip('/') != 'asb-pilot-nginx'
                    or set(value['NetworkSettings']['Networks']) != {'asb-pilot-net'}):
                raise ValueError()
            proxy_state = value['State']
            if (type(proxy_state.get('Running')) is not bool
                    or (not proxy_state['Running'] and (proxy_state.get('ExitCode') != 0
                        or proxy_state.get('OOMKilled') is not False or proxy_state.get('Error') != ''))):
                raise ValueError()
            mounts = value['Mounts']
            expected = {'/etc/nginx/nginx.conf': '/etc/ai-story-book/pilot/private/nginx.conf',
                        '/var/www/certbot': '/etc/ai-story-book/acme-webroot',
                        '/etc/letsencrypt': '/etc/ai-story-book/letsencrypt'}
            if (not isinstance(mounts, list) or len(mounts) != len(expected)
                    or {m['Destination']: m['Source'] for m in mounts} != expected
                    or any(m.get('Type') != 'bind' or m.get('RW') is not False for m in mounts)):
                raise ValueError()
            _verify_file(Path(expected['/etc/nginx/nginx.conf']), NGINX_CONF_SHA, uid=0)
            self._verify_running_proxy_bind(value, expected['/etc/nginx/nginx.conf'])
            for source in (expected['/var/www/certbot'], expected['/etc/letsencrypt']):
                info = os.lstat(source)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                    raise ValueError()
            host = dict(value['HostConfig'])
            host.pop('RestartPolicy', None)
            frozen = {'config': value['Config'], 'host': host, 'mounts': _ordered_mounts(mounts)}
            digest = hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(',', ':')).encode()).digest()
            if self._nginx_fingerprint is None:
                self._nginx_fingerprint = digest
            if digest != self._nginx_fingerprint:
                raise ValueError()
            return {'id': NGINX_ID, 'running': value['State']['Running'],
                    'restart_policy': value['HostConfig']['RestartPolicy']['Name'], 'identity_verified': True}
        except Exception:
            raise AdapterError('Pinned proxy configuration differs') from None

    def drain_ingress(self):
        drain_public_proxy(directory=STATE, transaction=self.transaction, nginx_id=NGINX_ID,
            inspect=lambda _: self._proxy(),
            disable_restart=lambda ident: self._call(['update', '--restart=no', ident]),
            graceful_quit=lambda ident: self._call(['exec', ident, 'nginx', '-s', 'quit']))

    def assert_ingress_drained(self):
        value = self._proxy()
        if value['running'] is not False or value['restart_policy'] != 'no':
            raise AdapterError('Public proxy is not drained')

    def _run_script(self, identifier, source, argument, expected, *, timeout=60):
        try:
            result = subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
                'exec', '-i', identifier, 'python', '-', argument], input=source,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
        except (OSError, subprocess.SubprocessError):
            raise AdapterError('Pinned runtime check failed or is indeterminate') from None
        if argument == '--worker' and result.returncode == 1 and result.stdout == b'QUEUE_DRAIN_FAILED\n':
            raise QueueDrainPending('Worker drain is not yet confirmed')
        if result.returncode or result.stdout != expected:
            raise AdapterError('Pinned runtime check failed or is indeterminate')

    def _wait_worker_queue_drain(self, worker_id):
        if worker_id not in (self.ids['old_worker'], self.ids['new_worker']):
            raise AdapterError('Worker identity differs')
        source = portless._source('provider_cutover_queue_probe.py', portless.QUEUE_SHA256)
        deadline = time.monotonic() + 300
        while True:
            try:
                self._run_script(worker_id, source, '--worker', b'QUEUE_DRAIN_OK\n', timeout=60)
                return
            except QueueDrainPending:
                if time.monotonic() >= deadline:
                    raise AdapterError('Worker, database, or broker did not drain') from None
                time.sleep(3)

    def drain_worker_and_queues(self):
        self._wait_worker_queue_drain(self.ids['old_worker'])

    def preserve_accepted_work_and_quarantine(self, ids):
        """Do not stop a live worker until accepted work is known drained.

        If Docker state or drain is indeterminate, raise with the recovery
        marker intact; the database, broker and privacy journal are untouched.
        """
        if ids != self.ids:
            raise AdapterError('Recovery identities differ')
        self.assert_no_unresolved_daemon_operations()
        self.drain_ingress()
        self.assert_ingress_drained()
        for slot in ('old_api', 'new_api'):
            identifier = ids[slot]
            item = self.inspect(identifier)
            if item['restart_policy'] != 'no':
                self.disable_restart(identifier)
            if item['running']:
                self.stop(identifier)
        running = []
        for slot in ('old_worker', 'new_worker'):
            identifier = ids[slot]
            if self.inspect(identifier)['running']:
                running.append(identifier)
        if len(running) > 1:
            raise AdapterError('Multiple workers require reconciliation')
        if running:
            # If this times out, keep the worker running and preserve queued
            # work; the recovery marker continues to block normal backups.
            self._wait_worker_queue_drain(running[0])
        for slot in ('old_worker', 'new_worker'):
            identifier = ids[slot]
            item = self.inspect(identifier)
            if item['restart_policy'] != 'no':
                self.disable_restart(identifier)
            if item['running']:
                self.stop(identifier)
        self.assert_no_unresolved_daemon_operations()

    def probe_equivalent_provider(self, identifier):
        if identifier != self.ids['new_api'] or self.probe_id is None or self.lock_fd is None:
            raise AdapterError('Probe identity is unavailable')
        probe_id = self.probe_id
        def execute():
            self.stage_runtime._run(['start', probe_id])
            portless.run_inside_owned_probe(runtime=self.stage_runtime, probe_id=probe_id,
                candidate_id=identifier, image_id=API_IMAGE, transaction_id=self.transaction,
                lock_fd=self.lock_fd, state_dir=str(STATE), evidence=self.evidence,
                overlay_path=OVERLAY_PATH, overlay_sha256=self.overlay_sha256, key_path=KEY_PATH)
            self.stage_runtime._run(['kill', '--signal=TERM', probe_id])
            deadline = time.monotonic() + 90
            while True:
                state = self.stage_runtime.inspect(probe_id)['State']
                if not state['Running']:
                    if state.get('ExitCode') != 0 or state.get('OOMKilled') is not False or state.get('Error') != '':
                        raise AdapterError('Portless probe did not exit cleanly')
                    break
                if time.monotonic() >= deadline:
                    raise AdapterError('Portless probe did not exit')
                time.sleep(0.25)
            self.stage_runtime.remove(probe_id)
        def verified():
            return stage.clear_probe_owner_after_compound(runtime=self.stage_runtime, probe_id=probe_id,
                candidate_id=identifier, image_id=API_IMAGE, transaction_id=self.transaction,
                lock_fd=self.lock_fd, state_dir=str(STATE))
        run_journaled(STATE, transaction=self.transaction, action='provider-probe', container=probe_id,
                      execute=execute, verify=verified)
        self.probe_id = None
        self.probe_owner = None

    def _bound(self, identifier, image):
        return stage.verify_running_bound_files(runtime=self.stage_runtime, identifier=identifier,
            image_id=image, transaction_id=self.transaction, evidence=self.evidence,
            overlay_path=OVERLAY_PATH, overlay_sha256=self.overlay_sha256, key_path=KEY_PATH)

    def assert_api_ready(self, identifier):
        if identifier != self.ids['new_api'] or not self._bound(identifier, API_IMAGE):
            raise AdapterError('API bind identity differs')
        script = (b'import urllib.request\n'
                  b'o=urllib.request.build_opener(urllib.request.ProxyHandler({}))\n'
                  b'r=o.open("http://127.0.0.1:8000/health/ready",timeout=10)\n'
                  b'assert r.status==200\nprint("API_READY")\n')
        deadline = time.monotonic() + 90
        while True:
            try:
                self._run_script(identifier, script, '--readiness', b'API_READY\n', timeout=20)
                return
            except AdapterError:
                if time.monotonic() >= deadline:
                    raise AdapterError('Candidate API readiness did not pass') from None
                time.sleep(2)

    def assert_worker_healthy(self, identifier):
        if identifier != self.ids['new_worker'] or not self._bound(identifier, WORKER_IMAGE):
            raise AdapterError('Worker bind identity differs')
        try:
            config = self.stage_runtime.inspect(identifier)['Config']
            hostname = config['Hostname']
            if not isinstance(hostname, str) or not hostname or len(hostname) > 253:
                raise ValueError()
            expected_worker = 'celery@' + hostname
        except Exception:
            raise AdapterError('Worker hostname is unavailable') from None
        deadline = time.monotonic() + 90
        while True:
            try:
                for kind in ('ping', 'active_queues'):
                    raw = self._call(['exec', identifier, 'celery', '-A', 'src.worker', 'inspect', kind,
                                      '--timeout', '10', '--json'], timeout=30)
                    value = json.loads(raw)
                    if not isinstance(value, dict) or set(value) != {expected_worker}:
                        raise ValueError()
                    if kind == 'ping' and value[expected_worker] != {'ok': 'pong'}:
                        raise ValueError()
                    if kind == 'active_queues':
                        queues = value[expected_worker]
                        if (not isinstance(queues, list) or len(queues) != 1
                                or not isinstance(queues[0], dict) or queues[0].get('name') != 'celery'):
                            raise ValueError()
                return
            except Exception:
                if time.monotonic() >= deadline:
                    raise AdapterError('Pinned new worker did not respond on the expected queue') from None
                time.sleep(2)

    def reload_proxy(self):
        self.assert_ingress_drained()

    def open_ingress(self):
        self.assert_ingress_drained()
        run_journaled(STATE, transaction=self.transaction, action='start', container=NGINX_ID,
            execute=lambda: self._call(['start', NGINX_ID]), verify=lambda: self._proxy()['running'] is True)
        run_journaled(STATE, transaction=self.transaction, action='restart-unless-stopped', container=NGINX_ID,
            execute=lambda: self._call(['update', '--restart=unless-stopped', NGINX_ID]),
            verify=lambda: self._proxy()['restart_policy'] == 'unless-stopped')

    def _assert_https_ready(self):
        # Connect to local nginx while verifying the pilot IP certificate and
        # routing through nginx; this is not an external reachability test.
        try:
            result = subprocess.run(['/usr/bin/curl', '--silent', '--show-error', '--fail',
                '--noproxy', '*', '--output', '/dev/null', '--write-out', '%{http_code}',
                '--connect-timeout', '5', '--max-time', '25',
                '--resolve', HTTPS_IP + ':443:127.0.0.1',
                'https://' + HTTPS_IP + '/health/ready'], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=30, check=False,
                env={'PATH': '/usr/bin:/bin', 'HOME': '/root'})
            if result.returncode or result.stdout != b'200':
                raise ValueError()
        except Exception:
            raise AdapterError('HTTPS readiness through the public proxy failed') from None

    def assert_live_candidate(self, api, worker):
        self.assert_api_ready(api)
        self.assert_worker_healthy(worker)
        self._assert_https_ready()
        proxy = self._proxy()
        if proxy['running'] is not True or proxy['restart_policy'] != 'unless-stopped':
            raise AdapterError('Public proxy did not restart')

    def complete_candidate_owner(self):
        identity = stage._read_owned_record(str(STATE / 'candidate-owner.json'), self.candidate_owner)
        current = os.lstat(STATE / 'candidate-owner.json')
        if (current.st_dev, current.st_ino) != identity:
            raise AdapterError('Candidate ownership changed')
        os.unlink(STATE / 'candidate-owner.json')
        _sync_dir(STATE)
