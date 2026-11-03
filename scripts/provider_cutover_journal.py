"""Durable intent for a single provider-cutover Docker operation.

This primitive does not authorize or implement production cutover. Callers
must hold the shared deployment lock and prove the boot guards are installed.
An unsuccessful or interrupted operation intentionally leaves the journal.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

_ID = re.compile(r'[0-9a-f]{64}\Z')
_TOKEN = re.compile(r'[0-9a-f]{32}\Z')
_ACTIONS = frozenset({'start', 'stop', 'rename', 'restart-no', 'restart-unless-stopped', 'nginx-quit', 'nginx-reload', 'provider-probe', 'probe-create', 'probe-remove', 'candidate-create'})


class JournalError(RuntimeError):
    pass


def _sync(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run_journaled(directory: Path, *, transaction: str, action: str, container: str,
                  execute, verify) -> None:
    """Run one operation; only completed and independently verified work clears intent.

    No callbacks may include secret material in their exceptions or logs. An
    existing journal is never overwritten or removed. This function is not a
    substitute for daemon reconciliation after a timeout or process death.
    """
    directory = Path(directory)
    if (not directory.is_absolute() or not _TOKEN.fullmatch(transaction)
            or action not in _ACTIONS or not _ID.fullmatch(container)):
        raise JournalError('Invalid operation identity')
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise JournalError('Unsafe journal directory')
    path = directory / 'docker-mutation.json'
    payload = (json.dumps({'version': 1, 'transaction': transaction, 'action': action,
                           'container': container}, sort_keys=True) + '\n').encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise JournalError('Unresolved operation or journal unavailable') from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid():
            raise JournalError('Unsafe operation journal')
        pending = memoryview(payload)
        while pending:
            count = os.write(fd, pending)
            if count <= 0:
                raise JournalError('Could not write operation journal')
            pending = pending[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync(directory)
    # BaseException is intentionally not caught: the journal must survive.
    execute()
    if verify() is not True:
        raise JournalError('Operation completion not verified')
    current = path.lstat()
    if (not stat.S_ISREG(current.st_mode) or current.st_dev != st.st_dev
            or current.st_ino != st.st_ino or current.st_nlink != 1):
        raise JournalError('Operation journal identity changed')
    path.unlink()
    _sync(directory)
