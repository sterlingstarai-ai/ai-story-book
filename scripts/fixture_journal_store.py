"""Disposable local journal store for synthetic multi-process rehearsals only."""

import os
from pathlib import Path
import re
import stat

from src.services.privacy_journal import JournalError, PrivacyJournal

_NAME = re.compile(r'^privacy-journal/v1/[0-9a-f]{32}/(?:intent|commit|abort)$')


class FixtureStore:
    def __init__(self, root):
        raw = Path(root)
        if raw.is_symlink():
            raise JournalError('Disposable journal symlink refused')
        self.root = raw.resolve()
        parent = self.root.parent
        if (os.environ.get('TESTING') != 'true' or self.root.name != 'journal'
                or not parent.name.startswith('storybook-restore-private-')
                or parent.is_symlink() or self.root.is_symlink()):
            raise JournalError('Disposable journal fixture required')
        st = parent.stat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
            raise JournalError('Disposable journal directory is not private')
        self.root.mkdir(mode=0o700, exist_ok=True)

    def _path(self, name):
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise JournalError('Invalid synthetic journal name')
        path = self.root / name
        if any(p.is_symlink() for p in (path, *path.parents) if p != self.root.parent):
            raise JournalError('Synthetic journal symlink refused')
        return path

    def create(self, name, data):
        path = self._path(name)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def read(self, name):
        path = self._path(name)
        if not path.is_file() or path.stat().st_size > 4096:
            raise JournalError('Synthetic journal record invalid')
        return path.read_bytes()

    def list_names(self, prefix):
        if prefix != 'privacy-journal/v1/' and not re.fullmatch(r'privacy-journal/v1/[0-9a-f]{32}/', prefix):
            raise JournalError('Synthetic journal prefix invalid')
        names = []
        for path in self.root.rglob('*'):
            if path.is_symlink():
                raise JournalError('Synthetic journal symlink refused')
            if path.is_file():
                name = path.relative_to(self.root).as_posix()
                self._path(name)
                if name.startswith(prefix):
                    names.append(name)
        return names


def load_fixture_journal():
    root = os.environ.get('ASB_FIXTURE_JOURNAL_DIR', '')
    encoded_key = os.environ.get('ASB_FIXTURE_JOURNAL_KEY', '')
    if not re.fullmatch('[0-9a-f]{64}', encoded_key):
        raise JournalError('Synthetic journal key is invalid')
    return PrivacyJournal(FixtureStore(root), bytes.fromhex(encoded_key))
