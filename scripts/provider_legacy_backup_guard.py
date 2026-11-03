"""Build a pinned legacy backup-guard overlay for isolated verification only.

This tool does not install, deploy, restart, or modify a production service.
The output is a new file; the exact production input SHA is mandatory.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import stat

SOURCE_SHA256 = '9de56dad4e7535116124f3f2fe89136c3e9c604679e86a4f350ab8117d504e86'

_HELPER = '''def assert_no_narration_recovery():
    """Called under backup.lock; fail closed on marker or path uncertainty."""
    for path in (NARRATION_RECOVERY_MARKER, PROVIDER_ROTATION_RECOVERY_MARKER, DOCKER_MUTATION_MARKER):
        if not path.is_absolute() or '..' in path.parts or path.name not in ('recovery.json', 'narration-recovery.json', 'docker-mutation.json'):
            raise GuardError('Recovery marker path is invalid')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
        fd = None
        try:
            fd = os.open('/', flags)
            missing = False
            for component in path.parts[1:-1]:
                try:
                    child = os.open(component, flags, dir_fd=fd)
                except FileNotFoundError:
                    missing = True
                    break
                os.close(fd)
                fd = child
            if missing:
                continue
            try:
                os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise GuardError('Recovery is pending')
        except GuardError:
            raise
        except OSError:
            raise GuardError('Recovery state is unavailable') from None
        finally:
            if fd is not None:
                os.close(fd)

'''


def build_overlay(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('legacy backup source does not match pinned SHA-256')
    text = source.decode('utf-8')
    changes = (
        ("_MARKER = {'version': 1, 'previously_running': [_WORKER, _API]}\n",
         "_MARKER = {'version': 1, 'previously_running': [_WORKER, _API]}\n"
         "NARRATION_RECOVERY_MARKER = Path('/var/lib/ai-story-book/narration-deploy/narration-recovery.json')\n"
         "PROVIDER_ROTATION_RECOVERY_MARKER = Path('/var/lib/ai-story-book/provider-rotation/recovery.json')\n"
         "DOCKER_MUTATION_MARKER = Path('/var/lib/ai-story-book/provider-rotation/docker-mutation.json')\n"),
        ('class DockerRuntime:\n', _HELPER + 'class DockerRuntime:\n'),
        ('    def _recover_unlocked(self):\n',
         '    def _recover_unlocked(self):\n        assert_no_narration_recovery()\n'),
        ('    def run(self, *, verify_idle, backup):\n'
         '        """Run callbacks with worker/API stopped; backup is NOT authorized here."""\n'
         '        fd = self._locked()\n'
         '        try:\n',
         '    def run(self, *, verify_idle, backup):\n'
         '        """Run callbacks with worker/API stopped; backup is NOT authorized here."""\n'
         '        fd = self._locked()\n'
         '        try:\n'
         '            assert_no_narration_recovery()\n'),
    )
    for old, new in changes:
        if text.count(old) != 1:
            raise ValueError('legacy backup source structure does not match')
        text = text.replace(old, new, 1)
    compile(text, '<legacy-backup-overlay>', 'exec')
    return text.encode('utf-8')


def create_overlay(source_path: str, output_path: str) -> str:
    source_fd = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    try:
        source_stat = os.fstat(source_fd)
        if (not stat.S_ISREG(source_stat.st_mode) or source_stat.st_uid != os.geteuid()
                or source_stat.st_mode & 0o077 or source_stat.st_size > 200000):
            raise ValueError('source must be a private owned regular file')
        with os.fdopen(source_fd, 'rb', closefd=False) as f:
            source = f.read(200001)
    finally:
        os.close(source_fd)
    result = build_overlay(source)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    fd = os.open(output_path, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as f:
            f.write(result)
            f.flush()
            os.fsync(f.fileno())
    finally:
        os.close(fd)
    return hashlib.sha256(result).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        digest = create_overlay(args.source, args.output)
    except (ValueError, OSError):
        print('OVERLAY_BUILD_FAILED')
        return 1
    print('OVERLAY_BUILT sha256=' + digest)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
