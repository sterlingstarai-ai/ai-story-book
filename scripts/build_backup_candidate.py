"""Build and verify a local backup-code candidate; never install or run it.

This is a source artifact, not a virtualenv, image, or production readiness
proof. It contains no environment files, credentials, databases, or backups.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_NAMES = (
    'run_scheduled_backup.py', 'automatic_backup.py', 'backup_external.py',
    'backup_service_guard.py', 'postgres_backup_fence.py', 'publish_backup_gcs.py',
    'verify_backup_set.py', 'final_external_preflight.py',
    'narration_marker_exec_condition.py', 'narration_deploy_safety.py',
    'provider_rotation_quarantine.py', 'check_backup_status.py', 'publish_backup_health.py',
)
UNIT_NAMES = ('asb-backup.service', 'asb-backup.timer', 'asb-backup-recover.service',
              'asb-backup-recover.service.d/narration-guard.conf',
              'asb-backup-recover.service.d/provider-order.conf',
              'asb-backup-watch.service', 'asb-backup-watch.timer',
              'asb-backup-signal.service', 'asb-backup-signal.timer',
              'asb-provider-rotation-quarantine.service')
_HASH = re.compile(r'^[0-9a-f]{64}$')


class CandidateError(ValueError):
    pass


def _files(root):
    names = [f'scripts/{name}' for name in SCRIPT_NAMES]
    names += [f'infra/gcp-pilot/{name}' for name in UNIT_NAMES]
    names.append('apps/api/requirements.txt')
    names.append('apps/api/scripts/activate_generation_budget.py')
    for directory in ('apps/api/src', 'apps/api/alembic'):
        base = root / directory
        if base.is_symlink() or not base.is_dir():
            raise CandidateError('Source directory is unavailable')
        for path in base.rglob('*'):
            if path.is_symlink():
                raise CandidateError('Source symlinks are not accepted')
            if path.is_file() and path.suffix in {'.py', '.jinja2'}:
                names.append(path.relative_to(root).as_posix())
    if len(names) != len(set(names)):
        raise CandidateError('Duplicate candidate path')
    return sorted(names)


def build(root, output):
    root = Path(root).resolve(strict=True)
    output = Path(output)
    if not output.is_absolute() or not output.parent.is_dir() or output.parent.is_symlink():
        raise CandidateError('An absolute output under an existing directory is required')
    names = _files(root)
    output.mkdir(mode=0o700)  # Never replace an existing candidate.
    hashes = {}
    for name in names:
        source = root / name
        if source.is_symlink() or not source.is_file() or any(p.is_symlink() for p in source.parents if p != root):
            raise CandidateError('Candidate source is not a regular file')
        data = source.read_bytes()
        if len(data) > 5 * 1024 * 1024:
            raise CandidateError('Candidate source exceeds the size limit')
        target = output / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open('xb') as dest:
            os.chmod(target, 0o600)
            dest.write(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    manifest = {'version': 1, 'files': hashes, 'production_install_authorized': False,
                'restore_authorized': False, 'virtualenv_included': False}
    encoded = (json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode()
    with (output / 'manifest.json').open('xb') as dest:
        os.chmod(output / 'manifest.json', 0o600)
        dest.write(encoded)
    return hashlib.sha256(encoded).hexdigest()


def verify(output, pin):
    output = Path(output)
    if not _HASH.fullmatch(pin) or output.is_symlink() or not output.is_dir():
        raise CandidateError('Invalid candidate or manifest pin')
    manifest_file = output / 'manifest.json'
    if manifest_file.is_symlink() or not manifest_file.is_file():
        raise CandidateError('Candidate manifest is unavailable')
    data = manifest_file.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin:
        raise CandidateError('Manifest does not match the independent pin')
    try:
        manifest = json.loads(data)
    except (ValueError, TypeError):
        raise CandidateError('Invalid candidate manifest') from None
    if (not isinstance(manifest, dict) or set(manifest) != {
            'version', 'files', 'production_install_authorized', 'restore_authorized', 'virtualenv_included'}
            or type(manifest['version']) is not int or manifest['version'] != 1
            or any(manifest[key] is not False for key in ('production_install_authorized', 'restore_authorized', 'virtualenv_included'))
            or not isinstance(manifest['files'], dict)):
        raise CandidateError('Invalid candidate manifest')
    actual = set()
    for path in output.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise CandidateError('Candidate contains an invalid entry')
        if not path.is_file():
            continue
        name = path.relative_to(output).as_posix()
        if name == 'manifest.json':
            continue
        expected = manifest['files'].get(name)
        if not isinstance(expected, str) or not _HASH.fullmatch(expected):
            raise CandidateError('Unexpected candidate file')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise CandidateError('Candidate content differs')
        actual.add(name)
    if actual != set(manifest['files']):
        raise CandidateError('Candidate is incomplete')
    return len(actual)


def compare_source(root, output, pin):
    """Compare a verified artifact with the current source, without installing."""
    verify(output, pin)
    root = Path(root).resolve(strict=True)
    manifest = json.loads((Path(output) / 'manifest.json').read_bytes())
    if set(_files(root)) != set(manifest['files']):
        raise CandidateError('Source inventory has changed')
    for name, expected in manifest['files'].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise CandidateError('Source content has changed')
    return len(manifest['files'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'verify'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--compare-source', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'build':
            if args.manifest_sha256 is not None or args.compare_source:
                raise CandidateError('Pin is only accepted for verification')
            pin = build(ROOT, args.output)
            print(json.dumps({'status': 'LOCAL_CANDIDATE_CREATED', 'manifest_sha256': pin,
                              'production_install_authorized': False}))
        else:
            count = (compare_source(ROOT, args.output, args.manifest_sha256 or '')
                     if args.compare_source else verify(args.output, args.manifest_sha256 or ''))
            print(json.dumps({'status': 'LOCAL_CANDIDATE_VERIFIED', 'file_count': count,
                              'source_compared': args.compare_source,
                              'production_install_authorized': False}))
    except (CandidateError, OSError):
        print(json.dumps({'status': 'FAILED', 'production_install_authorized': False}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
