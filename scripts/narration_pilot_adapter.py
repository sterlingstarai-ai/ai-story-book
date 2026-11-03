"""Concrete pilot container/backup adapter, closed until release guards exist.

This module is not a CLI. It never authorizes a release or a production
restore. Its preflight intentionally refuses operation until a real external
writer fence, independent privacy/media recovery proof, and reboot-safe
admission control have been implemented and independently verified.
"""
from contextlib import ExitStack
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile

from manage_privacy_purge_monitor import ROOT as MONITOR_ROOT, UNIT_DIR, UNITS, bundle_check, checked_file, digest

from narration_container_controls import NarrationContainerControls
from narration_deploy_safety import _validate_ids
from narration_fenced_backup_probe import fenced_backup_probe
from quarantined_backup_ingest import _dispose_owned, ingest_verified_backup
from quarantined_restore_adapter import restore_in_owned_sandbox
from quarantined_replay_adapter import prepare_isolated_replay


class PilotAdapterError(RuntimeError):
    pass


class NarrationPilotAdapter:
    """Bind the real Docker controls and fenced backup to one release lifetime.

    `backup_arguments` are passed to the existing backup primitive and may
    contain credentials. They remain in memory and must never be logged.
    """

    def __init__(self, *, runtime, identities, image_ids, backup_arguments, expected_google_project,
                 expected_daily_limit, expected_monthly_limit,
                 proxy_id, proxy_image_id, expected_proxy_config_sha256,
                 expected_monitor_manifest_sha256,
                 quarantine_arguments=None, witness_factory=None,
                 expected_narration_only=False):
        self.runtime = runtime
        self.identities = _validate_ids(identities)
        self.image_ids = dict(image_ids)
        self.backup_arguments = dict(backup_arguments)
        self.quarantine_arguments = dict(quarantine_arguments) if quarantine_arguments is not None else None
        self.witness_factory = witness_factory
        if not isinstance(expected_google_project, str) or not re.fullmatch(
                '[a-z][a-z0-9-]{4,28}[a-z0-9]', expected_google_project):
            raise PilotAdapterError('Google project identity is invalid')
        self.expected_google_project = expected_google_project
        if (type(expected_daily_limit) is not int or type(expected_monthly_limit) is not int
                or not 0 < expected_daily_limit <= expected_monthly_limit):
            raise PilotAdapterError('Explicit positive daily and monthly limits are required')
        self.expected_daily_limit = expected_daily_limit
        self.expected_monthly_limit = expected_monthly_limit
        if type(expected_narration_only) is not bool:
            raise PilotAdapterError('Narration-only mode must be explicitly boolean')
        self.expected_narration_only = expected_narration_only
        if (not isinstance(expected_monitor_manifest_sha256, str)
                or not re.fullmatch('[0-9a-f]{64}', expected_monitor_manifest_sha256)):
            raise PilotAdapterError('Pinned monitor manifest is required')
        self.expected_monitor_manifest_sha256 = expected_monitor_manifest_sha256
        if (not isinstance(proxy_id, str) or not re.fullmatch('[0-9a-f]{64}', proxy_id)
                or not isinstance(proxy_image_id, str) or not re.fullmatch('sha256:[0-9a-f]{64}', proxy_image_id)
                or not isinstance(expected_proxy_config_sha256, str)
                or not re.fullmatch('[0-9a-f]{64}', expected_proxy_config_sha256)):
            raise PilotAdapterError('Proxy identity is invalid')
        self.proxy_id = proxy_id
        self.proxy_image_id = proxy_image_id
        self.expected_proxy_config_sha256 = expected_proxy_config_sha256
        self.controls = NarrationContainerControls(runtime)
        self.stack = ExitStack()
        self.fence = None
        self.evidence = None
        self._preflight_complete = False
        self._migrated = False
        self._isolated_verified = False
        self._quarantine_live = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self._discard_quarantine()
        finally:
            self.stack.close()  # An uncommitted transaction always rolls back.
            self.fence = None
            self.evidence = None
            self._preflight_complete = False

    def _discard_quarantine(self):
        if self._quarantine_live:
            args = self.quarantine_arguments
            if not _dispose_owned(args['container_id'], args['image_id'], args['token']):
                raise PilotAdapterError('Owned quarantine cleanup could not be verified')
            self._quarantine_live = False

    def _ids(self, identities):
        if _validate_ids(identities) != self.identities:
            raise PilotAdapterError('Release container identities changed')

    def _require_preflight(self):
        if not self._preflight_complete:
            raise PilotAdapterError('Pilot release preconditions are not established')

    def _full_inspect(self, identifier):
        try:
            raw = json.loads(self.runtime._run('inspect', identifier))
            if not isinstance(raw, list) or len(raw) != 1 or raw[0].get('Id') != identifier:
                raise ValueError('invalid container')
            return raw[0]
        except Exception:
            # Docker inspect contains environment values; never surface them.
            raise PilotAdapterError('Container configuration cannot be inspected') from None

    @staticmethod
    def _environment(item):
        try:
            result = {}
            for pair in item['Config']['Env']:
                if not isinstance(pair, str) or '=' not in pair:
                    raise ValueError('invalid variable')
                key, value = pair.split('=', 1)
                if not key or key in result:
                    raise ValueError('duplicate variable')
                result[key] = value
            return result
        except Exception:
            raise PilotAdapterError('Container environment is ambiguous') from None

    @staticmethod
    def _mounts(item):
        try:
            mounts = item['Mounts']
            if not isinstance(mounts, list):
                raise ValueError('invalid mounts')
            if any(not isinstance(m, dict) or type(m.get('RW')) is not bool
                   or any(not isinstance(m.get(key), str) or not m[key]
                          for key in ('Type', 'Source', 'Destination')) for m in mounts):
                raise ValueError('invalid mount entry')
            return sorted((m['Type'], m['Source'], m['Destination'], m['RW']) for m in mounts)
        except Exception:
            raise PilotAdapterError('Container mounts cannot be compared') from None

    def _verify_configurations(self):
        allowed = {'AUDIO_FEATURE_ENABLED', 'AUDIO_NARRATION_ONLY_ENABLED', 'TTS_PROVIDER', 'GOOGLE_GEMINI_TTS_PROJECT',
                   'GOOGLE_GEMINI_TTS_DAILY_REQUEST_LIMIT', 'GOOGLE_GEMINI_TTS_MONTHLY_REQUEST_LIMIT'}
        for role in ('api', 'worker'):
            old = self._full_inspect(self.identities['old_' + role])
            new = self._full_inspect(self.identities['new_' + role])
            before, after = self._environment(old), self._environment(new)
            if ({k: v for k, v in before.items() if k not in allowed}
                    != {k: v for k, v in after.items() if k not in allowed}):
                raise PilotAdapterError('Staged environment differs outside narration settings')
            if (after.get('AUDIO_FEATURE_ENABLED', '').lower() != 'true'
                    or after.get('AUDIO_NARRATION_ONLY_ENABLED', 'false').lower()
                    != ('true' if self.expected_narration_only else 'false')
                    or after.get('TTS_PROVIDER', '').lower() != 'google_gemini'
                    or after.get('GOOGLE_GEMINI_TTS_PROJECT') != self.expected_google_project
                    or after.get('GOOGLE_GEMINI_TTS_DAILY_REQUEST_LIMIT') != str(self.expected_daily_limit)
                    or after.get('GOOGLE_GEMINI_TTS_MONTHLY_REQUEST_LIMIT') != str(self.expected_monthly_limit)):
                raise PilotAdapterError('Staged narration configuration does not match')
            if self._mounts(old) != self._mounts(new):
                raise PilotAdapterError('Staged mounts differ from reviewed running containers')
            try:
                if old['HostConfig']['NetworkMode'] != new['HostConfig']['NetworkMode']:
                    raise ValueError('network mode mismatch')
            except (KeyError, TypeError, ValueError):
                raise PilotAdapterError('Staged network configuration does not match') from None

    def _verify_monitor_precedes_candidate(self):
        """Require the pinned active monitor's health code in both images."""
        try:
            root_stat = MONITOR_ROOT.lstat()
            if (not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != 0
                    or root_stat.st_mode & 0o022):
                raise ValueError('monitor root is unsafe')
            current = MONITOR_ROOT / 'current'
            if not current.is_symlink():
                raise ValueError('monitor current is missing')
            target = os.readlink(current)
            if not re.fullmatch('[A-Za-z0-9._-]+', target) or target in {'.', '..'}:
                raise ValueError('monitor target is invalid')
            release = MONITOR_ROOT / target
            files = bundle_check(release, self.expected_monitor_manifest_sha256)
            expected = files['apps/api/src/services/privacy_purge_health.py']
            for name in UNITS:
                unit = UNIT_DIR / name
                checked_file(unit)
                if digest(unit) != files['infra/gcp-pilot/' + name]:
                    raise ValueError('monitor unit differs')
                for prop, wanted in (('FragmentPath', str(unit)), ('NeedDaemonReload', 'no')):
                    result = subprocess.run(['systemctl', 'show', name, '--property=' + prop, '--value'],
                                            capture_output=True, timeout=15, check=True)
                    if result.stdout.decode().strip() != wanted:
                        raise ValueError('loaded monitor unit differs')
            for args, wanted in ((('is-active', UNITS[1]), 'active'), (('is-enabled', UNITS[1]), 'enabled')):
                result = subprocess.run(['systemctl', *args], capture_output=True, timeout=15, check=True)
                if result.stdout.decode().strip() != wanted:
                    raise ValueError('monitor timer is inactive')
            for slot in ('new_api', 'new_worker'):
                result = subprocess.run(['docker', 'cp', self.identities[slot] +
                                         ':/app/src/services/privacy_purge_health.py', '-'],
                                        capture_output=True, timeout=20, check=True)
                if len(result.stdout) > 1024 * 1024:
                    raise ValueError('candidate health module is too large')
                with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:') as archive:
                    members = archive.getmembers()
                    if len(members) != 1 or not members[0].isfile() or members[0].size > 512 * 1024:
                        raise ValueError('candidate health module is invalid')
                    content = archive.extractfile(members[0]).read()
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError('monitor is older than staged image')
            if os.readlink(current) != target:
                raise ValueError('monitor changed during verification')
            bundle_check(release, self.expected_monitor_manifest_sha256)
        except Exception:
            raise PilotAdapterError('Pinned current privacy monitor is not established') from None

    def preflight(self, identities):
        """Inspect exact containers, then fail closed on unavailable guarantees."""
        self._ids(identities)
        self.controls.verify_pinned_images(self.identities, self.image_ids)
        names = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
                 'new_api': 'asb-narration-next-api', 'new_worker': 'asb-narration-next-worker'}
        for slot, identifier in self.identities.items():
            item = self.runtime.inspect(identifier)
            if item.get('id') != identifier or item.get('name') != names[slot]:
                raise PilotAdapterError('Container identity or name changed')
            if item.get('running') is not slot.startswith('old_'):
                raise PilotAdapterError('Container state is not ready for staging')
            if slot.startswith('new_') and item.get('restart_policy') != 'no':
                raise PilotAdapterError('Staged container restart policy is unsafe')
        self._verify_configurations()
        self._verify_monitor_precedes_candidate()
        self._verify_proxy()
        # Merely passing callbacks or operator-supplied booleans cannot prove
        # storage/admission isolation, newest privacy history, media replay, or
        # Docker-vs-systemd behavior after a real reboot. No success branch or
        # configuration override is offered until those controls exist.
        raise PilotAdapterError('Independent write, restore and reboot guards are not yet implemented')

    def stop_and_drain(self, identities):
        self._require_preflight()
        self._ids(identities)
        return self.controls.stop_and_drain(identities)

    def disable_restart(self, identities):
        self._require_preflight()
        self._ids(identities)
        return self.controls.disable_restart(identities)

    def backup_and_restore_verify(self):
        self._require_preflight()
        if self.fence is not None:
            raise PilotAdapterError('A backup fence is already active')
        try:
            self.fence, self.evidence = self.stack.enter_context(fenced_backup_probe(**self.backup_arguments))
            if self.evidence.get('status') != 'FENCED_BACKUP_DATABASE_PROBED':
                raise PilotAdapterError('Fresh fenced backup is unverified')
            if self.quarantine_arguments is not None:
                self.fence.verify()
                imported = ingest_verified_backup(
                    store=self.backup_arguments['store'], run_id=self.evidence['run_id'],
                    expected_manifest_sha256=self.evidence['manifest_sha256'],
                    expected_revision=self.evidence['revision'], **self.quarantine_arguments)
                self.fence.verify()
                if (imported.get('status') != 'BACKUP_IMPORTED_QUARANTINED'
                        or imported.get('restore_authorized') is not False
                        or imported.get('privacy_replay_verified') is not False):
                    raise PilotAdapterError('Quarantined backup import is unverified')
                self._quarantine_live = True
                restored = restore_in_owned_sandbox(**self.quarantine_arguments)
                if (restored.get('status') != 'DATABASE_AND_MEDIA_RESTORED_QUARANTINED'
                        or restored.get('restore_authorized') is not False
                        or restored.get('privacy_replay_verified') is not False):
                    raise PilotAdapterError('Quarantined database and media restore is unverified')
                self.fence.verify()
                if self.witness_factory is not None:
                    replay = prepare_isolated_replay(witness_factory=self.witness_factory,
                                                     **self.quarantine_arguments)
                    if (replay.get('status') != 'REPLAY_BLOCKED_LATEST_HISTORY_UNPROVEN'
                            or replay.get('privacy_replay_applied') is not False
                            or replay.get('restore_authorized') is not False):
                        raise PilotAdapterError('Quarantined replay preflight is invalid')
                    self.fence.verify()
            elif self.witness_factory is not None:
                raise PilotAdapterError('A quarantined target is required for witness verification')
            if (self.evidence.get('media_restore_verified') is not True
                    or self.evidence.get('migration_authorized') is not True):
                # DB-only restore is insufficient. Never promote it.
                self._discard_quarantine()
                self.stack.close()
                self.fence = None
                self.evidence = None
                return False
            return True
        except BaseException:
            try:
                self._discard_quarantine()
            finally:
                self.stack.close()
                self.fence = None
                self.evidence = None
            raise

    def migrate(self):
        self._require_preflight()
        if self.fence is None or self.evidence is None:
            raise PilotAdapterError('Verified backup fence is missing')
        self.fence.migrate(assert_backup_restored=lambda: (
            self.evidence is not None and self.evidence.get('media_restore_verified') is True
            and self.evidence.get('migration_authorized') is True))
        self.fence.commit()
        self._migrated = True
        return True

    def _require_migrated(self):
        self._require_preflight()
        if not self._migrated:
            raise PilotAdapterError('Verified migration has not committed')

    def start_isolated(self, identities):
        self._require_migrated()
        self._ids(identities)
        for slot in ('new_api', 'new_worker'):
            item = self.runtime.inspect(self.identities[slot])
            if item.get('running') is not False or item.get('restart_policy') != 'no':
                raise PilotAdapterError('Staged container state changed')
            self.runtime._run('start', self.identities[slot])
        return True

    def verify_isolated(self):
        self._require_migrated()
        self._verify_proxy()
        self._verify_api_and_worker()
        # Readiness does not prove proxy/network isolation or worker queue
        # fencing. Those controls remain unimplemented and fail closed.
        return False

    def _verify_proxy(self):
        try:
            item = self._full_inspect(self.proxy_id)
            if (item.get('Name') != '/asb-pilot-nginx' or item.get('Image') != self.proxy_image_id
                    or item.get('State', {}).get('Running') is not True):
                raise ValueError('proxy identity changed')
            process = subprocess.run(['docker', 'exec', self.proxy_id, 'nginx', '-T'],
                                     capture_output=True, check=True, timeout=30)
            config = process.stdout
            if (hashlib.sha256(config).hexdigest() != self.expected_proxy_config_sha256
                    or not re.search(rb'(?m)^\s*server\s+asb-pilot-api:8000(?:\s|;)', config)
                    or b'asb-narration-next-api' in config):
                raise ValueError('proxy configuration changed')
        except Exception:
            # The configuration may contain paths or private material.
            raise PilotAdapterError('Proxy identity or configuration cannot be verified') from None

    def _verify_api_and_worker(self):
        api = self.identities['new_api']
        worker = self.identities['new_worker']
        try:
            for identifier in (api, worker):
                if self.runtime.inspect(identifier).get('running') is not True:
                    raise ValueError('container stopped')
            # Probe locally inside the exact API container; no response body is
            # printed or exported to the caller.
            self.runtime._run('exec', api, 'python', '-c',
                              "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=5); "
                              "assert r.status==200")
            host = self._full_inspect(worker)['Config']['Hostname']
            if not isinstance(host, str) or not re.fullmatch('[A-Za-z0-9_.-]{1,253}', host):
                raise ValueError('worker hostname invalid')
            raw = self.runtime._run('exec', worker, 'celery', '-A', 'src.worker',
                                    'inspect', 'ping', '--timeout', '10', '--json')
            response = json.loads(raw)
            if response != {'celery@' + host: {'ok': 'pong'}}:
                raise ValueError('worker identity or ping mismatch')
        except Exception:
            raise PilotAdapterError('Candidate API or worker readiness cannot be verified') from None

    def enable_new_restart(self, identities):
        self._require_migrated()
        self._ids(identities)
        return self.controls.enable_new_restart(identities)

    def publish(self):
        self._require_migrated()
        if not self._isolated_verified:
            raise PilotAdapterError('Ingress isolation is not verified')
        self._verify_proxy()
        self._verify_api_and_worker()
        for slot, expected in (('old_api', 'asb-pilot-api'), ('old_worker', 'asb-pilot-worker'),
                               ('new_api', 'asb-narration-next-api'), ('new_worker', 'asb-narration-next-worker')):
            item = self.runtime.inspect(self.identities[slot])
            if (item.get('id') != self.identities[slot] or item.get('name') != expected
                    or item.get('restart_policy') != 'no'
                    or item.get('running') is not slot.startswith('new_')):
                raise PilotAdapterError('Container state changed before publication')
        # The durable marker is held by the orchestrator throughout this
        # sequence. Any failure quarantines all recorded identities; the old
        # images are never restarted against the migrated schema.
        self.runtime._run('rename', self.identities['old_worker'], 'asb-pilot-worker-before-narration')
        self.runtime._run('rename', self.identities['old_api'], 'asb-pilot-api-before-narration')
        self.runtime._run('rename', self.identities['new_worker'], 'asb-pilot-worker')
        self.runtime._run('rename', self.identities['new_api'], 'asb-pilot-api')
        self._verify_proxy()
        self.runtime._run('exec', self.proxy_id, 'nginx', '-t')
        self.runtime._run('exec', self.proxy_id, 'nginx', '-s', 'reload')
        return True

    def verify_published(self):
        self._require_migrated()
        if not self._isolated_verified:
            raise PilotAdapterError('Ingress isolation is not verified')
        self._verify_proxy()
        self._verify_api_and_worker()
        for slot, expected in (('old_api', 'asb-pilot-api-before-narration'),
                               ('old_worker', 'asb-pilot-worker-before-narration'),
                               ('new_api', 'asb-pilot-api'), ('new_worker', 'asb-pilot-worker')):
            item = self.runtime.inspect(self.identities[slot])
            if item.get('id') != self.identities[slot] or item.get('name') != expected:
                raise PilotAdapterError('Published container identity differs')
        try:
            item = self._full_inspect(self.identities['new_api'])
            address = item['NetworkSettings']['Networks']['asb-pilot-net']['IPAddress']
            if not isinstance(address, str) or not re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}', address):
                raise ValueError('invalid API address')
            resolved = self.runtime._run('exec', self.proxy_id, 'getent', 'hosts', 'asb-pilot-api')
            if address not in {line.split()[0] for line in resolved.splitlines() if line.split()}:
                raise ValueError('proxy DNS mismatch')
            self.runtime._run('exec', self.proxy_id, 'wget', '-q', '-O', '/dev/null',
                              'http://asb-pilot-api:8000/health/ready')
        except Exception:
            raise PilotAdapterError('Published API route cannot be verified') from None
        return True
