"""Build a new local monitor candidate without copying configuration or keys.

This creates only the requested new, private local directory. It neither
installs a service nor changes the existing application's current release.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
FILES = ('scripts/check_privacy_purge_queue.py', 'scripts/publish_privacy_purge_health.py',
         'infra/gcp-pilot/asb-privacy-purge-signal.service', 'infra/gcp-pilot/asb-privacy-purge-signal.timer',
         'infra/gcp-pilot/asb-privacy-purge-alert-policy.template.json')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        destination = args.output
        if not destination.is_absolute() or destination.name in ('', '.', '..'):
            raise ValueError('An absolute, new output directory is required')
        parent = destination.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode)
                or parent.st_uid != os.geteuid() or parent.st_mode & 0o077):
            raise ValueError('Output parent must be owner-only')
        source = ROOT / 'apps/api/src'
        paths = [p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        if source.is_symlink() or any(p.is_symlink() for p in source.rglob('*')):
            raise ValueError('Source symlinks are not allowed')
        if any(p.name.startswith('.env') or p.suffix.lower() in {'.key', '.pem', '.db', '.pyc'} for p in paths):
            raise ValueError('Unexpected secret-like or generated file in source')
        inputs = [*paths, *(ROOT / item for item in FILES)]
        if any(p.is_symlink() or not p.is_file() for p in inputs):
            raise ValueError('Input is missing or a symlink')
        hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in inputs}
        os.mkdir(destination, 0o700)  # Exclusive; never replace an existing directory.
        for relative, digest in hashes.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(ROOT / relative, target)
            os.chmod(target, 0o600)
            if sha(target) != digest or sha(ROOT / relative) != digest:
                raise ValueError('Source changed during snapshot')
        if any(sha(ROOT / relative) != digest for relative, digest in hashes.items()):
            raise ValueError('Source changed during snapshot')
        manifest = {'version': 1, 'files': hashes, 'runtime_configuration_copied': False,
                    'installed': False, 'restore_authorized': False}
        manifest_path = destination / 'manifest.json'
        with manifest_path.open('x') as stream:
            os.chmod(manifest_path, 0o600)
            json.dump(manifest, stream, sort_keys=True, indent=2)
            stream.write('\n')
        print(json.dumps({'status': 'CANDIDATE_CREATED', 'file_count': len(hashes),
                          'installed': False, 'restore_authorized': False}))
        return 0
    except Exception:
        # Do not remove a partial directory: another process could have added
        # files to it after creation. A failed snapshot is never installable.
        print(json.dumps({'status': 'CANDIDATE_FAILED', 'installed': False, 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
