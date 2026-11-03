"""Build a private code-only payload for the disposable boot fixture.

No cloud resources are created. The input is the hash-pinned production
recovery source, not configuration or credentials. The archive remains private
and must be removed after use; it is not a deployment package.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

from provider_boot_guest_fixture import verify_package


def build(package, privacy_source, output):
    source = verify_package(package, privacy_source)
    destination = Path(output)
    if not destination.is_absolute():
        raise ValueError('absolute new output path required')
    expected = json.loads((source / 'manifest.json').read_text())['files']
    items = {'provider_boot_guest_fixture.py': Path(__file__).with_name('provider_boot_guest_fixture.py').read_bytes(),
             'legacy_privacy.py': Path(privacy_source).read_bytes(),
             'package/manifest.json': (source / 'manifest.json').read_bytes()}
    for name in expected:
        items['package/' + name] = (source / name).read_bytes()
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as raw:
            with tarfile.open(fileobj=raw, mode='w:gz') as archive:
                for name, data in sorted(items.items()):
                    if len(data) > 1024 * 1024:
                        raise ValueError('payload file too large')
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    entry.mode = 0o600
                    entry.uid = entry.gid = entry.mtime = 0
                    archive.addfile(entry, io.BytesIO(data))
            raw.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {'status': 'FIXTURE_PAYLOAD_BUILT', 'sha256': digest,
            'file_count': len(items), 'cloud_resources_created': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--privacy-source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.package, args.privacy_source, args.output), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'FIXTURE_PAYLOAD_FAILED', 'cloud_resources_created': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
