"""Receive a bounded backup stream into an already-isolated tmpfs sandbox.

This helper never restores a database or publishes a service. It emits only a
binary status; backup content, object keys and original paths are never logged.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

from verify_backup_set import verify

ROOT = Path('/var/lib/asb-restore')
MAX_MANIFEST = 16 * 1024 * 1024
MAX_TOTAL = 384 * 1024 * 1024
MAX_OBJECTS = 10000


class ReceiveError(RuntimeError):
    pass


def _line(stream):
    raw = stream.readline(4097)
    if not raw.endswith(b'\n') or len(raw) > 4096:
        raise ReceiveError('Invalid stream frame')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ReceiveError('Invalid stream frame') from None
    if not isinstance(value, dict):
        raise ReceiveError('Invalid stream frame')
    return value


def _receive_file(stream, path, size, expected):
    if type(size) is not int or not 0 <= size <= MAX_TOTAL or not re.fullmatch('[0-9a-f]{64}', expected or ''):
        raise ReceiveError('Invalid stream descriptor')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    digest = hashlib.sha256()
    remaining = size
    with os.fdopen(fd, 'wb') as output:
        while remaining:
            chunk = stream.read(min(remaining, 65536))
            if not chunk:
                raise ReceiveError('Backup stream is incomplete')
            output.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        output.flush()
        os.fsync(output.fileno())
    if digest.hexdigest() != expected:
        raise ReceiveError('Backup stream checksum differs')


def receive(stream, token):
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token):
        raise ReceiveError('Invalid sandbox token')
    if ROOT.is_symlink() or not ROOT.is_dir() or any(ROOT.iterdir()):
        raise ReceiveError('Sandbox must be empty')
    folder = ROOT / ('ingest-' + token)
    folder.mkdir(mode=0o700)
    complete = False
    try:
        header = _line(stream)
        if (set(header) != {'kind', 'size', 'sha256'} or header['kind'] != 'manifest'
                or type(header['size']) is not int or not 0 < header['size'] <= MAX_MANIFEST):
            raise ReceiveError('Invalid manifest frame')
        _receive_file(stream, folder / 'manifest.json', header['size'], header['sha256'])
        manifest_bytes = (folder / 'manifest.json').read_bytes()
        manifest = json.loads(manifest_bytes)
        verification = _line(stream)
        if (set(verification) != {'kind', 'size', 'sha256'} or verification['kind'] != 'verification'
                or type(verification['size']) is not int or not 0 < verification['size'] <= 4096):
            raise ReceiveError('Invalid backup verification frame')
        _receive_file(stream, folder / 'verified.json', verification['size'], verification['sha256'])
        marker = json.loads((folder / 'verified.json').read_bytes())
        if (not isinstance(marker, dict) or type(marker.get('version')) is not int or marker['version'] != 1
                or marker.get('restore_authorized') is not False
                or marker.get('manifest_sha256') != hashlib.sha256(manifest_bytes).hexdigest()):
            raise ReceiveError('Backup verification marker does not match')
        objects = manifest.get('objects') if isinstance(manifest, dict) else None
        if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
            raise ReceiveError('Invalid backup inventory')
        descriptors = [manifest.get('database'), *objects]
        names = set()
        total = header['size'] + verification['size']
        (folder / 'objects').mkdir(mode=0o700)
        for index, descriptor in enumerate(descriptors):
            if not isinstance(descriptor, dict):
                raise ReceiveError('Invalid backup inventory')
            if index == 0:
                name = 'database.dump'
            else:
                key = descriptor.get('key')
                if not isinstance(key, str) or not key:
                    raise ReceiveError('Invalid backup inventory')
                name = 'objects/' + hashlib.sha256(key.encode()).hexdigest()
            size, digest = descriptor.get('size'), descriptor.get('sha256')
            if (descriptor.get('file') != name or name in names or type(size) is not int or size < 0
                    or (index == 0 and size == 0)):
                raise ReceiveError('Invalid backup inventory')
            names.add(name)
            total += size
            if total > MAX_TOTAL:
                raise ReceiveError('Backup exceeds sandbox capacity limit')
            frame = _line(stream)
            if frame != {'kind': 'object', 'name': name, 'size': size, 'sha256': digest}:
                raise ReceiveError('Backup frame does not match manifest')
            _receive_file(stream, folder / name, size, digest)
        if _line(stream) != {'kind': 'end'} or stream.read(1) != b'':
            raise ReceiveError('Backup stream termination is invalid')
        checked = verify(folder)
        if checked.get('restore_verified') is not False:
            raise ReceiveError('Unexpected backup verification result')
        # This is a quarantine marker only; it must never release restored data.
        marker = folder / 'quarantined.json'
        with marker.open('x') as output:
            os.chmod(marker, 0o600)
            json.dump({'status': 'BACKUP_IMPORTED_QUARANTINED', 'restore_authorized': False}, output)
            output.flush()
            os.fsync(output.fileno())
        complete = True
        return {'status': 'BACKUP_IMPORTED_QUARANTINED', 'restore_authorized': False}
    finally:
        if not complete:
            shutil.rmtree(folder)


def main():
    try:
        if len(sys.argv) != 2:
            raise ReceiveError('Sandbox token required')
        print(json.dumps(receive(sys.stdin.buffer, sys.argv[1]), sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({'status': 'BACKUP_IMPORT_FAILED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
