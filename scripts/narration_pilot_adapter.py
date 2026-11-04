"""Bind pilot containers, storage permissions and recovery proof to a release.

Preflight accepts the planned storage-only detach or a post-detach narration
release with the retired writer denied and an independent restore verifier.
"""
from contextlib import ExitStack, closing
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import syslog
import tarfile
import tempfile
import time

from dotenv import dotenv_values
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import narration_deploy_safety as safety
from backup_external import database_environment, inventory, storage_client
from manage_privacy_purge_monitor import (BUNDLE_FILES, PYTHON as MONITOR_PYTHON, ROOT as MONITOR_ROOT,
    UNIT_DIR, UNITS, checked_file, config_paths as monitor_config_paths, digest, run as run_monitor)

from media_cutover_preflight import (
    MediaCutoverError, _verify_empty_source_history, gcs_freeze_canary_payload, verify_empty_media_detach,
    verify_frozen_gcs_writer, verify_source_storage_permissions, verify_staged_media_cutover,
    verify_staged_target_writer,
)
from narration_container_controls import NarrationContainerControls
from narration_deploy_safety import WorkerDrainUnverified, _validate_ids
from narration_fenced_backup_probe import fenced_backup_probe
from narration_release_backup import SOURCE_REVISION
from postgres_backup_fence import PostgresBackupFence
from provider_cutover_portless_exec import QUEUE_SHA256, _source
from publish_backup_gcs import _valid_checkpoint
from quarantined_backup_ingest import _dispose_owned, ingest_verified_backup
from quarantined_restore_adapter import restore_in_owned_sandbox
from quarantined_replay_adapter import prepare_isolated_replay
from run_scheduled_backup import private_file
from run_pilot_provider_refresh import bootstrap_isolated_narration
from update_privacy_purge_monitor import _validate_installed_release


class PilotAdapterError(RuntimeError):
    pass


MEDIA_STAGE_PATH = Path('/etc/ai-story-book/pilot/private/media-gcs-stage.env')
MEDIA_READER_PATH = Path('/etc/ai-story-book/pilot/private/media-neon-reader.stage.env')
PRIVATE_CONFIG_DIR = MEDIA_STAGE_PATH.parent
NARRATION_BOOTSTRAP_LEDGER = Path('/var/lib/ai-story-book/provider-refresh/narration-bootstrap.sqlite')
OLD_CONFIG_OVERLAY = ('bind', '/etc/ai-story-book/pilot/private/provider-rotation/config.py',
                      '/app/src/core/config.py', False)


class NarrationPilotAdapter:
    """Bind the real Docker controls and fenced backup to one release lifetime.

    `backup_arguments` are passed to the existing backup primitive and may
    contain credentials. They remain in memory and must never be logged.
    """

    gcs_narration = False

    def __init__(self, *, runtime, identities, image_ids, backup_arguments, expected_google_project,
                 expected_daily_limit, expected_monthly_limit,
                 proxy_id, proxy_image_id, expected_proxy_config_sha256,
                 expected_monitor_manifest_sha256,
                 quarantine_arguments=None, witness_factory=None,
                 expected_narration_only=False, expected_gcs_media=False, service_config_generation=None,
                 storage_only=False, offhost_restore=None, retired_neon=None, freeze_canary=None):
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
        if type(expected_gcs_media) is not bool:
            raise PilotAdapterError('Media transition must be explicitly boolean')
        self.expected_gcs_media = expected_gcs_media
        if type(storage_only) is not bool or (storage_only and (not expected_gcs_media or expected_narration_only)):
            raise PilotAdapterError('Storage-only transition mode is invalid')
        self.storage_only = storage_only
        self.gcs_narration = retired_neon is not None
        if self.gcs_narration and (not isinstance(retired_neon, dict) or storage_only
                or not expected_gcs_media or not expected_narration_only or offhost_restore is None):
            raise PilotAdapterError('Post-detach narration requires exact GCS and retired Neon bindings')
        if self.gcs_narration:
            gcs_freeze_canary_payload(freeze_canary)
        elif freeze_canary is not None:
            raise PilotAdapterError('Only post-detach narration uses a freeze canary')
        self.freeze_canary = freeze_canary
        self.retired_neon = dict(retired_neon) if self.gcs_narration else None
        if ('offhost_restore' in self.backup_arguments or (offhost_restore is not None and (
                not (storage_only or self.gcs_narration) or quarantine_arguments is not None or witness_factory is not None
                or self.backup_arguments.get('image_id') is not None
                or not isinstance(offhost_restore, tuple) or len(offhost_restore) != 2
                or not isinstance(offhost_restore[0], Ed25519PublicKey) or not callable(offhost_restore[1])))):
            raise PilotAdapterError('Off-host restore verifier is invalid')
        self.offhost_restore = offhost_restore
        if service_config_generation is not None and (
                not isinstance(service_config_generation, str)
                or not re.fullmatch(r'v[1-9][0-9]{0,3}', service_config_generation)):
            raise PilotAdapterError('Service configuration generation is invalid')
        self.service_config_generation = service_config_generation
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
        self._restore_verified = False
        self._preflight_complete = False
        self._publication_started = False
        self._migrated = False
        self._isolated_verified = False
        self._isolated_generation = None
        self._quarantine_live = False
        self._media_cutover = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self._discard_quarantine()
        finally:
            self.stack.close()  # An uncommitted transaction always rolls back.
            self.fence = None
            self.evidence = None
            self._restore_verified = False
            self._preflight_complete = False
            self._media_cutover = None

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

    def _expected_media_changes(self, before):
        try:
            raw = private_file(MEDIA_STAGE_PATH, max_bytes=8192).decode('ascii')
            match = re.fullmatch(r'S3_ACCESS_KEY=([A-Za-z0-9]+)\nS3_SECRET_KEY=([A-Za-z0-9+/=]+)\n', raw)
            if not match or not before.get('S3_PUBLIC_URL'):
                raise ValueError()
            access, secret = match.groups()
            if access == before.get('S3_ACCESS_KEY') or secret == before.get('S3_SECRET_KEY'):
                raise ValueError()
            bucket = 'asb-media-' + self.expected_google_project
            legacy = ','.join(filter(None, (before.get('S3_LEGACY_PUBLIC_URLS'), before['S3_PUBLIC_URL'])))
            return {
                'S3_ACCESS_KEY': access, 'S3_SECRET_KEY': secret, 'S3_BUCKET': bucket,
                'S3_ENDPOINT': 'https://storage.googleapis.com', 'S3_DOWNLOAD_ENDPOINT': 'https://storage.googleapis.com',
                'S3_REGION': 'us-central1', 'S3_ADDRESSING_STYLE': 'path', 'S3_AUTO_CREATE_BUCKET': 'false',
                'S3_PUBLIC_URL': 'https://storage.googleapis.com/' + bucket, 'S3_LEGACY_PUBLIC_URLS': legacy,
                'PRIVACY_JOURNAL_WITNESS_BUCKET': 'asb-journal-witness-' + self.expected_google_project,
            }
        except (OSError, ValueError, RuntimeError):
            raise PilotAdapterError('Pinned media transition configuration is unavailable') from None

    def _verify_configurations(self):
        allowed = {'AUDIO_FEATURE_ENABLED', 'AUDIO_NARRATION_ONLY_ENABLED', 'TTS_PROVIDER', 'GOOGLE_GEMINI_TTS_PROJECT',
                   'GOOGLE_GEMINI_TTS_DAILY_REQUEST_LIMIT', 'GOOGLE_GEMINI_TTS_MONTHLY_REQUEST_LIMIT'}
        for role in ('api', 'worker'):
            old = self._full_inspect(self.identities['old_' + role])
            new = self._full_inspect(self.identities['new_' + role])
            before, after = self._environment(old), self._environment(new)
            expected = dict(before)
            old_mounts = self._mounts(old)
            if self.expected_gcs_media:
                if self.gcs_narration:
                    expected['PRIVACY_JOURNAL_WITNESS_BUCKET'] = 'asb-journal-witness-' + self.expected_google_project
                else:
                    expected.update(self._expected_media_changes(before))
                if old_mounts.count(OLD_CONFIG_OVERLAY) != 1:
                    raise PilotAdapterError('Reviewed configuration overlay is missing')
                old_mounts.remove(OLD_CONFIG_OVERLAY)
            if ({k: v for k, v in expected.items() if k not in allowed}
                    != {k: v for k, v in after.items() if k not in allowed}):
                raise PilotAdapterError('Staged environment differs from reviewed settings')
            if (after.get('AUDIO_FEATURE_ENABLED', '').lower() != 'true'
                    or after.get('AUDIO_NARRATION_ONLY_ENABLED', 'false').lower()
                    != ('true' if self.expected_narration_only else 'false')
                    or after.get('TTS_PROVIDER', '').lower() != 'google_gemini'
                    or after.get('GOOGLE_GEMINI_TTS_PROJECT') != self.expected_google_project
                    or after.get('GOOGLE_GEMINI_TTS_DAILY_REQUEST_LIMIT') != str(self.expected_daily_limit)
                    or after.get('GOOGLE_GEMINI_TTS_MONTHLY_REQUEST_LIMIT') != str(self.expected_monthly_limit)):
                raise PilotAdapterError('Staged narration configuration does not match')
            if old_mounts != self._mounts(new):
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
            files = _validate_installed_release(release, self.expected_monitor_manifest_sha256)
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
            if self.storage_only:
                # The standalone monitor runs its own pinned code. A media
                # detach preserves the exact API and worker images even if
                # they predate the monitor module.
                inputs = monitor_config_paths()
                run_monitor(str(MONITOR_PYTHON), str(release / BUNDLE_FILES[0]), '--execute',
                            '--env-file', str(inputs['ASB_PURGE_MONITOR_ENV_FILE']),
                            '--ca-file', str(inputs['ASB_PURGE_MONITOR_CA_FILE']))
                if os.readlink(current) != target:
                    raise ValueError('monitor changed during verification')
                _validate_installed_release(release, self.expected_monitor_manifest_sha256)
                return
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
            _validate_installed_release(release, self.expected_monitor_manifest_sha256)
        except Exception:
            raise PilotAdapterError('Pinned current privacy monitor is not established') from None

    def _verify_media_rollback_candidates(self):
        """Check pre-migration recovery can use the target storage with old code."""
        try:
            for role in ('api', 'worker'):
                old = self._full_inspect(self.identities['old_' + role])
                name = 'asb-media-rollback-' + role
                identifier = self.runtime.inspect(name)['id']
                if not re.fullmatch('[0-9a-f]{64}', identifier):
                    raise ValueError()
                candidate = self._full_inspect(identifier)
                if self.storage_only and identifier != self.identities['new_' + role]:
                    raise ValueError()
                before = self._environment(old)
                changes = self._expected_media_changes(before)
                # The pre-migration fallback retains the existing journal configuration.
                del changes['PRIVACY_JOURNAL_WITNESS_BUCKET']
                if (candidate['Name'] != '/' + name or candidate['Image'] != old['Image']
                        or candidate['State']['Running'] is not False
                        or candidate['HostConfig']['RestartPolicy']['Name'] != 'no'
                        or self._environment(candidate) != {**before, **changes}
                        or self._mounts(candidate) != self._mounts(old)
                        or any(candidate['Config'][key] != old['Config'][key]
                               for key in ('Entrypoint', 'Cmd', 'User'))
                        or candidate['HostConfig']['NetworkMode'] != old['HostConfig']['NetworkMode']
                        or candidate['HostConfig']['PortBindings'] != {}
                        or candidate['HostConfig']['PublishAllPorts'] is not False):
                    raise ValueError()
        except Exception:
            raise PilotAdapterError('Pre-migration media rollback candidates cannot be verified') from None

    @staticmethod
    def _verify_boot_quarantine():
        unit = 'asb-narration-quarantine.service'
        installed = Path('/etc/systemd/system') / unit
        expected = Path(__file__).resolve().parents[1] / 'infra' / 'gcp-pilot' / unit
        recovery_dir = Path('/opt/ai-story-book/narration-recovery')
        try:
            checked_file(installed)
            if digest(installed) != digest(expected):
                raise ValueError()
            info = recovery_dir.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError()
            for name in ('narration_deploy_safety.py', 'backup_service_guard.py'):
                recovery = recovery_dir / name
                checked_file(recovery)
                if digest(recovery) != digest(Path(__file__).with_name(name)):
                    raise ValueError()
            result = subprocess.run(
                ['/usr/bin/systemctl', 'show', unit, '--property=FragmentPath,UnitFileState,'
                 'NeedDaemonReload,DropInPaths,LoadState'],
                capture_output=True, text=True, timeout=15, check=True)
            properties = dict(line.split('=', 1) for line in result.stdout.splitlines())
            if properties != {'FragmentPath': str(installed), 'UnitFileState': 'enabled',
                              'NeedDaemonReload': 'no', 'DropInPaths': '', 'LoadState': 'loaded'}:
                raise ValueError()
        except Exception:
            raise PilotAdapterError('Boot quarantine unit or recovery code cannot be verified') from None

    def preflight(self, identities):
        """Inspect exact containers, then fail closed on unavailable guarantees."""
        self._ids(identities)
        self.controls.verify_pinned_images(self.identities, self.image_ids)
        names = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
                 'new_api': self._staged_name('api'), 'new_worker': self._staged_name('worker')}
        for slot, identifier in self.identities.items():
            item = self.runtime.inspect(identifier)
            if item.get('id') != identifier or item.get('name') != names[slot]:
                raise PilotAdapterError('Container identity or name changed')
            if item.get('running') is not slot.startswith('old_'):
                raise PilotAdapterError('Container state is not ready for staging')
            if slot.startswith('new_') and item.get('restart_policy') != 'no':
                raise PilotAdapterError('Staged container restart policy is unsafe')
        self._verify_retired_names_available()
        if not self.storage_only:
            self._verify_configurations()
        self._verify_monitor_precedes_candidate()
        self._verify_proxy()
        if self.expected_gcs_media:
            self._verify_live_network()
            self._verify_candidate_ports()
            self._verified_service_configs()
            self._verify_boot_quarantine()
            if self.gcs_narration:
                self._verify_retired_neon()
                values = self.backup_arguments['values']
                verify_staged_target_writer(values)
                with PostgresBackupFence(database_environment(values, self.backup_arguments['ca_file'])) as fence:
                    fence.verify_revision(SOURCE_REVISION)
            else:
                self._verify_media_rollback_candidates()
                source, _, target = self._media_cutover_values()
                verify_staged_target_writer(target)
                environment = database_environment(source, self.backup_arguments['ca_file'])
                with PostgresBackupFence(environment) as fence:
                    verify_empty_media_detach(fence, source, target, expected_revision=SOURCE_REVISION)
        if (self.storage_only or self.gcs_narration) and (self.offhost_restore is not None or (
                self.quarantine_arguments is not None and callable(self.witness_factory))):
            if not _valid_checkpoint(self.backup_arguments['verify_journal']()):
                raise PilotAdapterError('Live privacy journal cannot be verified before detach')
            # Catch an unreachable or busy worker while the original API can
            # still serve. Drain repeats the probe after admission closes.
            self._verify_worker_queue(self.identities['old_worker'])
            self._preflight_complete = True
            return True
        # Merely passing callbacks or operator-supplied booleans cannot prove
        # storage/admission isolation, newest privacy history, media replay, or
        # Docker-vs-systemd behavior after a real reboot. No success branch or
        # configuration override is offered until those controls exist.
        raise PilotAdapterError('Independent write, restore and reboot guards are not yet implemented')

    def _staged_name(self, role):
        prefix = 'asb-media-rollback-' if self.storage_only else 'asb-narration-next-'
        return prefix + role

    def _retired_names(self):
        return safety._RETIRED_NAMES['media' if self.storage_only else 'narration']

    def _verify_retired_names_available(self):
        for name in self._retired_names().values():
            if self.runtime._run('container', 'ls', '-aq', '--filter', f'name=^/{name}$'):
                raise PilotAdapterError('A retired container name is already in use')

    def _verify_live_network(self, *, isolated=False):
        """Reject an unexpected live peer or a host-published Redis broker."""
        try:
            raw = self.runtime._run('network', 'inspect', 'asb-pilot-net')
            networks = json.loads(raw)
            if not isinstance(networks, list) or len(networks) != 1:
                raise ValueError()
            network = networks[0]
            if network['Name'] != 'asb-pilot-net' or network['Driver'] != 'bridge':
                raise ValueError()
            peers = {identifier: peer['Name'] for identifier, peer in network['Containers'].items()}
            redis_ids = [identifier for identifier, name in peers.items() if name == 'asb-pilot-redis']
            if len(redis_ids) != 1:
                raise ValueError()
            redis = self._full_inspect(redis_ids[0])
            if (redis['Name'] != '/asb-pilot-redis' or redis['State']['Running'] is not True
                    or redis['HostConfig']['PortBindings'] or redis['HostConfig']['PublishAllPorts']):
                raise ValueError()
            expected = {redis['Id']: 'asb-pilot-redis'}
            if isolated:
                expected.update({self.identities['new_api']: self._staged_name('api'),
                                 self.identities['new_worker']: self._staged_name('worker')})
            else:
                expected.update({self.identities['old_api']: 'asb-pilot-api',
                                 self.identities['old_worker']: 'asb-pilot-worker', self.proxy_id: 'asb-pilot-nginx'})
            if peers != expected:
                raise ValueError()
        except Exception:
            raise PilotAdapterError('Pilot network or broker exposure cannot be verified') from None

    def stop_and_drain(self, identities):
        self._require_preflight()
        self._ids(identities)
        if self.expected_gcs_media:
            self._verify_proxy()
            if self.runtime.inspect(self.proxy_id).get('restart_policy') != 'no':
                raise PilotAdapterError('Proxy restart policy changed before drain')
            self.runtime.stop(self.proxy_id)
            self._verify_stopped_proxy()
        return self.controls.stop_and_drain(identities, verify_worker_drain=self._wait_worker_queue)

    def _wait_worker_queue(self, worker_id):
        try:
            self._verify_worker_queue(worker_id, wait_seconds=300)
        except PilotAdapterError as exc:
            # The exception is restricted to fixed messages from this probe.
            syslog.syslog(syslog.LOG_WARNING, 'asb-media-detach worker_drain=' + str(exc))
            raise WorkerDrainUnverified('Old worker drain is unverified') from exc

    @staticmethod
    def _verify_worker_queue(worker_id, *, wait_seconds=0):
        try:
            source = _source('provider_cutover_queue_probe.py', QUEUE_SHA256)
            deadline = time.monotonic() + wait_seconds
            while True:
                # Celery imports and control replies can be slow on the pilot
                # VM. Allow the same budget for both old and new generations.
                timeout = min(150, deadline - time.monotonic()) if wait_seconds else 150
                if timeout <= 0:
                    raise PilotAdapterError('Worker queue did not drain before the deadline')
                try:
                    checked = subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock',
                        'exec', '-i', worker_id, 'python', '-', '--worker'],
                        input=source, capture_output=True, timeout=timeout, check=False)
                except subprocess.TimeoutExpired:
                    raise PilotAdapterError('Worker queue probe exceeded its subprocess deadline') from None
                if checked.returncode == 0 and checked.stdout == b'QUEUE_DRAIN_OK\n':
                    return
                if checked.returncode != 1 or checked.stdout != b'QUEUE_DRAIN_FAILED\n':
                    raise ValueError()
                if time.monotonic() + 3 >= deadline:
                    raise PilotAdapterError('Worker, database, or broker queue drain is unverified')
                time.sleep(3)
        except PilotAdapterError:
            raise
        except Exception:
            raise PilotAdapterError('Worker, database, or broker queue drain is unverified') from None

    def disable_restart(self, identities):
        self._require_preflight()
        self._ids(identities)
        if self.controls.disable_restart(identities) is not True:
            return False
        if self.expected_gcs_media:
            self._verify_proxy()
            self.runtime.disable_restart(self.proxy_id)
            if self.runtime.inspect(self.proxy_id).get('restart_policy') != 'no':
                return False
        return True

    def recovery_proxy(self):
        return {'id': self.proxy_id, 'image_id': self.proxy_image_id} if self.expected_gcs_media else None

    @staticmethod
    def _neon_reader_values(values):
        raw = private_file(MEDIA_READER_PATH, max_bytes=1024).decode('ascii')
        reader = re.fullmatch(
            r'S3_ACCESS_KEY=(nak_live_[a-f0-9]{32})\nS3_SECRET_KEY=([A-Za-z0-9_+/=-]{16,512})\n', raw)
        if not reader or reader[1] == values['S3_ACCESS_KEY'] or reader[2] == values['S3_SECRET_KEY']:
            raise PilotAdapterError('A distinct staged source media reader is required')
        return {**values, 'S3_ACCESS_KEY': reader[1], 'S3_SECRET_KEY': reader[2]}

    def _verify_retired_neon(self):
        values = self.backup_arguments['values']
        old = self.retired_neon
        if (values['S3_ENDPOINT'] != 'https://storage.googleapis.com'
                or values['S3_BUCKET'] != 'asb-media-' + self.expected_google_project
                or old['S3_ENDPOINT'] == values['S3_ENDPOINT'] or old['S3_BUCKET'] != 'storybook-private'):
            raise PilotAdapterError('Current and retired storage identities differ from the plan')
        with closing(storage_client(self._neon_reader_values(old))) as reader, closing(storage_client(old)) as retired:
            verify_source_storage_permissions(reader, retired, old['S3_BUCKET'])
            _verify_empty_source_history(reader, old['S3_BUCKET'])
            if inventory(reader, old['S3_BUCKET']):
                raise PilotAdapterError('Retired storage contains unaccounted media')

    def _wait_for_gcs_permissions(self, verify):
        deadline = time.monotonic() + 240
        while True:
            try:
                verify(self.backup_arguments['values'])
                return
            except MediaCutoverError:
                if time.monotonic() + 12 >= deadline:
                    raise
                time.sleep(12)

    def _verify_gcs_frozen(self, values):
        verify_frozen_gcs_writer(values, self.freeze_canary)

    def _media_cutover_values(self):
        before = self._environment(self._full_inspect(self.identities['old_api']))
        values = self.backup_arguments['values']
        if any(values.get(key) != before.get(key) for key in (
                'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_ENDPOINT', 'S3_BUCKET', 'S3_REGION')):
            raise PilotAdapterError('Backup and retired source media identities differ')
        return (
            self._neon_reader_values(values),
            values,
            {**values, **self._expected_media_changes(before)},
        )

    def backup_and_restore_verify(self):
        self._require_preflight()
        if self.fence is not None:
            raise PilotAdapterError('A backup fence is already active')
        try:
            backup_arguments = self.backup_arguments
            if self.gcs_narration:
                self._wait_for_gcs_permissions(self._verify_gcs_frozen)
                backup_arguments = {**backup_arguments, 'freeze_canary': self.freeze_canary,
                                    'offhost_restore': self.offhost_restore}
            elif self.expected_gcs_media:
                self._media_cutover = self._media_cutover_values()
                source, retired, target = self._media_cutover
                backup_arguments = {**backup_arguments, 'values': source}
                if self.storage_only:
                    backup_arguments['media_detach_target'] = target
                    backup_arguments['offhost_restore'] = self.offhost_restore
                else:
                    backup_arguments['media_cutover'] = (retired, target)
            self.fence, self.evidence = self.stack.enter_context(fenced_backup_probe(**backup_arguments))
            if (self.storage_only or self.gcs_narration) and self.offhost_restore is not None:
                if (self.evidence.get('status') != 'FENCED_BACKUP_OFFHOST_RESTORE_VERIFIED'
                        or self.evidence.get('media_restore_verified') is not True
                        or self.evidence.get('restore_authorized') is not False):
                    raise PilotAdapterError('Off-host restored backup is unverified')
                self._restore_verified = True
                return True
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
                    checkpoint = self.evidence['journal_checkpoint']
                    if self.backup_arguments['verify_journal']() != checkpoint:
                        raise PilotAdapterError('Privacy journal differs from the verified backup')
                    replay = prepare_isolated_replay(witness_factory=self.witness_factory,
                                                     require_exact_backup=True,
                                                     live_journal_binding=(checkpoint['event_count'],
                                                                           checkpoint['journal_sha256']),
                                                     **self.quarantine_arguments)
                    if (replay.get('status') != 'RESTORED_OUTBOX_MATCHES_FENCED_LIVE_HISTORY'
                            or replay.get('target_verified_at_preflight') is not True
                            or replay.get('backup_event_count') != checkpoint['event_count']
                            or replay.get('later_event_count') != 0
                            or replay.get('privacy_replay_applied') is not False
                            or replay.get('restore_authorized') is not False):
                        raise PilotAdapterError('Quarantined replay preflight is invalid')
                    self.fence.verify()
                    if self.backup_arguments['verify_journal']() != checkpoint:
                        raise PilotAdapterError('Privacy journal changed during restore verification')
                    self._restore_verified = True
            elif self.witness_factory is not None:
                raise PilotAdapterError('A quarantined target is required for witness verification')
            if not self._restore_verified:
                # DB-only restore is insufficient. Never promote it.
                self._discard_quarantine()
                self.stack.close()
                self.fence = None
                self.evidence = None
                self._media_cutover = None
                return False
            return True
        except BaseException:
            try:
                self._discard_quarantine()
            finally:
                self.stack.close()
                self.fence = None
                self.evidence = None
                self._media_cutover = None
                self._restore_verified = False
            raise

    def migrate(self):
        self._require_preflight()
        if self.fence is None or self.evidence is None:
            raise PilotAdapterError('Verified backup fence is missing')
        if self.gcs_narration:
            self._verify_retired_neon()
            self._verify_gcs_frozen(self.backup_arguments['values'])
        elif self.expected_gcs_media:
            if self._media_cutover is None:
                raise PilotAdapterError('Verified media cutover configuration is missing')
            if self.storage_only:
                source, _, target = self._media_cutover
                verify_empty_media_detach(self.fence, source, target, expected_revision=SOURCE_REVISION)
            else:
                verify_staged_media_cutover(self.fence, *self._media_cutover)
        if not self._restore_verified:
            raise PilotAdapterError('Verified media restore and privacy history are missing')
        self.fence.verify()
        if self.backup_arguments['verify_journal']() != self.evidence['journal_checkpoint']:
            raise PilotAdapterError('Privacy journal changed before migration')
        if self.storage_only:
            self.fence.verify_revision(SOURCE_REVISION)
        else:
            def assert_backup_restored():
                if self.gcs_narration:
                    self._verify_gcs_frozen(self.backup_arguments['values'])
                return self._restore_verified is True

            self.fence.migrate(assert_backup_restored=assert_backup_restored)
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
        if self.expected_gcs_media:
            self._verify_stopped_proxy()
            self._verify_candidate_ports()
        if self.gcs_narration:
            self._wait_for_gcs_permissions(verify_staged_target_writer)
        for slot in ('new_api', 'new_worker'):
            item = self.runtime.inspect(self.identities[slot])
            if item.get('running') is not False or item.get('restart_policy') != 'no':
                raise PilotAdapterError('Staged container state changed')
        self._start_generation('new_')
        return True

    def verify_isolated(self):
        self._require_migrated()
        if not self.expected_gcs_media:
            return False
        self._verify_stopped_proxy()
        self._verify_candidate_ports()
        self._verify_live_network(isolated=True)
        before = self._candidate_generation()
        if self.expected_narration_only and not self.gcs_narration:
            self._bootstrap_narration()
        self._wait_api_and_worker()
        self._verify_worker_queue(self.identities['new_worker'])
        self._verify_stopped_proxy()
        self._verify_live_network(isolated=True)
        if self._candidate_generation() != before:
            raise PilotAdapterError('Candidate restarted during isolated verification')
        self._isolated_generation = (time.monotonic(), before)
        self._isolated_verified = True
        return True

    def _candidate_generation(self):
        generation = []
        for slot in ('new_api', 'new_worker'):
            item = self._full_inspect(self.identities[slot])
            state = item.get('State', {})
            started = state.get('StartedAt')
            restarts = item.get('RestartCount')
            if (item.get('Id') != self.identities[slot] or item.get('Image') != self.image_ids[slot]
                    or state.get('Running') is not True or state.get('Restarting') is not False
                    or not isinstance(started, str) or started.startswith('0001-') or not started
                    or type(restarts) is not int or restarts < 0):
                raise PilotAdapterError('Candidate process generation cannot be verified')
            generation.append((item['Id'], started, restarts))
        return tuple(generation)

    def _verify_fresh_isolated_generation(self):
        if (self._isolated_generation is None
                or time.monotonic() - self._isolated_generation[0] > 180
                or self._candidate_generation() != self._isolated_generation[1]):
            raise PilotAdapterError('Verified candidate generation changed or expired')

    def _verify_stopped_proxy(self):
        proxy = self._full_inspect(self.proxy_id)
        if (proxy.get('Name') != '/asb-pilot-nginx' or proxy.get('Image') != self.proxy_image_id
                or proxy.get('State', {}).get('Running') is not False
                or proxy.get('HostConfig', {}).get('RestartPolicy', {}).get('Name') != 'no'):
            raise PilotAdapterError('Proxy is not safely stopped')

    def _verify_candidate_ports(self):
        for role in ('api', 'worker'):
            host = self._full_inspect(self.identities['new_' + role]).get('HostConfig', {})
            if host.get('PortBindings') != {} or host.get('PublishAllPorts') is not False:
                raise PilotAdapterError('Candidate must not publish host ports')

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

    def _verify_api_and_worker(self, *, original=False):
        generation = 'old_' if original else 'new_'
        api = self.identities[generation + 'api']
        worker = self.identities[generation + 'worker']
        phase = 'container state'
        try:
            for identifier in (api, worker):
                if self.runtime.inspect(identifier).get('running') is not True:
                    raise ValueError('container stopped')
            # Probe locally inside the exact API container; no response body is
            # printed or exported to the caller.
            phase = 'API readiness'
            self._verify_api_ready(api)
            phase = 'worker identity'
            host = self._full_inspect(worker)['Config']['Hostname']
            if not isinstance(host, str) or not re.fullmatch('[A-Za-z0-9_.-]{1,253}', host):
                raise ValueError('worker hostname invalid')
            phase = 'worker ping'
            raw = self.runtime._run('exec', worker, 'celery', '-A', 'src.worker',
                                    'inspect', 'ping', '--timeout', '10', '--json')
            response = json.loads(raw)
            if response != {'celery@' + host: {'ok': 'pong'}}:
                raise ValueError('worker identity or ping mismatch')
        except Exception:
            raise PilotAdapterError('Cannot verify ' + phase) from None

    def _verify_api_ready(self, api, *, live=False):
        endpoint = 'live' if live else 'ready'
        self.runtime._run('exec', api, 'python', '-c',
                          f"import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health/{endpoint}',timeout=8); "
                          "assert r.status==200")

    def _wait_api_ready(self, api, *, live=False):
        deadline = time.monotonic() + 240
        while True:
            try:
                if live:
                    self._verify_api_ready(api, live=True)
                else:
                    self._verify_api_ready(api)
                return
            except safety.NarrationSafetyError:
                if self.runtime.inspect(api).get('running') is not True:
                    raise PilotAdapterError('Storage generation API exited before readiness') from None
                if time.monotonic() + 3 >= deadline:
                    raise PilotAdapterError('Storage generation API did not become ready') from None
                time.sleep(3)

    def _bootstrap_narration(self):
        try:
            bootstrap_isolated_narration(self.identities['new_api'], self.image_ids['new_api'],
                                         NARRATION_BOOTSTRAP_LEDGER)
        except Exception:
            raise PilotAdapterError('Isolated narration provider could not be verified') from None

    def _start_generation(self, prefix, *, worker_running=False):
        api = self.identities[prefix + 'api']
        self.runtime._run('start', api)
        if self.storage_only or self.gcs_narration:
            # On the pilot VM, starting both cold Python processes at once
            # delayed readiness. Keep admission closed and warm one at a time.
            if self.gcs_narration and prefix == 'new_':
                self._wait_api_ready(api, live=True)
                self._bootstrap_narration()
            self._wait_api_ready(api)
        if not worker_running:
            self.runtime._run('start', self.identities[prefix + 'worker'])

    def _wait_api_and_worker(self, *, original=False):
        for attempt in range(10):
            try:
                if original:
                    self._verify_api_and_worker(original=True)
                else:
                    self._verify_api_and_worker()
                return
            except PilotAdapterError:
                if attempt == 9:
                    raise
                time.sleep(2)

    def resume_original_storage_before_publication(self, *, worker_running=False):
        """Recover from a failed detach before any container or settings were renamed."""
        if not (self.storage_only or self.gcs_narration) or self.offhost_restore is None:
            raise PilotAdapterError('Original storage recovery is unavailable')
        self.stack.close()
        self.fence = None
        self._verify_stopped_proxy()
        self._verified_service_configs()
        if self.gcs_narration:
            self._verify_retired_neon()
            source = self.backup_arguments['values']
            self._wait_for_gcs_permissions(verify_staged_target_writer)
        else:
            if worker_running:
                raise PilotAdapterError('Storage detach recovery requires a stopped worker')
            self._verify_media_rollback_candidates()
            source, _, _ = self._media_cutover_values()
        with PostgresBackupFence(database_environment(source, self.backup_arguments['ca_file'])) as fence:
            fence.verify_revision(SOURCE_REVISION)
        for slot in ('old_api', 'old_worker'):
            identifier = self.identities[slot]
            item = self.runtime.inspect(identifier)
            expected = {'id': identifier, 'name': 'asb-pilot-' + slot.removeprefix('old_'),
                        'image_id': self.image_ids[slot],
                        'running': worker_running and slot == 'old_worker', 'restart_policy': 'no'}
            if item != expected:
                raise PilotAdapterError('Original container changed during storage detach')
        self._start_generation('old_', worker_running=worker_running)
        self._wait_api_and_worker(original=True)
        self.runtime._run('start', self.proxy_id)
        self._verify_proxy()
        self.runtime._run('exec', self.proxy_id, 'wget', '-q', '-O', '/dev/null',
                          'http://asb-pilot-api:8000/health/ready')
        for identifier in (self.identities['old_api'], self.identities['old_worker'], self.proxy_id):
            self.runtime.enable_restart(identifier)
            item = self.runtime.inspect(identifier)
            if item.get('running') is not True or item.get('restart_policy') != 'unless-stopped':
                raise PilotAdapterError('Original storage restart policy cannot be verified')
        return True

    def enable_new_restart(self, identities):
        self._require_migrated()
        self._ids(identities)
        if self.controls.enable_new_restart(identities) is not True:
            return False
        if self.expected_gcs_media:
            self._verify_proxy()
            self.runtime.enable_restart(self.proxy_id)
            if self.runtime.inspect(self.proxy_id).get('restart_policy') != 'unless-stopped':
                return False
        return True

    def publish(self):
        self._require_migrated()
        if not self._isolated_verified:
            raise PilotAdapterError('Ingress isolation is not verified')
        if self.expected_gcs_media:
            self._verify_stopped_proxy()
            self._verify_live_network(isolated=True)
            configs = self._verified_service_configs()
        else:
            self._verify_proxy()
        self._verify_fresh_isolated_generation()
        for slot, expected in (('old_api', 'asb-pilot-api'), ('old_worker', 'asb-pilot-worker'),
                               ('new_api', self._staged_name('api')), ('new_worker', self._staged_name('worker'))):
            item = self.runtime.inspect(self.identities[slot])
            if (item.get('id') != self.identities[slot] or item.get('name') != expected
                    or item.get('restart_policy') != 'no'
                    or item.get('running') is not slot.startswith('new_')):
                raise PilotAdapterError('Container state changed before publication')
        # The durable marker is held by the orchestrator throughout this
        # sequence. Any failure quarantines all recorded identities; the old
        # images are never restarted against the migrated schema.
        retired_names = self._retired_names()
        self._verify_retired_names_available()
        self._verify_fresh_isolated_generation()
        self._publication_started = True  # A timed-out daemon call may still rename a container.
        for slot in ('old_worker', 'old_api'):
            self.runtime._run('rename', self.identities[slot], retired_names[slot])
        self.runtime._run('rename', self.identities['new_worker'], 'asb-pilot-worker')
        self.runtime._run('rename', self.identities['new_api'], 'asb-pilot-api')
        if self.expected_gcs_media:
            self._install_service_configs(configs)
            self.runtime._run('start', self.proxy_id)
        self._verify_proxy()
        self.runtime._run('exec', self.proxy_id, 'nginx', '-t')
        self.runtime._run('exec', self.proxy_id, 'nginx', '-s', 'reload')
        return True

    def _verified_service_configs(self):
        generation = self.service_config_generation
        if generation is None:
            raise PilotAdapterError('Staged service configuration generation is required')
        names = {
            'pilot.env': f'pilot-{generation}-backup.stage.env',
            'backup-config.env': f'backup-config-{generation}.stage.env',
            'provider-refresh.env': f'provider-refresh-{generation}.stage.env',
        }
        api = self._full_inspect(self.identities['new_api'])
        worker = self._full_inspect(self.identities['new_worker'])
        before, after = self._environment(api), self._environment(worker)
        media = ('S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_BUCKET', 'S3_ENDPOINT', 'S3_REGION',
                 'S3_ADDRESSING_STYLE', 'S3_AUTO_CREATE_BUCKET')
        if any(before.get(key) != after.get(key) for key in (*media, 'PRIVACY_JOURNAL_WITNESS_BUCKET')):
            raise PilotAdapterError('Candidate service configuration differs')
        updates = {
            'pilot.env': {**{key: before[key] for key in media}, 'API_IMAGE': 'local-image@' + api['Image'],
                          'WORKER_IMAGE': 'local-image@' + worker['Image']},
            'backup-config.env': {'ASB_JOURNAL_WITNESS_BUCKET': before.get('PRIVACY_JOURNAL_WITNESS_BUCKET', '')},
            'provider-refresh.env': {'ASB_PROVIDER_REFRESH_API_IMAGE': api['Image']},
        }
        configs = {}
        for name, staged_name in names.items():
            target = PRIVATE_CONFIG_DIR / name
            current = private_file(target, max_bytes=1024 * 1024)
            staged = private_file(PRIVATE_CONFIG_DIR / staged_name, max_bytes=1024 * 1024)
            def parse(raw):
                return dict(dotenv_values(stream=io.StringIO(raw.decode('utf-8')), interpolate=False))
            if parse(staged) != {**parse(current), **updates[name]}:
                raise PilotAdapterError('Staged backup or provider configuration does not match')
            configs[target] = (current, staged)
        return configs

    @staticmethod
    def _install_service_configs(configs):
        # The caller holds the backup lock and an armed recovery marker.
        # An interrupted multi-file install remains quarantined on reboot.
        with ExitStack() as pending:
            for path, (current, _) in configs.items():
                if private_file(path, max_bytes=1024 * 1024) != current:
                    raise PilotAdapterError('Active service configuration changed before installation')
            def prepare(path, data):
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    pending.callback(temporary.unlink, missing_ok=True)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                return temporary

            prepared = {path: (prepare(path, current), prepare(path, staged))
                        for path, (current, staged) in configs.items()}
            fd = os.open(PRIVATE_CONFIG_DIR, os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                installed = []
                try:
                    for path, (_, staged) in prepared.items():
                        os.replace(staged, path)
                        installed.append(path)
                    os.fsync(fd)
                    for path, (_, data) in configs.items():
                        if private_file(path, max_bytes=1024 * 1024) != data:
                            raise PilotAdapterError('Installed service configuration does not match')
                except BaseException:
                    for path in reversed(installed):
                        os.replace(prepared[path][0], path)
                    os.fsync(fd)
                    raise
            finally:
                os.close(fd)

    def verify_published(self):
        self._require_migrated()
        if not self._isolated_verified:
            raise PilotAdapterError('Ingress isolation is not verified')
        self._verify_proxy()
        self._verify_fresh_isolated_generation()
        names = {**self._retired_names(), 'new_api': 'asb-pilot-api', 'new_worker': 'asb-pilot-worker'}
        for slot, expected in names.items():
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
        self._verify_fresh_isolated_generation()
        return True
