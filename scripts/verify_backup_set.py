"""Verify a private external backup set offline; never restore or contact services.

Checksums detect incomplete/corrupt backup files, not an attacker who can replace
both data and manifest. Keep the set in approved encrypted, access-controlled
storage. This validation does not replay later deletion or identity revocations.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re


class BackupValidationError(ValueError):
    pass


def checked_file(folder, descriptor, expected_name):
    if not isinstance(descriptor, dict) or descriptor.get('file') != expected_name:
        raise BackupValidationError('Unexpected backup file mapping.')
    path = folder / expected_name
    if path.is_symlink() or not path.is_file() or any(part.is_symlink() for part in path.parents if part != folder.parent):
        raise BackupValidationError('Backup files must be regular files within the supplied set.')
    size = descriptor.get('size')
    expected_hash = descriptor.get('sha256')
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise BackupValidationError('Invalid backup size metadata.')
    if not isinstance(expected_hash, str) or not re.fullmatch('[a-f0-9]{64}', expected_hash):
        raise BackupValidationError('Invalid backup checksum metadata.')
    digest = hashlib.sha256()
    actual_size = 0
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            actual_size += len(chunk)
            digest.update(chunk)
    if actual_size != size or digest.hexdigest() != expected_hash:
        raise BackupValidationError('A backup file is incomplete or its checksum differs.')
    return actual_size


def verify(folder):
    if folder.is_symlink() or not folder.is_dir():
        raise BackupValidationError('A non-symlink backup directory is required.')
    # macOS /tmp is itself a symlink; canonicalize the explicitly selected parent.
    folder = folder.resolve()
    manifest_path = folder / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise BackupValidationError('A regular backup manifest is required.')
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        raise BackupValidationError('Backup manifest could not be read.') from None
    if (not isinstance(manifest, dict) or type(manifest.get('format_version')) is not int
            or manifest['format_version'] != 1 or manifest.get('database_scope') != 'public'):
        raise BackupValidationError('Unsupported backup format or database scope.')
    if manifest.get('requires_latest_deletion_and_identity_revocations') is not True:
        raise BackupValidationError('Backup does not carry the mandatory revocation replay requirement.')
    total_size = checked_file(folder, manifest.get('database'), 'database.dump')
    # An empty byte stream is never a usable PostgreSQL archive, even if its
    # declared checksum and size match exactly.  This is only a necessary
    # condition: a nonempty stream still needs a real restore rehearsal.
    if total_size == 0:
        raise BackupValidationError('Database archive is empty.')
    objects = manifest.get('objects')
    if not isinstance(objects, list):
        raise BackupValidationError('Backup media inventory is missing.')
    keys = set()
    filenames = set()
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get('key'), str) or not item['key'] or item['key'] in keys:
            raise BackupValidationError('Backup media inventory contains missing or duplicate entries.')
        keys.add(item['key'])
        filename = 'objects/' + hashlib.sha256(item['key'].encode()).hexdigest()
        total_size += checked_file(folder, item, filename)
        filenames.add(filename)
    objects_dir = folder / 'objects'
    if objects_dir.is_symlink() or not objects_dir.is_dir():
        raise BackupValidationError('A regular backup media directory is required.')
    actual_files = {str(path.relative_to(folder)) for path in objects_dir.iterdir()}
    if actual_files != filenames:
        raise BackupValidationError('Backup media files differ from the manifest inventory.')
    return {'status': 'CHECKSUMS_VERIFIED_NOT_RESTORED', 'object_count': len(objects),
            'total_bytes': total_size, 'remote_calls': 0, 'restore_verified': False,
            'requires_latest_deletion_and_identity_revocations': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-set', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.backup_set)))
        return 0
    except (OSError, BackupValidationError):
        # Never print object names, manifest content, backup path, or provider data.
        print(json.dumps({'status': 'FAILED', 'message': 'Backup checksum/inventory validation failed. No restore was attempted.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
