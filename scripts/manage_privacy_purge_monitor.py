"""Install or disable the standalone privacy-purge monitor on its designated VM.

No credentials are created or copied. The operator must independently configure
and verify the approved notification policy. Requires explicit --execute.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import urllib.request

ROOT = Path('/opt/ai-story-book/privacy-purge-monitor')
UNIT_DIR = Path('/etc/systemd/system')
PRIVATE = Path('/etc/ai-story-book/pilot/private/privacy-purge-watch.env')
PYTHON = Path('/opt/ai-story-book/current/apps/api/venv/bin/python')
UNITS = ('asb-privacy-purge-signal.service', 'asb-privacy-purge-signal.timer')
BUNDLE_FILES = ('scripts/check_privacy_purge_queue.py', 'scripts/publish_privacy_purge_health.py',
                *(f'infra/gcp-pilot/{name}' for name in UNITS),
                'infra/gcp-pilot/asb-privacy-purge-alert-policy.template.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_file(path, *, mode_mask=0o022):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & mode_mask:
        raise ValueError('Unsafe file ownership, permissions or type')


def bundle_check(bundle, expected):
    # Root-owned sources avoid changes by unprivileged local users during install.
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError('Invalid bundle directory')
    for directory in (bundle, *[p for p in bundle.rglob('*') if p.is_dir()]):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Unsafe bundle directory')
    manifest_path = bundle / 'manifest.json'
    checked_file(manifest_path)
    if digest(manifest_path) != expected:
        raise ValueError('Manifest digest mismatch')
    manifest = json.loads(manifest_path.read_text())
    if (set(manifest) != {'version', 'files', 'runtime_configuration_copied', 'installed', 'restore_authorized'}
            or manifest['version'] != 1 or manifest['runtime_configuration_copied'] is not False
            or manifest['installed'] is not False or manifest['restore_authorized'] is not False
            or not isinstance(manifest['files'], dict)):
        raise ValueError('Invalid manifest')
    files = manifest['files']
    if not all(name in files for name in BUNDLE_FILES) or not 1 <= len(files) <= 1000:
        raise ValueError('Incomplete bundle')
    actual = set()
    for item in bundle.rglob('*'):
        if item.is_symlink():
            raise ValueError('Bundle symlinks are not allowed')
        if item.is_file() and item != manifest_path:
            actual.add(item.relative_to(bundle).as_posix())
    if actual != set(files):
        raise ValueError('Bundle file set differs from manifest')
    for name, expected_file in files.items():
        p = PurePosixPath(name)
        if (p.is_absolute() or any(part in ('', '.', '..') for part in p.parts)
                or not (name.startswith('apps/api/src/') or name in BUNDLE_FILES)
                or not isinstance(expected_file, str) or len(expected_file) != 64):
            raise ValueError('Invalid bundle member')
        source = bundle.joinpath(*p.parts)
        checked_file(source)
        if digest(source) != expected_file:
            raise ValueError('Bundle content mismatch')
    return files


def run(*command):
    # The read-only preflight imports modules from the candidate. Python must
    # not add __pycache__ files between manifest checks and the copy.
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, env=env)


def config_paths():
    checked_file(PRIVATE, mode_mask=0o077)
    # Restrict this small systemd EnvironmentFile to plain absolute paths. No
    # shell expansion, quoting, duplicate assignments or other values allowed.
    entries = {}
    for line in PRIVATE.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if (not sep or key not in {'ASB_PURGE_MONITOR_ENV_FILE', 'ASB_PURGE_MONITOR_CA_FILE'}
                or key in entries or not value.startswith('/') or any(c.isspace() or c in "'\"\\$`" for c in value)):
            raise ValueError('Invalid monitor configuration')
        entries[key] = Path(value)
    if set(entries) != {'ASB_PURGE_MONITOR_ENV_FILE', 'ASB_PURGE_MONITOR_CA_FILE'}:
        raise ValueError('Incomplete monitor configuration')
    checked_file(entries['ASB_PURGE_MONITOR_ENV_FILE'], mode_mask=0o077)
    checked_file(entries['ASB_PURGE_MONITOR_CA_FILE'])
    return entries


def require_root():
    if os.geteuid() != 0:
        raise ValueError('Root is required')


def require_pilot_vm():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = 'http://metadata.google.internal/computeMetadata/v1/'
    expected = {'project/project-id': 'gen-lang-client-0308507618', 'instance/name': 'asb-free-test'}
    for name, value in expected.items():
        request = urllib.request.Request(base + name, headers={'Metadata-Flavor': 'Google'})
        with opener.open(request, timeout=5) as response:
            if response.read(256).decode().strip() != value:
                raise ValueError('Wrong pilot VM')


def install(args):
    require_root()
    require_pilot_vm()
    files = bundle_check(args.bundle, args.manifest_sha256)
    inputs = config_paths()
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        raise ValueError('Application virtualenv unavailable')
    if ROOT.exists() or ROOT.is_symlink() or any((UNIT_DIR / n).exists() or (UNIT_DIR / n).is_symlink() for n in UNITS):
        raise ValueError('Monitor path or unit already exists')
    # Detect loaded/transient units even if their expected unit path is absent.
    for unit in UNITS:
        result = subprocess.run(['systemctl', 'show', unit, '--property=LoadState', '--value'],
                                capture_output=True, text=True, timeout=15, check=False)
        if result.stdout.strip() != 'not-found':
            raise ValueError('Monitor unit already loaded or systemd unavailable')
    # Read-only check before any installation. Fail closed on unknown source,
    # schema, permission, or unresolved erasures; never print its output.
    run(str(PYTHON), str(args.bundle / BUNDLE_FILES[0]), '--execute',
        '--env-file', str(inputs['ASB_PURGE_MONITOR_ENV_FILE']),
        '--ca-file', str(inputs['ASB_PURGE_MONITOR_CA_FILE']))
    os.mkdir(ROOT, 0o700)
    receipt = {'version': 1, 'bundle_manifest_sha256': args.manifest_sha256,
               'units': {name: files[f'infra/gcp-pilot/{name}'] for name in UNITS}}
    with (ROOT / 'installation.json').open('x') as output:
        os.chmod(ROOT / 'installation.json', 0o600)
        json.dump(receipt, output, sort_keys=True)
    # An incomplete attempt is kept for inspection and can be disabled with
    # rollback; it is never overwritten or removed automatically.
    shutil.copytree(args.bundle, ROOT / 'release', symlinks=False)
    bundle_check(ROOT / 'release', args.manifest_sha256)
    os.symlink('release', ROOT / 'current')
    for name in UNITS:
        target = UNIT_DIR / name
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
        with os.fdopen(fd, 'wb') as stream:
            stream.write((ROOT / 'release' / 'infra/gcp-pilot' / name).read_bytes())
    run('systemd-analyze', 'verify', *(str(UNIT_DIR / name) for name in UNITS))
    run('systemctl', 'daemon-reload')
    # First start returns nonzero if the metadata token or metric write fails.
    run('systemctl', 'start', UNITS[0])
    run('systemctl', 'enable', '--now', UNITS[1])
    return 'INSTALLED_FIRST_SIGNAL_SENT'


def rollback(args):
    require_root()
    require_pilot_vm()
    if not args.policy_disabled:
        raise ValueError('Disable this monitor policy first to avoid an absence alert')
    info = ROOT.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('Unsafe monitor installation directory')
    receipt_path = ROOT / 'installation.json'
    checked_file(receipt_path, mode_mask=0o077)
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('version') != 1 or set(receipt.get('units', {})) != set(UNITS):
        raise ValueError('Invalid installation receipt')
    for name in UNITS:
        path = UNIT_DIR / name
        if path.exists() or path.is_symlink():
            checked_file(path)
            if digest(path) != receipt['units'][name]:
                raise ValueError('Installed unit was changed; manual review required')
    # No delete, no impact to backup policy, application, user data or other units.
    if (UNIT_DIR / UNITS[1]).exists():
        run('systemctl', 'disable', '--now', UNITS[1])
    if (UNIT_DIR / UNITS[0]).exists():
        run('systemctl', 'stop', UNITS[0])
    return 'MONITOR_DISABLED_FILES_RETAINED'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'rollback'))
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--policy-disabled', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status': 'DISABLED', 'changed': False}))
        return 0
    try:
        if args.action == 'install':
            if not args.bundle or not args.bundle.is_absolute() or not args.manifest_sha256 or len(args.manifest_sha256) != 64:
                raise ValueError('Absolute bundle and manifest digest required')
            status = install(args)
        else:
            status = rollback(args)
        print(json.dumps({'status': status, 'restore_authorized': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'FAILED_REVIEW_REQUIRED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
