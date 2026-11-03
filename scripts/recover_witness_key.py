"""Recover a witness key to a new owner-only file without printing its value.

The recovery secret and immutable envelope reference must already be held in
an independently controlled location. This cannot recover the existing journal
key unless that key was separately enrolled into a compatible envelope.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

from run_scheduled_backup import private_file

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'


def write_new_private_file(path, data):
    if (not isinstance(path, Path) or not path.is_absolute() or not isinstance(data, bytes)
            or not 1 <= len(data) <= 1024):
        raise ValueError('Invalid private output')
    parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    try:
        parent = os.fstat(parent_fd)
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
            raise ValueError('A private output directory is required')
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0),
                     0o600, dir_fd=parent_fd)
        identity = os.fstat(fd)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.fsync(parent_fd)
        except Exception:
            try:
                current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                    os.unlink(path.name, dir_fd=parent_fd)
            except OSError:
                pass
            raise
    finally:
        os.close(parent_fd)


def write_new_private_key(path, key):
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError('Invalid key output')
    write_new_private_file(path, key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery-key-file', required=True, type=Path)
    parser.add_argument('--envelope-reference-file', required=True, type=Path)
    envelope = parser.add_mutually_exclusive_group(required=True)
    envelope.add_argument('--envelope-bucket')
    envelope.add_argument('--envelope-file', type=Path, help='Independent offline copy of encrypted envelope')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        recovery_key = private_file(args.recovery_key_file, max_bytes=32)
        reference = json.loads(private_file(args.envelope_reference_file, max_bytes=1024))
        if not isinstance(reference, dict) or set(reference) != {'namespace', 'key_id', 'sha256'}:
            raise ValueError('Invalid envelope reference')
        sys.path.insert(0, str(API))
        from src.services.privacy_checkpoint_keys import recover_checkpoint_key
        if args.envelope_file:
            envelope_data = private_file(args.envelope_file, max_bytes=1024)

            class OfflineEnvelope:
                def read(self, name):
                    expected = f'privacy-checkpoint-keys/v1/{reference["namespace"]}/{reference["key_id"]}'
                    if name != expected:
                        raise ValueError('Unexpected envelope identity')
                    return envelope_data

            store = OfflineEnvelope()
        else:
            from src.services.privacy_checkpoint_gcs import GCSCheckpointStore
            store = GCSCheckpointStore(args.envelope_bucket)
        try:
            key = recover_checkpoint_key(store, namespace=reference['namespace'], key_id=reference['key_id'],
                expected_sha256=reference['sha256'], recovery_key=recovery_key)
        finally:
            close = getattr(store, 'close', None)
            if close:
                close()
        write_new_private_key(args.output, key)
        print(json.dumps({'status': 'KEY_RECOVERED', 'restore_authorized': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'KEY_RECOVERY_FAILED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
