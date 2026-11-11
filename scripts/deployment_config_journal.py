"""Durable, root-only rollback data for the two pilot deployment env files.

Callers hold the shared deployment/backup lock for the complete sequence:
prepare -> publish marker with config_journal_sha256 + fsync -> apply -> verify
-> remove marker + fsync -> discard_committed. Marker removal is the commit
point. Afterwards discard_committed never restores configuration. Install the
matching recovery reader before publishing a marker with the optional pin;
legacy readers reject this additional field even though the version stays 1.
The journal contains secrets and must never be printed or included in artifacts.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


ENV_PATHS = (
    Path('/etc/ai-story-book/pilot/private/provider-refresh.env'),
    Path('/etc/ai-story-book/pilot/private/pilot.env'),
)
_ROOT_UID = 0
_LIMIT = 1024 * 1024
_HASH = re.compile(r'[0-9a-f]{64}')


class JournalError(RuntimeError):
    """A secret-free error; retained state requires investigation."""


def _root():
    if os.geteuid() != _ROOT_UID:
        raise JournalError('Configuration journal requires root')


def _sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_directory(path):
    value = path.lstat()
    if (not stat.S_ISDIR(value.st_mode) or value.st_uid != _ROOT_UID
            or value.st_mode & 0o077):
        raise JournalError('Configuration journal directory is unsafe')


def _read(path, limit=_LIMIT):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            value = os.fstat(stream.fileno())
            if (not stat.S_ISREG(value.st_mode) or value.st_uid != _ROOT_UID
                    or value.st_mode & 0o7077 or value.st_size > limit):
                raise JournalError('Configuration journal file is unsafe')
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise JournalError('Configuration journal file exceeds limit')
            return data, value
    except OSError:
        raise JournalError('Configuration journal file is unavailable') from None


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _atomic(path, data, *, uid, gid, mode, exclusive=False):
    fd, name = tempfile.mkstemp(prefix='.config-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        if exclusive:
            os.link(name, path, follow_symlinks=False)
            os.unlink(name)
        else:
            os.replace(name, path)
        _sync(path.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


class DeploymentConfigJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'journal.json'

    def prepare(self, updates):
        """Save both previous files and intended hashes without changing env files."""
        _root()
        if set(updates) != set(ENV_PATHS) or any(type(data) is not bytes or len(data) > _LIMIT
                                               for data in updates.values()):
            raise JournalError('Exactly the allowlisted configuration files are required')
        if os.path.lexists(self.directory):
            raise JournalError('Configuration journal already exists')
        _private_directory(self.directory.parent)
        entries = []
        for path in ENV_PATHS:
            previous, value = _read(path)
            entries.append({'path': str(path), 'previous_b64': base64.b64encode(previous).decode('ascii'),
                            'uid': value.st_uid, 'gid': value.st_gid,
                            'mode': stat.S_IMODE(value.st_mode), 'previous_sha256': _sha(previous),
                            'intended_sha256': _sha(updates[path])})
        encoded = (json.dumps({'version': 1, 'files': entries}, sort_keys=True,
                              separators=(',', ':')) + '\n').encode()
        self.directory.mkdir(mode=0o700)
        _sync(self.directory.parent)
        _atomic(self.path, encoded, uid=_ROOT_UID, gid=os.getegid(), mode=0o600, exclusive=True)
        return _sha(encoded)

    def _load(self, expected_sha256=None):
        _root()
        _private_directory(self.directory)
        if {path.name for path in self.directory.iterdir()} != {'journal.json'}:
            raise JournalError('Configuration journal is incomplete or contains unknown files')
        encoded, _ = _read(self.path, limit=4 * _LIMIT)
        if expected_sha256 is not None and (
                not isinstance(expected_sha256, str) or not _HASH.fullmatch(expected_sha256)
                or _sha(encoded) != expected_sha256):
            raise JournalError('Configuration journal pin does not match')
        try:
            value = json.loads(encoded)
            if (type(value) is not dict or set(value) != {'version', 'files'}
                    or type(value['version']) is not int or value['version'] != 1
                    or type(value['files']) is not list or len(value['files']) != len(ENV_PATHS)):
                raise ValueError
            seen = set()
            for item in value['files']:
                if type(item) is not dict or set(item) != {
                        'path', 'previous_b64', 'uid', 'gid', 'mode', 'previous_sha256', 'intended_sha256'}:
                    raise ValueError
                path = Path(item['path'])
                if path not in ENV_PATHS or path in seen:
                    raise ValueError
                seen.add(path)
                if (any(type(item[key]) is not int for key in ('uid', 'gid', 'mode'))
                        or item['uid'] != _ROOT_UID or item['gid'] < 0
                        or not 0 <= item['mode'] <= 0o777 or item['mode'] & 0o077
                        or any(not isinstance(item[key], str) or not _HASH.fullmatch(item[key])
                               for key in ('previous_sha256', 'intended_sha256'))):
                    raise ValueError
                previous = base64.b64decode(item['previous_b64'], validate=True)
                if len(previous) > _LIMIT or _sha(previous) != item['previous_sha256']:
                    raise ValueError
                item['previous'] = previous
            return value['files']
        except (ValueError, TypeError, KeyError):
            raise JournalError('Configuration journal contents are invalid') from None

    def _validated_targets(self, entries):
        # Validate every file before replacing any. A third-party change must
        # never be overwritten, including when it affects the second file.
        for item in entries:
            current, value = _read(Path(item['path']))
            if (_sha(current) not in (item['previous_sha256'], item['intended_sha256'])
                    or (value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode))
                    != (item['uid'], item['gid'], item['mode'])):
                raise JournalError('Configuration changed outside this deployment')

    def apply(self, updates, *, expected_sha256):
        """Apply the intended bytes; the caller has durably published its marker."""
        entries = self._load(expected_sha256)
        if (set(updates) != set(ENV_PATHS)
                or any(type(updates[Path(item['path'])]) is not bytes
                       or _sha(updates[Path(item['path'])]) != item['intended_sha256'] for item in entries)):
            raise JournalError('Configuration does not match the intended update')
        self._validated_targets(entries)
        for item in entries:
            self._validated_targets([item])
            _atomic(Path(item['path']), updates[Path(item['path'])], uid=item['uid'],
                    gid=item['gid'], mode=item['mode'])

    def restore(self, *, expected_sha256=None):
        """Restore an uncommitted deployment, retaining the journal for retries."""
        if not self.validate_restore(expected_sha256=expected_sha256):
            return False
        entries = self._load(expected_sha256)
        self._validated_targets(entries)
        for item in entries:
            self._validated_targets([item])
            _atomic(Path(item['path']), item['previous'], uid=item['uid'],
                    gid=item['gid'], mode=item['mode'])
        return True

    def validate_restore(self, *, expected_sha256=None):
        """Fail before container mutation if durable rollback data is unavailable."""
        if not os.path.lexists(self.directory):
            if expected_sha256 is not None:
                raise JournalError('Required configuration journal is missing')
            return False  # Legacy version-1 container-only deployment.
        if expected_sha256 is None:
            raise JournalError('Configuration journal is not bound to the rollback marker')
        entries = self._load(expected_sha256)
        self._validated_targets(entries)
        return True

    def discard_committed(self):
        """Never read or change live env files after the privacy commit point."""
        if not os.path.lexists(self.directory):
            return False
        _root()
        _private_directory(self.directory)
        if not any(self.directory.iterdir()):
            # A crash after journal unlink but before rmdir is a committed
            # cleanup interruption, not a reason to restore live env files.
            self.directory.rmdir()
            _sync(self.directory.parent)
            return True
        self._load()
        self.path.unlink()
        _sync(self.directory)
        self.directory.rmdir()
        _sync(self.directory.parent)
        return True
