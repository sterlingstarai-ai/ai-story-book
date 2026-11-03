"""Build a local, explicitly pinned narration experiment; never deploy it.

The manifest freezes a reviewed set of checkout files and two local base image
IDs. No environment files, credentials, provider calls, or network access are
used. This is not a release or restore authorization.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'infra/gcp-pilot/narration-candidate-manifest.json'
CONSENT_MANIFEST = ROOT / 'infra/gcp-pilot/narration-consent-candidate-manifest.json'
DELETION_MANIFEST = ROOT / 'infra/gcp-pilot/narration-consent-deletion-candidate-manifest.json'
PRIVACY_MANIFEST = ROOT / 'infra/gcp-pilot/narration-privacy-candidate-manifest.json'
MONITOR_MANIFEST = ROOT / 'infra/gcp-pilot/narration-privacy-monitor-candidate-manifest.json'
RECEIPT_MANIFEST = ROOT / 'infra/gcp-pilot/narration-receipt-candidate-v2-manifest.json'
FINAL_MANIFEST = ROOT / 'infra/gcp-pilot/narration-receipt-candidate-v17-manifest.json'
CURRENT_MANIFEST = ROOT / 'infra/gcp-pilot/narration-receipt-candidate-v18-manifest.json'
BUDGET_MANIFEST = ROOT / 'infra/gcp-pilot/narration-receipt-candidate-v22-manifest.json'
CONFIG_PATH = 'src/core/config.py'
ALLOWED_FILES = frozenset({
    'alembic/env.py',
    'alembic/versions/9c1e3a7f620d_narration_variants.py',
    'alembic/versions/7e28d9a6b451_narration_styles.py',
    'src/core/audio_feature.py',
    'src/models/db.py',
    'src/routers/books.py',
    'src/routers/config.py',
    'src/services/audio_assets.py',
    'src/services/illustration_quality_edits.py',
    'src/services/narration_style.py',
    'src/services/orchestrator.py',
    'src/services/provider_runtime.py',
    'src/services/realtime_tts.py',
    'src/services/tts.py',
})
CONSENT_FILES = ALLOWED_FILES | {'src/routers/consent.py'}
DELETION_FILES = CONSENT_FILES | {'src/services/storage.py', 'src/services/purge_queue.py'}
PRIVACY_FILES = DELETION_FILES | {
    CONFIG_PATH,
    'src/services/privacy_checkpoint_gcs.py',
    'src/services/privacy_checkpoint_head.py',
    'src/services/privacy_checkpoint_keys.py',
    'src/services/privacy_journal.py',
    'src/services/privacy_journal_backfill.py',
    'src/services/privacy_journal_backfill_guard.py',
    'src/services/privacy_journal_checkpoint.py',
    'src/services/privacy_journal_mirror.py',
    'src/services/privacy_journal_runtime.py',
    'src/services/privacy_journal_s3.py',
    'src/services/privacy_journal_verify.py',
    'src/services/privacy_restore_source_guard.py',
    'src/services/privacy_witness_receipt.py',
    'src/services/privacy_witness_watch.py',
}
MONITOR_FILES = PRIVACY_FILES | {'src/services/privacy_purge_health.py'}
RECEIPT_FILES = MONITOR_FILES | {
    'alembic/versions/8a34e19c6b72_book_deletion_receipts.py',
    'alembic/versions/b3f149ac52d7_voice_history.py',
    'alembic/versions/d52b81c9a734_gemini_tts_budget.py',
    'src/core/gemini_tts_budget.py',
    'src/models/dto.py',
    'src/models/gemini_tts_budget.py',
    'src/routers/account.py',
    'src/routers/characters.py',
    'src/routers/library.py',
    'src/routers/profiles.py',
    'src/routers/users.py',
    'src/routers/voice_profiles.py',
    'src/services/account_recovery.py',
    'src/services/account_scope.py',
    'src/services/photo_lifecycle.py',
    'src/services/privacy_journal_outbox.py',
    'src/services/privacy_journal_transaction.py',
}
FINAL_PROMPTS = frozenset({
    'src/prompts/generate_image_prompts.system.jinja2',
    'src/prompts/generate_story.system.jinja2',
})
FINAL_FILES = RECEIPT_FILES | FINAL_PROMPTS | {
    'alembic/versions/4c2d8f71b906_privacy_retry_fairness.py',
    'src/services/llm.py',
    'src/services/image_quality.py',
    'src/services/image_correction.py',
    'src/services/privacy_journal_gcs.py',
}
CURRENT_FILES = FINAL_FILES | {'src/core/cost_budget.py', 'src/routers/branch.py'}
BUDGET_FILES = CURRENT_FILES | {
    'alembic/versions/e7b93d2a601f_generation_budget.py',
    'src/models/generation_budget.py',
    'scripts/activate_generation_budget.py',
}
MONITOR_HOST_FILES = frozenset({
    'scripts/build_privacy_purge_monitor_bundle.py',
    'scripts/check_privacy_purge_queue.py',
    'scripts/manage_privacy_purge_monitor.py',
    'scripts/publish_privacy_purge_health.py',
    'infra/gcp-pilot/asb-privacy-purge-signal.timer',
    'infra/gcp-pilot/asb-privacy-purge-signal.service',
    'infra/gcp-pilot/asb-privacy-purge-alert-policy.template.json',
})
RECEIPT_HOST_FILES = MONITOR_HOST_FILES | {
    'apps/api/.env.example',
    'env.schema.json',
    'infra/.env.example',
    'infra/docker-compose.yml',
    'infra/docker-compose.prod.yml',
    'infra/docker-compose.external.yml',
    'infra/docker-compose.account-scope.yml',
    'infra/render.yaml.template',
    'packages/shared/schema/openapi.json',
    'scripts/account_scope_key.py',
    'scripts/check_restore_sandbox.py',
    'scripts/final_external_preflight.py',
    'scripts/independent_journal_evidence.py',
    'scripts/live_fenced_replay_preflight.py',
    'scripts/live_privacy_boundary.py',
    'scripts/narration_container_controls.py',
    'scripts/narration_deploy_safety.py',
    'scripts/narration_fenced_backup_probe.py',
    'scripts/narration_marker_exec_condition.py',
    'scripts/narration_pilot_adapter.py',
    'scripts/narration_release_backup.py',
    'scripts/narration_release_migration.py',
    'scripts/narration_release_orchestrator.py',
    'scripts/narration_transaction_fence.py',
    'scripts/publish_backup_gcs.py',
    'scripts/quarantined_backup_ingest.py',
    'scripts/quarantined_backup_receiver.py',
    'scripts/quarantined_db_fingerprint.py',
    'scripts/quarantined_outbox_binding.py',
    'scripts/quarantined_replay_adapter.py',
    'scripts/quarantined_replay_preflight.py',
    'scripts/quarantined_restore_adapter.py',
    'scripts/quarantined_restore_runtime.py',
    'scripts/replay_privacy_journal.py',
    'scripts/run_offline_restore_rehearsal.py',
    'scripts/update_privacy_purge_monitor.py',
    'scripts/verify_backup_set.py',
    'infra/Dockerfile.restore-sandbox-test',
    'infra/gcp-pilot/asb-narration-quarantine.service',
    'infra/gcp-pilot/asb-backup-recover.service.d/narration-guard.conf',
    'infra/gcp-pilot/asb-privacy-deploy-recover.service.d/narration-guard.conf',
}
FINAL_HOST_FILES = RECEIPT_HOST_FILES | {
    'scripts/automatic_backup.py',
    'scripts/run_scheduled_backup.py',
    'scripts/backup_external.py',
    'scripts/backup_service_guard.py',
    'scripts/postgres_backup_fence.py',
    'scripts/provider_rotation_quarantine.py',
    'infra/gcp-pilot/asb-backup.service',
    'infra/gcp-pilot/asb-backup.timer',
    'infra/gcp-pilot/asb-provider-rotation-quarantine.service',
}
BUDGET_HOST_FILES = FINAL_HOST_FILES | {
    'docs/DEPLOYMENT.md',
    'infra/.env.external.example',
    'infra/docker-compose.provider-key-files.yml',
    'scripts/linux_parent_death_exec.py',
}
ANCHOR = b'    google_tts_api_key: Optional[str] = None\n'
ADDITION = (b'    # Gemini TTS billing project; credentials come from workload ADC.\n'
            b'    google_gemini_tts_project: Optional[str] = None\n')


def docker(*args, input_bytes=None):
    try:
        return subprocess.run(['docker', *args], input=input_bytes, capture_output=True,
                              check=True, timeout=600).stdout
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('Docker operation failed; inspect the local environment') from None


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ensure_local_daemon():
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise RuntimeError('Explicit Docker host or context is not permitted')
    context = json.loads(docker('context', 'inspect'))[0]
    if not context['Endpoints']['docker']['Host'].startswith('unix://'):
        raise RuntimeError('A local Unix Docker daemon is required')


def inspect_base(image):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise RuntimeError('Base image must be an exact local digest')
    data = json.loads(docker('image', 'inspect', image))[0]
    if data['Id'] != image or data.get('Os') != 'linux' or data.get('Architecture') != 'amd64':
        raise RuntimeError('Base image identity or architecture does not match')
    # Removing the temporary build tag from an originally untagged image can
    # delete the only reference to that image. Never make that choice for the
    # operator; preserve a stable, owned tag before invoking this builder.
    if not data.get('RepoTags'):
        raise RuntimeError('Base image needs a pre-existing stable tag for preservation')
    if data['Config'].get('User') != 'appuser':
        raise RuntimeError('Unexpected base image user')
    # Inspect locally, but never display base environment values.
    for entry in data['Config'].get('Env') or []:
        key, _, value = entry.partition('=')
        if value and re.search(r'(SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|ACCESS_KEY|'
                               r'CREDENTIAL|DATABASE_URL|REDIS_URL)', key, re.I):
            raise RuntimeError('Base image contains a credential-like environment value')
    # The current filesystem is checked, not historical image layers; this
    # does not certify that a base image has never contained a secret.
    probe = "from pathlib import Path; import sys; sys.exit(any(p.is_file() and p.name != '.env.example' for p in Path('/app').glob('.env*')))"
    docker('run', '--rm', '--network=none', '--read-only', '--entrypoint', 'python', image, '-c', probe)


def read_from_image(image, path):
    return docker('run', '--rm', '--network=none', '--read-only', '--entrypoint',
                  'cat', image, '/app/' + path)


def source_hashes(image):
    program = '''import hashlib,json,pathlib
root=pathlib.Path('/app')
paths=[p for tree in ('src','alembic') for p in (root/tree).rglob('*')
       if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in paths},sort_keys=True))'''
    return json.loads(docker('run', '--rm', '--network=none', '--read-only',
                             '--entrypoint', 'python', image, '-c', program))


def checkout_hashes():
    root = ROOT / 'apps/api'
    hashes = {}
    for tree in ('src', 'alembic'):
        for path in (root / tree).rglob('*'):
            if path.is_symlink():
                raise RuntimeError('Source tree contains a symlink')
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                hashes[str(path.relative_to(root))] = sha(path.read_bytes())
    return hashes


def snapshot(manifest, base):
    files = {}
    if set(manifest['files']) not in (ALLOWED_FILES, CONSENT_FILES, DELETION_FILES, PRIVACY_FILES, MONITOR_FILES, RECEIPT_FILES, FINAL_FILES, CURRENT_FILES, BUDGET_FILES):
        raise RuntimeError('Manifest does not match the reviewed source allowlist')
    if set(manifest['files']) in (MONITOR_FILES, RECEIPT_FILES, FINAL_FILES, CURRENT_FILES, BUDGET_FILES):
        host_files = manifest.get('host_artifacts')
        expected_host_files = (BUDGET_HOST_FILES if set(manifest['files']) == BUDGET_FILES else
                               FINAL_HOST_FILES if set(manifest['files']) in (FINAL_FILES, CURRENT_FILES) else
                               RECEIPT_HOST_FILES if set(manifest['files']) == RECEIPT_FILES else MONITOR_HOST_FILES)
        if not isinstance(host_files, dict) or set(host_files) != expected_host_files:
            raise RuntimeError('Monitor host artifact manifest is incomplete')
        for name, digest in host_files.items():
            path = ROOT / name
            if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != digest:
                raise RuntimeError('Reviewed monitor host artifact changed: ' + name)
    for name, expected in manifest['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or (path.suffix != '.py' and name not in FINAL_PROMPTS):
            raise RuntimeError('Invalid source allowlist entry')
        full = ROOT / 'apps/api' / path
        if (full.is_symlink() or not full.is_file()
                or not full.resolve().is_relative_to((ROOT / 'apps/api').resolve())):
            raise RuntimeError('Allowlisted source is not a regular file')
        content = full.read_bytes()
        if sha(content) != expected:
            raise RuntimeError('Reviewed source changed: ' + name)
        files[name] = content
    config = read_from_image(base, CONFIG_PATH)
    if sha(config) != manifest['base_config_sha256'] or config.count(ANCHOR) != 1:
        raise RuntimeError('Base configuration differs from the reviewed version')
    if CONFIG_PATH not in files:
        files[CONFIG_PATH] = config.replace(ANCHOR, ANCHOR + ADDITION)
    return files


def build(base, tag, files):
    # BuildKit interprets `FROM sha256:...` as a registry name rather than a
    # local image ID. Use an owned random local tag and verify its identity.
    base_tag = 'asb-narration-base:local-' + uuid.uuid4().hex
    docker('tag', base, base_tag)
    try:
        tagged = json.loads(docker('image', 'inspect', base_tag))[0]['Id']
        if tagged != base:
            raise RuntimeError('Local base tag identity changed')
        with tempfile.TemporaryDirectory(prefix='asb-narration-overlay-') as directory:
            stage = Path(directory)
            lines = ['FROM ' + base_tag, 'USER root']
            for name, content in sorted(files.items()):
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                lines.append('COPY --chown=appuser:appuser ' + json.dumps([name, '/app/' + name]))
            lines.append('USER appuser')
            (stage / 'Dockerfile').write_text('\n'.join(lines) + '\n')
            iid = stage / 'image-id'
            docker('build', '--network=none', '--pull=false', '--platform=linux/amd64',
                   '--iidfile', str(iid), '--tag', tag, str(stage))
            image = iid.read_text().strip()
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
                raise RuntimeError('Invalid resulting image ID')
            for name, content in files.items():
                if read_from_image(image, name) != content:
                    raise RuntimeError('Candidate file differs from frozen source: ' + name)
            before, after = source_hashes(base), source_hashes(image)
            changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
            # The source inventory deliberately covers only src/ and alembic/.
            # The separately allowlisted activation script is byte-verified above.
            expected_changes = {path for path, content in files.items()
                                if path.startswith(('src/', 'alembic/')) and before.get(path) != sha(content)}
            if changed != expected_changes:
                raise RuntimeError('Candidate contains unexpected source changes')
            return image
    finally:
        docker('image', 'rm', base_tag)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path,
                        help='new private JSON report path; never overwrites')
    parser.add_argument('--local-rehearsal-image',
                        help='optional exact local image ID for rehearsal; never claims production identity')
    parser.add_argument('--include-consent', action='store_true',
                        help='use the separately reviewed consent-inclusive manifest')
    parser.add_argument('--include-deletion-guards', action='store_true',
                        help='also include reviewed deletion response and queue safeguards')
    parser.add_argument('--include-privacy', action='store_true',
                        help='also include the separately reviewed journal and witness code bundle')
    parser.add_argument('--include-purge-monitor', action='store_true',
                        help='include the reviewed queue monitor source and pin its host artifacts')
    parser.add_argument('--include-receipts', action='store_true',
                        help='include reviewed deletion receipt model, schema and operations')
    parser.add_argument('--include-current-source', action='store_true',
                        help='use the current reviewed branch and cost-budget candidate')
    parser.add_argument('--include-postgres-budget', action='store_true',
                        help='include the reviewed PostgreSQL budget model and migration')
    args = parser.parse_args()
    ensure_local_daemon()
    if args.include_deletion_guards and not args.include_consent:
        raise RuntimeError('Deletion safeguards require the reviewed consent-inclusive candidate')
    if args.include_privacy and not args.include_deletion_guards:
        raise RuntimeError('Privacy bundle requires the reviewed deletion safeguards')
    if args.include_purge_monitor and not args.include_privacy:
        raise RuntimeError('Purge monitor candidate requires the reviewed privacy bundle')
    if args.include_receipts and not args.include_purge_monitor:
        raise RuntimeError('Receipt candidate requires the reviewed purge monitor bundle')
    if args.include_current_source and not args.include_receipts:
        raise RuntimeError('Current source candidate requires the reviewed receipt bundle')
    if args.include_postgres_budget and not args.include_current_source:
        raise RuntimeError('PostgreSQL budget candidate requires the reviewed current bundle')
    manifest_path = (BUDGET_MANIFEST if args.include_postgres_budget else
                     CURRENT_MANIFEST if args.include_current_source else
                     FINAL_MANIFEST if args.include_receipts else
                     MONITOR_MANIFEST if args.include_purge_monitor else
                     PRIVACY_MANIFEST if args.include_privacy else
                     DELETION_MANIFEST if args.include_deletion_guards else
                     CONSENT_MANIFEST if args.include_consent else MANIFEST)
    manifest = json.loads(manifest_path.read_text())
    required_files = (BUDGET_FILES if args.include_postgres_budget else
                      CURRENT_FILES if args.include_current_source else
                      FINAL_FILES if args.include_receipts else
                      MONITOR_FILES if args.include_purge_monitor else
                      PRIVACY_FILES if args.include_privacy else
                      DELETION_FILES if args.include_deletion_guards else
                      CONSENT_FILES if args.include_consent else ALLOWED_FILES)
    if set(manifest['files']) != required_files:
        raise RuntimeError('Selected manifest does not match its reviewed allowlist')
    if set(manifest['bases']) != {'api', 'worker'}:
        raise RuntimeError('Invalid candidate base set')
    result = {'status': 'LOCAL_CANDIDATES_BUILT', 'deployment_authorized': False,
              'provider_called': False, 'images': {}, 'files': {},
              'base_matches_observed_production_image_id': args.local_rehearsal_image is None}
    files = None
    owned_tags = []
    try:
        checkout_before = checkout_hashes()
        for role, original_base in manifest['bases'].items():
            base = args.local_rehearsal_image or original_base
            inspect_base(base)
            if args.local_rehearsal_image:
                actual = source_hashes(base)
                digest = sha(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode())
                if digest != manifest['running_source_manifest_sha256']:
                    raise RuntimeError('Rehearsal image source does not match the running container snapshot')
            current = snapshot(manifest, base)
            if files is not None and current != files:
                raise RuntimeError('Base configuration differs between API and worker')
            files = current
            tag = f'asb-narration-candidate-{role}:local-{uuid.uuid4().hex[:12]}'
            owned_tags.append(tag)
            image = build(base, tag, files)
            result['images'][role] = {'base': base, 'observed_production_base': original_base,
                                      'candidate': image, 'tag': tag}
        # Do not emit a successful report if collaborators changed a reviewed
        # source or host artifact while the images were being built.
        for name, digest in manifest['files'].items():
            if sha((ROOT / 'apps/api' / name).read_bytes()) != digest:
                raise RuntimeError('Reviewed source changed during build: ' + name)
        for name, digest in manifest.get('host_artifacts', {}).items():
            if sha((ROOT / name).read_bytes()) != digest:
                raise RuntimeError('Reviewed monitor host artifact changed during build: ' + name)
        checkout_after = checkout_hashes()
        if checkout_before != checkout_after:
            raise RuntimeError('Checkout source changed during build; retry after concurrent edits')
        candidate_source = source_hashes(result['images']['api']['candidate'])
        result['checkout_differing_paths'] = sorted(
            path for path in set(checkout_after) | set(candidate_source)
            if checkout_after.get(path) != candidate_source.get(path))
        result['same_source_as_checkout'] = not result['checkout_differing_paths']
        result['files'] = {name: sha(content) for name, content in sorted(files.items())}
        if args.include_purge_monitor:
            result['host_artifacts'] = manifest['host_artifacts']
            result['host_artifacts_installed'] = False
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(args.report, flags, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write('\n')
    except BaseException:
        # Remove only tags uniquely created by this failed invocation. Never
        # prune the daemon or remove previously reviewed candidate images.
        cleanup_failed = False
        for tag in owned_tags:
            result_check = subprocess.run(['docker', 'image', 'inspect', tag], capture_output=True)
            if result_check.returncode == 0:
                try:
                    docker('image', 'rm', tag)
                except RuntimeError:
                    cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError('Owned failed-build image cleanup failed') from None
        raise
    print(json.dumps({'status': result['status'], 'report': str(args.report),
                      'deployment_authorized': False}))


if __name__ == '__main__':
    main()
