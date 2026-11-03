#!/usr/bin/env python3
"""Isolated stdin-to-private-file primitive; this CLI accepts synthetic keys only.

No remote connection, Keychain access, production path or service is involved.
This is not an operational key-rotation or host-authentication tool.
"""
import argparse
import json
import os
import re
import secrets
import stat
import sys


class ReceiverError(RuntimeError):
    """A secret-free failure; the target must not be treated as committed."""


def _open_private_directory(path, expected_uid):
    descriptors = []
    try:
        if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
                or os.path.normpath(path) != path or path == '/'
                or not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY')):
            raise ValueError('invalid destination')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        descriptors.append(os.open('/', flags))
        for component in path[1:].split('/'):
            descriptors.append(os.open(component, flags, dir_fd=descriptors[-1]))
        directory = os.fstat(descriptors[-1])
        if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != expected_uid
                or directory.st_mode & 0o077):
            raise ValueError('unsafe destination')
        return descriptors.pop()
    except Exception:
        raise ReceiverError('Private destination is unavailable or unsafe') from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _safe_remove_created(directory_fd, filename, identity):
    """Remove only a name still pointing at the inode this operation created."""
    try:
        item = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if (item.st_dev, item.st_ino) != identity or not stat.S_ISREG(item.st_mode):
            return False
        os.unlink(filename, dir_fd=directory_fd)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def install_from_stream(stream, *, directory, filename, expected_uid, expected_gid):
    """Write once by hard-link publication. Callers must keep services fenced.

    The operator/receiver must run with the intended file's effective UID and
    GID. An old destination is never replaced. A crash can leave a complete
    target or a private staging name, so external recovery must inspect state
    before retrying; the absence of a success response does not mean absence.
    """
    if (type(expected_uid) is not int or type(expected_gid) is not int
            or expected_uid != os.geteuid() or expected_gid != os.getegid()
            or not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}\.key', filename)):
        raise ReceiverError('Receiver identity or file name is invalid')
    directory_fd = _open_private_directory(directory, expected_uid)
    staging = '.asb-key-' + secrets.token_hex(16) + '.tmp'
    identity = None
    published = False
    succeeded = False
    try:
        raw = stream.read(4099)
        if not isinstance(raw, bytes) or len(raw) > 4098:
            raise ValueError('invalid input')
        if raw.endswith(b'\r\n'):
            raw = raw[:-2]
        elif raw.endswith(b'\n'):
            raw = raw[:-1]
        if not re.fullmatch(rb'[\x21-\x7e]{1,4096}', raw):
            raise ValueError('invalid input')
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        fd = os.open(staging, flags, 0o600, dir_fd=directory_fd)
        try:
            entry = os.fstat(fd)
            identity = (entry.st_dev, entry.st_ino)
            # A restrictive inherited umask must not silently create a file
            # that its intended owner cannot read after publication.
            os.fchmod(fd, 0o600)
            entry = os.fstat(fd)
            if ((entry.st_dev, entry.st_ino) != identity or not stat.S_ISREG(entry.st_mode) or entry.st_uid != expected_uid
                    or entry.st_gid != expected_gid or entry.st_mode & 0o777 != 0o600):
                raise ValueError('unsafe created file')
            remaining = memoryview(raw)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError('short write')
                remaining = remaining[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        # link() creates the final name atomically and never replaces an old
        # file, symlink, directory, or another publisher's result.
        os.link(staging, filename, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                follow_symlinks=False)
        published = True
        target = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
        if ((target.st_dev, target.st_ino) != identity or not stat.S_ISREG(target.st_mode)
                or target.st_uid != expected_uid or target.st_gid != expected_gid or target.st_mode & 0o777 != 0o600):
            raise ValueError('invalid published file')
        os.fsync(directory_fd)
        if not _safe_remove_created(directory_fd, staging, identity):
            raise OSError('staging cleanup failed')
        os.fsync(directory_fd)
        succeeded = True
    except Exception:
        raise ReceiverError('Private key installation failed') from None
    finally:
        if not succeeded and identity:
            if published:
                _safe_remove_created(directory_fd, filename, identity)
            _safe_remove_created(directory_fd, staging, identity)
            try:
                os.fsync(directory_fd)
            except OSError:
                pass  # Failure is already reported; absence is not guaranteed.
        os.close(directory_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic-fixture', action='store_true', required=True)
    parser.add_argument('--directory', required=True, help='existing private fixture directory')
    args = parser.parse_args()
    try:
        # Make accidental use with an actual provider secret fail closed. The
        # bounded input is not passed to commands or printed on either path.
        value = sys.stdin.buffer.read(4099)
        if not value.startswith(b'synthetic-fixture-'):
            raise ReceiverError('Only synthetic fixture input is permitted')
        from io import BytesIO
        install_from_stream(BytesIO(value), directory=args.directory, filename='provider.key',
                            expected_uid=os.geteuid(), expected_gid=os.getegid())
        print(json.dumps({'status': 'SYNTHETIC_FIXTURE_WRITTEN', 'production_authorized': False}))
        return 0
    except Exception:
        print(json.dumps({'status': 'FIXTURE_FAILED', 'production_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
