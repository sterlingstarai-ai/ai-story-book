"""Private append-only local ledger for future IAP provider sender sessions.

Records public SSH metadata and state only, never bearer tokens or provider keys.
It is not an operator reconciliation or automatic authorization mechanism.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import uuid


class LedgerError(RuntimeError):
    pass


_ID = re.compile(r'[0-9a-f]{32}\Z')
_FILE = re.compile(r'([0-9a-f]{32})\.(session-open|session-closed|op-start|op-operation|op-done)\.json\Z')
_MAX_FILES = 10000
_MAX_RECORD = 16384
_TARGET = {'project': 'gen-lang-client-0308507618', 'zone': 'us-central1-c',
           'instance': 'asb-free-test', 'instance_id': '1428786032988053776'}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


class SenderSessionLedger:
    """One private canonical directory and one non-blocking process lock."""

    def __init__(self, directory):
        self._dir = None
        self._lock = None
        try:
            path = Path(directory)
            if not path.is_absolute() or str(path.resolve(strict=True)) != str(path):
                raise ValueError()
            self._dir = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(self._dir)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077):
                raise ValueError()
            self._lock = os.open('session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=self._dir)
            lock_info = os.fstat(self._lock)
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid()
                    or lock_info.st_mode & 0o077 or lock_info.st_nlink != 1):
                raise ValueError()
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self.close()
            raise LedgerError('Private IAP session ledger is unavailable') from None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None
        if self._dir is not None:
            os.close(self._dir)
            self._dir = None

    def _write(self, identifier, kind, payload):
        if not _ID.fullmatch(identifier) or kind not in {'session-open', 'session-closed',
                                                           'op-start', 'op-operation', 'op-done'}:
            raise LedgerError('Invalid IAP ledger record')
        value = {'version': 1, 'id': identifier, 'kind': kind, **payload}
        data = _canonical(value)
        envelope = _canonical({'record': value, 'sha256': hashlib.sha256(data).hexdigest()})
        if len(envelope) > _MAX_RECORD:
            raise LedgerError('IAP ledger record is too large')
        fd = None
        try:
            fd = os.open(f'{identifier}.{kind}.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self._dir)
            view = memoryview(envelope)
            while view:
                n = os.write(fd, view)
                if n <= 0:
                    raise OSError('short ledger write')
                view = view[n:]
            os.fsync(fd)
            os.fsync(self._dir)
        except Exception:
            raise LedgerError('IAP ledger persistence is unconfirmed') from None
        finally:
            if fd is not None:
                os.close(fd)

    def _read(self, filename):
        match = _FILE.fullmatch(filename)
        if not match:
            raise LedgerError('Unexpected IAP ledger entry')
        fd = None
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self._dir)
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                    or before.st_mode & 0o077 or before.st_nlink != 1 or before.st_size > _MAX_RECORD):
                raise ValueError()
            raw = os.read(fd, _MAX_RECORD + 1)
            after = os.fstat(fd)
            if (len(raw) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in
                    ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
                raise ValueError()
            envelope = json.loads(raw)
            record = envelope['record']
            if (set(envelope) != {'record', 'sha256'} or not isinstance(record, dict)
                    or hashlib.sha256(_canonical(record)).hexdigest() != envelope['sha256']
                    or type(record.get('version')) is not int or record.get('version') != 1
                    or record.get('id') != match.group(1)
                    or record.get('kind') != match.group(2)):
                raise ValueError()
            return record
        except Exception:
            raise LedgerError('IAP ledger record is damaged or inaccessible') from None
        finally:
            if fd is not None:
                os.close(fd)

    def _records(self):
        names = os.listdir(self._dir)
        if len(names) > _MAX_FILES:
            raise LedgerError('IAP ledger has too many entries')
        records = {}
        for name in names:
            if name == 'session.lock':
                continue
            value = self._read(name)
            key = (value['id'], value['kind'])
            if key in records:
                raise LedgerError('IAP ledger has duplicate entries')
            records[key] = value
        return records

    def assert_quiescent(self):
        records = self._records()
        sessions = {i for i, k in records if k == 'session-open'}
        closed = {i for i, k in records if k == 'session-closed'}
        starts = {i for i, k in records if k == 'op-start'}
        operations = {i for i, k in records if k == 'op-operation'}
        done = {i for i, k in records if k == 'op-done'}
        if sessions != closed or starts != done or not operations <= starts:
            raise LedgerError('An earlier IAP session or GCE operation is unresolved')
        for identifier in sessions:
            opened, finished = records[(identifier, 'session-open')], records[(identifier, 'session-closed')]
            if (set(opened) != {'version', 'id', 'kind', 'temporary_directory', 'target'}
                    or not isinstance(opened['temporary_directory'], str)
                    or opened['target'] != _TARGET
                    or set(finished) != {'version', 'id', 'kind', 'metadata_removed', 'identity_removed', 'tunnel_closed'}
                    or any(finished[x] is not True for x in ('metadata_removed', 'identity_removed', 'tunnel_closed'))):
                raise LedgerError('IAP session closure is invalid')
        for identifier in starts:
            started, finished = records[(identifier, 'op-start')], records[(identifier, 'op-done')]
            if (set(started) != {'version', 'id', 'kind', 'session', 'request_id', 'owned_entry', 'metadata_fingerprint', 'action'}
                    or started.get('session') not in sessions or not isinstance(started.get('owned_entry'), str)
                    or not isinstance(started.get('metadata_fingerprint'), str)
                    or not re.fullmatch(r'[A-Za-z0-9_+/=-]{1,256}', started['metadata_fingerprint'])
                    or started.get('action') not in {'insert', 'remove'}
                    or set(finished) != {'version', 'id', 'kind', 'session', 'outcome'}
                    or finished.get('session') != started['session']
                    or finished.get('outcome') not in {'applied', 'rejected'}):
                raise LedgerError('IAP operation record is invalid')
            try:
                parsed = uuid.UUID(started['request_id'])
                if str(parsed) != started['request_id'] or parsed.int == 0:
                    raise ValueError()
            except (ValueError, TypeError, KeyError, AttributeError):
                raise LedgerError('IAP request identity is invalid') from None
            operation = records.get((identifier, 'op-operation'))
            if finished['outcome'] == 'applied' and operation is None:
                raise LedgerError('Applied operation identity is missing')
            if operation is not None and (set(operation) != {'version', 'id', 'kind', 'session', 'operation'}
                                           or operation.get('session') != started['session']
                                           or not isinstance(operation.get('operation'), str)
                                           or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', operation['operation'])):
                raise LedgerError('IAP operation identity is invalid')

    def begin_session(self, temporary_directory):
        self.assert_quiescent()
        if not isinstance(temporary_directory, str) or not os.path.isabs(temporary_directory):
            raise LedgerError('IAP temporary directory is invalid')
        identifier = secrets.token_hex(16)
        self._write(identifier, 'session-open', {'temporary_directory': temporary_directory, 'target': _TARGET})
        return identifier

    def begin_operation(self, session_id, owned_entry, *, metadata_fingerprint, action):
        if (not _ID.fullmatch(session_id) or not isinstance(owned_entry, str) or not 1 <= len(owned_entry) <= 4096
                or not isinstance(metadata_fingerprint, str)
                or not re.fullmatch(r'[A-Za-z0-9_+/=-]{1,256}', metadata_fingerprint)
                or action not in {'insert', 'remove'}):
            raise LedgerError('IAP operation intent is invalid')
        opened = self._read(f'{session_id}.session-open.json')
        if opened.get('id') != session_id:
            raise LedgerError('IAP session identity is invalid')
        try:
            os.stat(f'{session_id}.session-closed.json', dir_fd=self._dir, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise LedgerError('IAP session is already closed')
        identifier, request_id = secrets.token_hex(16), str(uuid.uuid4())
        self._write(identifier, 'op-start', {'session': session_id, 'request_id': request_id,
                                              'owned_entry': owned_entry, 'metadata_fingerprint': metadata_fingerprint,
                                              'action': action})
        return identifier, request_id

    def record_operation(self, identifier, session_id, operation):
        if not _ID.fullmatch(session_id) or not isinstance(operation, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', operation):
            raise LedgerError('IAP operation identity is invalid')
        if self._read(f'{identifier}.op-start.json').get('session') != session_id:
            raise LedgerError('IAP operation session differs')
        self._write(identifier, 'op-operation', {'session': session_id, 'operation': operation})

    def finish_operation(self, identifier, session_id, outcome):
        if not _ID.fullmatch(session_id) or outcome not in {'applied', 'rejected'}:
            raise LedgerError('IAP operation outcome is invalid')
        if self._read(f'{identifier}.op-start.json').get('session') != session_id:
            raise LedgerError('IAP operation session differs')
        if outcome == 'applied' and self._read(f'{identifier}.op-operation.json').get('session') != session_id:
            raise LedgerError('Applied IAP operation identity is missing')
        self._write(identifier, 'op-done', {'session': session_id, 'outcome': outcome})

    def close_session(self, session_id, *, metadata_removed, identity_removed, tunnel_closed):
        if metadata_removed is not True or identity_removed is not True or tunnel_closed is not True:
            raise LedgerError('IAP access cleanup is unconfirmed')
        records = self._records()
        if (session_id, 'session-open') not in records or (session_id, 'session-closed') in records:
            raise LedgerError('IAP session cannot be closed')
        for (identifier, kind), record in records.items():
            if kind == 'op-start' and record.get('session') == session_id:
                done = records.get((identifier, 'op-done'))
                if done is None or done.get('session') != session_id:
                    raise LedgerError('IAP operation completion is unconfirmed')
        self._write(session_id, 'session-closed', {'metadata_removed': True, 'identity_removed': True,
                                                    'tunnel_closed': True})
        self.assert_quiescent()
