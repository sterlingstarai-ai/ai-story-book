"""Run a synthetic backup/deletion replay inside one offline tmpfs container.

No project .env, production data, remote Docker endpoint, or paid provider is
used. This experiment does not authorize opening a restored system.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASES = {'PYTHONDEPS': 'storybook-launch-api:c20d312', 'MINIODEPS': 'storybook-minio-test:2025-09-07',
         'POSTGRES': 'postgres:16'}
SCRIPTS = ('run_backup_restore_rehearsal.py', 'run_runtime_e2e.py', 'mock_illustration_review.py',
           'run_restore_replay_fixture.py', 'fixture_journal_store.py', 'replay_privacy_journal.py',
           'run_privacy_boundary_integration.py',
           'run_source_privacy_fixture.py', 'run_witness_fixture.py', 'run_purge_health_fixture.py',
           'quarantined_backup_receiver.py', 'quarantined_restore_runtime.py',
           'quarantined_db_fingerprint.py', 'quarantined_replay_preflight.py', 'quarantined_outbox_binding.py',
           'verify_backup_set.py', 'backup_external.py', 'final_external_preflight.py',
           'publish_backup_gcs.py', 'quarantined_backup_ingest.py', 'check_restore_sandbox.py',
           'narration_deploy_safety.py')


class OfflineRehearsalError(RuntimeError):
    pass


def command(args, *, input_bytes=None, timeout=30):
    try:
        result = subprocess.run(args, input=input_bytes, capture_output=True, timeout=timeout, check=True)
        return result.stdout.decode('utf-8')
    except subprocess.CalledProcessError as exc:
        if len(args) >= 3 and args[:3] == ['docker', 'exec', '-i']:
            # This process runs only in the inspected network-none synthetic
            # sandbox with fixed test credentials and no production data.
            detail = (exc.stderr or b'').decode('utf-8', errors='replace')[-1500:]
            raise OfflineRehearsalError('Synthetic fixture failed: ' + detail) from None
        raise OfflineRehearsalError('A synthetic container operation failed') from None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise OfflineRehearsalError('A synthetic container operation failed') from None


def local_daemon():
    override = os.environ.get('DOCKER_HOST', '')
    endpoint = json.loads(command(['docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}']))
    if (override and not override.startswith('unix://')) or not isinstance(endpoint, str) or not endpoint.startswith('unix://'):
        raise OfflineRehearsalError('A local Docker daemon is required')


def source_tree(source, destination):
    if source.is_symlink() or any(path.is_symlink() for path in source.rglob('*')):
        raise OfflineRehearsalError('Symlinks are not permitted in the build source')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env*', '*.pem', '*.key', '*.db'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    nonce = secrets.token_hex(16)
    image_tag = f'asb-offline-restore-{nonce}:synthetic'
    container_name = f'asb-offline-restore-{nonce}'
    base_tags = []
    container_id = None
    image_id = None
    run_attempted = False
    output_owned = False
    outcome = {'status': 'FAILED', 'synthetic_data_only': True, 'restore_authorized': False}
    try:
        local_daemon()
        if subprocess.run(['docker', 'image', 'inspect', image_tag], capture_output=True, timeout=20).returncode == 0:
            raise OfflineRehearsalError('Synthetic output image tag unexpectedly exists')
        output_owned = True
        base_images = {}
        for key, tag in BASES.items():
            image = json.loads(command(['docker', 'image', 'inspect', tag]))
            if (not isinstance(image, list) or len(image) != 1
                    or not re.fullmatch(r'sha256:[0-9a-f]{64}', image[0].get('Id', ''))):
                raise OfflineRehearsalError('A local test dependency is missing')
            base_images[key] = image[0]
        if len({(value.get('Os'), value.get('Architecture')) for value in base_images.values()}) != 1:
            raise OfflineRehearsalError('Synthetic image architectures do not match')
        with tempfile.TemporaryDirectory(prefix='asb-offline-build-') as temporary:
            stage = Path(temporary)
            api = stage / 'apps' / 'api'
            api.mkdir(parents=True)
            source_tree(ROOT / 'apps/api/src', api / 'src')
            source_tree(ROOT / 'apps/api/alembic', api / 'alembic')
            shutil.copy2(ROOT / 'apps/api/alembic.ini', api / 'alembic.ini')
            (stage / 'scripts').mkdir()
            for name in SCRIPTS:
                src = ROOT / 'scripts' / name
                if src.is_symlink() or not src.is_file():
                    raise OfflineRehearsalError('Synthetic script source is invalid')
                shutil.copy2(src, stage / 'scripts' / name)
            shutil.copy2(ROOT / 'infra/Dockerfile.restore-sandbox-test', stage / 'Dockerfile')
            args_build = ['docker', 'build', '--pull=false', '--network=none', '-t', image_tag]
            for key, image in base_images.items():
                temporary_tag = f'asb-offline-base-{nonce}-{key.lower()}:synthetic'
                if subprocess.run(['docker', 'image', 'inspect', temporary_tag], capture_output=True, timeout=20).returncode == 0:
                    raise OfflineRehearsalError('Synthetic image tag unexpectedly exists')
                command(['docker', 'image', 'tag', image['Id'], temporary_tag])
                base_tags.append(temporary_tag)
                args_build += ['--build-arg', f'{key}={temporary_tag}']
            print('Building a local synthetic offline recovery image...', flush=True)
            command(args_build + [str(stage)], timeout=600)
        info = json.loads(command(['docker', 'image', 'inspect', image_tag]))
        image_id = info[0]['Id']
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
            raise OfflineRehearsalError('Synthetic image identity is invalid')
        mounts = ['--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=64m,uid=65534,gid=65534,mode=0700',
                  '--tmpfs', '/var/lib/asb-restore:rw,nosuid,nodev,noexec,size=512m,uid=65534,gid=65534,mode=0700',
                  '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size=8m,uid=65534,gid=65534,mode=0700']
        run_attempted = True
        container_id = command(['docker', 'run', '-d', '--name', container_name, '--network', 'none',
            '--read-only', '--user', '65534:65534', *mounts, '--cap-drop', 'ALL', '--security-opt',
            'no-new-privileges', '--pids-limit', '128', '--memory', '1g', '--memory-swap', '1g',
            '--log-driver', 'none', '--label', 'asb.restore.purpose=offline-candidate',
            '--label', f'asb.restore.token={nonce}', image_id]).strip()
        if not re.fullmatch('[0-9a-f]{64}', container_id):
            raise OfflineRehearsalError('Synthetic container identity is invalid')
        def check():
            raw = command([sys.executable, str(ROOT / 'scripts/check_restore_sandbox.py'), '--container-id', container_id,
                           '--image-id', image_id, '--token', nonce])
            if json.loads(raw) != {'status': 'SANDBOX_CONFIGURATION_MATCHES', 'restore_authorized': False}:
                raise OfflineRehearsalError('Offline sandbox did not pass inspection')
        check()
        print('Testing synthetic backup and replay without an external network...', flush=True)
        fixture = ROOT / 'scripts/run_offline_restore_fixture.py'
        raw = command(['docker', 'exec', '-i', '-e', 'ASB_OFFLINE_SYNTHETIC_FIXTURE=true', container_id,
                       '/opt/venv/bin/python', '-'], input_bytes=fixture.read_bytes(), timeout=240)
        result = json.loads(raw)
        if (result.get('status') != 'OFFLINE_SYNTHETIC_REPLAY_PASSED'
                or result.get('restore_authorized') is not False):
            raise OfflineRehearsalError('Synthetic replay did not pass')
        check()
        outcome = {'status': 'PASSED', 'synthetic_data_only': True, 'sandbox_before_after_verified': True,
                   'result': result, 'restore_authorized': False}
    except Exception as exc:
        outcome['error_type'] = type(exc).__name__
        if isinstance(exc, OfflineRehearsalError) and str(exc).startswith('Synthetic fixture failed: '):
            outcome['synthetic_diagnostic'] = str(exc)
    finally:
        cleanup_ok = True
        if run_attempted and (not isinstance(container_id, str) or not re.fullmatch('[0-9a-f]{64}', container_id)):
            try:
                # A daemon may create the container before the CLI loses its
                # response. Recover only the exact image and run-owned labels.
                inspected = json.loads(command(['docker', 'inspect', container_name]))
                item = inspected[0] if isinstance(inspected, list) and len(inspected) == 1 else {}
                labels = item.get('Config', {}).get('Labels') or {}
                if (item.get('Image') != image_id or labels.get('asb.restore.token') != nonce
                        or labels.get('asb.restore.purpose') != 'offline-candidate'
                        or not re.fullmatch('[0-9a-f]{64}', item.get('Id', ''))):
                    raise OfflineRehearsalError('Unowned recovery container')
                container_id = item['Id']
            except Exception:
                # This may also mean the container was never created; a failed
                # inspection cannot prove cleanup, so do not report success.
                cleanup_ok = False
        if container_id and re.fullmatch('[0-9a-f]{64}', container_id):
            try:
                command(['docker', 'rm', '-f', container_id])
            except OfflineRehearsalError:
                cleanup_ok = False
        for tag in ([image_tag] if output_owned else []) + base_tags:
            try:
                exists = subprocess.run(['docker', 'image', 'inspect', tag], capture_output=True, timeout=20).returncode == 0
                if exists:
                    command(['docker', 'image', 'rm', tag])
            except (OfflineRehearsalError, OSError, subprocess.SubprocessError):
                cleanup_ok = False
        outcome['owned_cleanup_complete'] = cleanup_ok
        if not cleanup_ok:
            outcome['status'] = 'FAILED'
    try:
        args.report_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if args.report_dir.is_symlink() or not args.report_dir.is_dir():
            raise OfflineRehearsalError('Report directory invalid')
        report = args.report_dir / f'offline-restore-{nonce}.json'
        with report.open('x') as stream:
            os.chmod(report, 0o600)
            json.dump(outcome, stream, sort_keys=True, indent=2)
            stream.write('\n')
        print(json.dumps({'status': outcome['status'], 'report': str(report), 'restore_authorized': False}))
    except Exception:
        print(json.dumps({'status': 'REPORT_FAILED', 'restore_authorized': False}))
        return 1
    return 0 if outcome['status'] == 'PASSED' else 1


if __name__ == '__main__':
    sys.exit(main())
