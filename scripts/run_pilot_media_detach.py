"""Run a pinned pilot media detach or the following GCS narration release."""
import argparse
import asyncio
from contextlib import closing, contextmanager
import io
import json
import os
from pathlib import Path
import re
import signal
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

from backup_service_guard import (BackupServiceGuard, DockerRuntime as BackupRuntime,
    PROVIDER_ROTATION_RECOVERY_MARKER, assert_no_narration_recovery)
from narration_deploy_safety import BACKUP_STATE, PRIVACY_RECOVERY_MARKER, DockerRuntime, _private_directory
from run_scheduled_backup import (assert_runtime_database_binding, assert_runtime_journal_binding,
    assert_runtime_media_binding, build_backup_journal, private_file, require_backup_disk_headroom)


PRIVATE = Path('/etc/ai-story-book/pilot/private')
STATE = Path('/var/lib/ai-story-book/narration-deploy')
BACKUPS = Path('/var/lib/ai-story-book/backups')
CA_FILE = PRIVATE / 'neon-ca.pem'
SLOTS = ('old_api', 'old_worker', 'new_api', 'new_worker')
S3_WITNESS = tuple('PRIVACY_JOURNAL_WITNESS_S3_' + key
                   for key in ('ENDPOINT', 'BUCKET', 'REGION', 'ACCESS_KEY', 'SECRET_KEY'))


class MediaDetachError(RuntimeError):
    pass


def _terminate(_signum, _frame):
    raise MediaDetachError('Storage detach was interrupted')


def _env(path):
    data = private_file(path, max_bytes=1024 * 1024)
    return {key: value or '' for key, value in dotenv_values(stream=io.StringIO(data.decode()),
                                                             interpolate=False).items()}


def _plan(path, *, narration=False):
    plan = json.loads(private_file(path, max_bytes=4096))
    if (not isinstance(plan, dict) or set(plan) != {
        'project', 'generation', 'containers', 'images', 'proxy_id', 'proxy_image_id',
        'proxy_config_sha256', 'monitor_manifest_sha256', 'restore_public_key',
    } or any(not isinstance(plan[name], dict) or set(plan[name]) != set(SLOTS) for name in ('containers', 'images'))
            or any((plan['images']['old_' + role] != plan['images']['new_' + role]) != narration
                   for role in ('api', 'worker'))
            or not isinstance(plan['restore_public_key'], str) or len(plan['restore_public_key']) > 256):
        raise MediaDetachError('Private storage detach plan is invalid')
    key = load_pem_public_key(plan['restore_public_key'].encode('ascii'))
    if not isinstance(key, Ed25519PublicKey):
        raise MediaDetachError('An Ed25519 restore verifier is required')
    return plan, key


def _retired_media(plan, prior_plan_path):
    prior, _ = _plan(prior_plan_path)
    if (prior['project'] != plan['project'] or prior['proxy_id'] != plan['proxy_id']
            or any(prior['containers']['new_' + role] != plan['containers']['old_' + role]
                   or prior['images']['new_' + role] != plan['images']['old_' + role]
                   for role in ('api', 'worker'))):
        raise MediaDetachError('Narration plan is not tied to the published storage detach')
    runtime = DockerRuntime()
    values = _env(prior_plan_path.parent / 'prior-configs' / 'pilot.env')
    for role in ('api', 'worker'):
        slot = 'old_' + role
        identifier = prior['containers'][slot]
        if runtime.inspect(identifier) != {'id': identifier, 'name': 'asb-pilot-' + role + '-before-media',
                'image_id': prior['images'][slot], 'running': False, 'restart_policy': 'no'}:
            raise MediaDetachError('Retired Neon container identity changed')
        entries = [item.split('=', 1) for item in json.loads(runtime._run('inspect', identifier))[0]['Config']['Env']]
        env = dict(entries)
        if len(env) != len(entries) or any(env.get(field) != values.get(field) for field in (
                'S3_ENDPOINT', 'S3_BUCKET', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'S3_REGION')):
            raise MediaDetachError('Retired Neon storage config changed')
    return values


def _configure_db(values):
    url = values.get('DATABASE_MIGRATION_URL') or values['DATABASE_URL']
    if url.startswith('postgres://'):
        url = 'postgresql://' + url.removeprefix('postgres://')
    os.environ.update(DATABASE_URL=make_url(url).difference_update_query(['sslrootcert']).render_as_string(
        hide_password=False), DATABASE_SSL_MODE=values['DATABASE_SSL_MODE'],
        DATABASE_SSL_ROOT_CERT=str(CA_FILE), TESTING='false')


@contextmanager
def _adapter(plan, public_key, mailbox=None, *, retired_neon=None, freeze_canary=None):
    from manage_privacy_purge_monitor import checked_file

    checked_file(CA_FILE)
    require_backup_disk_headroom(BACKUPS)
    values = _env(PRIVATE / 'pilot.env')
    config = _env(PRIVATE / 'backup-config.env')
    project = plan['project']
    primary = config['ASB_JOURNAL_BUCKET']
    backup = config['ASB_BACKUP_BUCKET']
    active_witness = config.get('ASB_JOURNAL_WITNESS_BUCKET', '')
    # The old images may still write just the primary. A read-only compare to
    # the independent replica is mandatory for the detach snapshot regardless.
    replica = 'asb-journal-witness-' + project
    if (backup != 'asb-backups-' + project or len({primary, replica, backup}) != 3
            or active_witness not in ('', replica) or any(values.get(name) for name in S3_WITNESS)):
        raise MediaDetachError('Backup or privacy journal settings differ from the reviewed pilot')
    key = private_file(PRIVATE / 'privacy-journal.key', max_bytes=32)
    if len(key) != 32:
        raise MediaDetachError('Privacy journal key is unavailable')
    _configure_db(values)
    from narration_detach_attestation import request_mailbox_attestation
    from narration_pilot_adapter import NarrationPilotAdapter
    from publish_backup_gcs import GCSBackupStore
    from src.core.database import AsyncSessionLocal, configure_for_worker
    from src.services.privacy_journal_gcs import application_default_token
    from src.services.privacy_journal_verify import verify_current_outbox

    configure_for_worker()
    writer_runtime = BackupRuntime()
    assert_runtime_database_binding(writer_runtime, values, CA_FILE)
    assert_runtime_media_binding(writer_runtime, values)
    assert_runtime_journal_binding(writer_runtime, primary, active_witness)
    for role in ('api', 'worker'):
        values[role.upper() + '_IMAGE'] = 'local-image@' + plan['images']['old_' + role]
    journal, journal_store = build_backup_journal(primary, replica, dict.fromkeys(S3_WITNESS, ''), values, key)

    def verify_journal():
        async def verify():
            scan = await asyncio.to_thread(journal.scan)
            async with AsyncSessionLocal() as session:
                return await verify_current_outbox(session, scan, legacy_source=True)
        return asyncio.run(verify())

    def attest(challenge):
        return request_mailbox_attestation(challenge, mailbox)

    with closing(journal_store), closing(GCSBackupStore(backup, application_default_token)) as store:
        with NarrationPilotAdapter(runtime=DockerRuntime(), identities=plan['containers'], image_ids=plan['images'],
            backup_arguments={'values': values, 'ca_file': CA_FILE, 'output_dir': BACKUPS,
                              'store': store, 'verify_journal': verify_journal},
            expected_google_project=project, expected_daily_limit=24 if retired_neon else 1,
            expected_monthly_limit=120 if retired_neon else 1,
            proxy_id=plan['proxy_id'], proxy_image_id=plan['proxy_image_id'],
            expected_proxy_config_sha256=plan['proxy_config_sha256'],
            expected_monitor_manifest_sha256=plan['monitor_manifest_sha256'],
            expected_gcs_media=True, storage_only=retired_neon is None, service_config_generation=plan['generation'],
            expected_narration_only=retired_neon is not None, offhost_restore=(public_key, attest),
            retired_neon=retired_neon, freeze_canary=freeze_canary) as adapter:
            yield adapter


def _recover_original(plan, public_key, *, retired_neon=None, freeze_canary=None):
    from narration_deploy_safety import _read_recovery_marker, quarantine

    marker = STATE / 'narration-recovery.json'
    fd = BackupServiceGuard(BACKUP_STATE, None)._locked()
    try:
        if any(os.path.lexists(path) for path in (BACKUP_STATE / 'restart-required.json',
                PRIVACY_RECOVERY_MARKER, PROVIDER_ROTATION_RECOVERY_MARKER)):
            raise MediaDetachError('A different operation has pending recovery')
        expected = {'version': 2, 'containers': plan['containers'],
                    'proxy': {'id': plan['proxy_id'], 'image_id': plan['proxy_image_id']}}
        if _read_recovery_marker(marker) != expected:
            raise MediaDetachError('The recovery marker does not identify the unpublished detach')
        narration = retired_neon is not None
        context = (_adapter(plan, public_key, retired_neon=retired_neon, freeze_canary=freeze_canary)
                   if narration else _adapter(plan, public_key))
        with context as adapter:
            adapter._verify_stopped_proxy()
            worker_running = False
            for slot, identifier in plan['containers'].items():
                phase, role = slot.split('_')
                name = 'asb-pilot-' + role if phase == 'old' else adapter._staged_name(role)
                item = adapter.runtime.inspect(identifier)
                if (item['id'] != identifier or item['name'] != name or item['image_id'] != plan['images'][slot]
                        or item['restart_policy'] != 'no'
                        or (item['running'] and (narration and slot != 'old_worker' or not narration and phase == 'old'))):
                    raise MediaDetachError('Recovery requires the unchanged, stopped original generation')
                if slot == 'old_worker':
                    worker_running = item['running']
            if not narration:
                quarantine(STATE, adapter.runtime)
            try:
                result = (adapter.resume_original_storage_before_publication(worker_running=worker_running)
                          if narration else adapter.resume_original_storage_before_publication())
                if result is not True:
                    raise MediaDetachError('Original storage recovery is unverified')
            except BaseException:
                if not narration:
                    quarantine(STATE, adapter.runtime)
                else:
                    # Never terminate a still-draining worker on a failed
                    # recovery attempt. Stop the exact ingress if it opened.
                    proxy = adapter.runtime.inspect(plan['proxy_id'])
                    if (proxy['name'] == 'asb-pilot-nginx' and proxy['image_id'] == plan['proxy_image_id']
                            and proxy['running']):
                        adapter.runtime.disable_restart(plan['proxy_id'])
                        adapter.runtime.stop(plan['proxy_id'])
                raise
        marker.unlink()
        directory = os.open(STATE, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--post-detach', type=Path, help='Pinned successful detach plan before a narration release')
    parser.add_argument('--freeze-canary', help='Owned media object used to verify the GCS write freeze')
    parser.add_argument('--mailbox', help='Unique 32-character operation ID shared by the VM and the restore host')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true', help='Execute the pinned media or narration plan')
    mode.add_argument('--recover-original', action='store_true', help='Resume only the unchanged, stopped original generation')
    mode.add_argument('--read', choices=('challenge', 'result'))
    mode.add_argument('--sign', action='store_true', help='Submit the verified restore signature on stdin')
    args = parser.parse_args()
    if (args.post_detach is None) != (args.freeze_canary is None):
        parser.error('Post-detach plans require exactly one freeze canary')
    if any((args.execute, args.read, args.sign)) != (args.mailbox is not None) or (
            args.mailbox is not None and re.fullmatch('[0-9a-f]{32}', args.mailbox) is None):
        parser.error('Supply a unique operation ID with execution, reading or signature submission')
    if os.geteuid() != 0 or os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise SystemExit('The pilot root account and local Docker are required')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'apps/api'))
    os.environ['PATH'] = '/opt/ai-story-book/postgres16/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    mailbox = None
    owns_mailbox = False
    try:
        from manage_privacy_purge_monitor import require_pilot_vm
        require_pilot_vm()
        plan, public_key = _plan(args.plan, narration=args.post_detach is not None)
        if args.recover_original:
            signal.signal(signal.SIGTERM, _terminate)
            retired_neon = _retired_media(plan, args.post_detach) if args.post_detach else None
            _recover_original(plan, public_key, retired_neon=retired_neon, freeze_canary=args.freeze_canary)
            print(json.dumps({'status': 'ORIGINAL_STORAGE_RECOVERED', 'restore_authorized': False}))
            return 0
        if args.mailbox:
            from narration_detach_attestation import read_mailbox_record, verify_restore_attestation, write_mailbox_record
            mailbox = _private_directory(STATE) / ('detach-' + args.mailbox)
        if args.read:
            try:
                content = read_mailbox_record(mailbox, args.read)
            except FileNotFoundError:
                return 3  # The recorded operation has not reached this point.
            sys.stdout.buffer.write(content)
            return 0
        if args.sign:
            challenge = json.loads(read_mailbox_record(mailbox, 'challenge'))
            raw = sys.stdin.buffer.read(90)
            if re.fullmatch(rb'[A-Za-z0-9+/]{86}==\n', raw) is None:
                raise MediaDetachError('Restore signature format is invalid')
            verify_restore_attestation(challenge, raw[:-1].decode('ascii'), public_key=public_key)
            try:
                write_mailbox_record(mailbox, 'signature', raw)
            except FileExistsError:
                if read_mailbox_record(mailbox, 'signature') != raw:
                    raise
            return 0
        if args.execute:
            from narration_release_orchestrator import release
            mailbox.mkdir(mode=0o700)
            owns_mailbox = True
            write_mailbox_record(mailbox, 'started', b'STORAGE_DETACH_STARTED\n')
            signal.signal(signal.SIGTERM, _terminate)
            retired_neon = _retired_media(plan, args.post_detach) if args.post_detach else None
            with _adapter(plan, public_key, mailbox, retired_neon=retired_neon,
                          freeze_canary=args.freeze_canary) as adapter:
                result = release(state_dir=STATE, backup_state_dir=BACKUP_STATE,
                    identities=plan['containers'], image_ids=plan['images'], runtime=adapter.runtime,
                    operations=adapter)
            write_mailbox_record(mailbox, 'result', (json.dumps(result) + '\n').encode('ascii'))
            return 0
        fd = BackupServiceGuard(BACKUP_STATE, None)._locked()
        try:
            assert_no_narration_recovery()
            if any(os.path.lexists(path) for path in (STATE / 'narration-recovery.json',
                    BACKUP_STATE / 'restart-required.json', PRIVACY_RECOVERY_MARKER)):
                raise MediaDetachError('A recovery is pending')
            retired_neon = _retired_media(plan, args.post_detach) if args.post_detach else None
            with _adapter(plan, public_key, retired_neon=retired_neon, freeze_canary=args.freeze_canary) as adapter:
                if adapter.preflight(plan['containers']) is not True:
                    raise MediaDetachError('Storage detach preflight failed')
                checkpoint = adapter.backup_arguments['verify_journal']()
                print(json.dumps({'status': 'MEDIA_DETACH_PREFLIGHT_VERIFIED',
                                  'journal_event_count': checkpoint['event_count'], 'published': False}))
        finally:
            os.close(fd)
        return 0
    except Exception as exc:
        import traceback
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        # Every failure is reported by type and code location only.
        status = ('MEDIA_DETACH_EXECUTION_FAILED' if args.execute else 'MEDIA_DETACH_RECOVERY_FAILED'
                  if args.recover_original else 'MEDIA_DETACH_PREFLIGHT_FAILED')
        failure = json.dumps({'status': status, 'type': type(exc).__name__,
                              'location': f'{Path(frame.filename).name}:{frame.lineno}'}) + '\n'
        if owns_mailbox and not (mailbox / 'result').exists():
            write_mailbox_record(mailbox, 'result', failure.encode('ascii'))
        print(failure, end='')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
