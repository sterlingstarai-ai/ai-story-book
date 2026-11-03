"""Synthetic IAP/CAS-to-sender sequencing; never connects or reads Keychain.

The only metadata transport is in-memory, the identity is synthetic, and the
sender's SSH master and Keychain/transfer portions are replaced by fixtures.
This is not a production authorization or network implementation.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import copy
import datetime as dt
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from unittest.mock import patch

from scripts import provider_key_transfer as sender
from scripts.gcp_instance_ssh_guard import InstanceKeyGuard, UncertainUpdate, make_entry


class FixtureMetadata:
    """In-memory fake only; no external endpoint or credential support."""

    def __init__(self, mode):
        self.data = {'fingerprint': 'fixture-0', 'items': [{'key': 'unrelated', 'value': 'kept'}]}
        self.mode = mode
        self.calls = 0

    def read(self):
        return copy.deepcopy(self.data)

    def compare_and_set(self, value):
        self.calls += 1
        self.data = copy.deepcopy(value)
        self.data['fingerprint'] = 'fixture-' + str(self.calls)
        if (self.mode == 'insert_uncertain' and self.calls == 1
                or self.mode == 'remove_uncertain' and self.calls == 2):
            # Model a daemon that accepted the write before its reply was lost.
            raise UncertainUpdate('synthetic operation outcome unknown')


def run_fixture(mode='success'):
    """Run one fully synthetic sequence and report only fixture events.

    No argument supplies a URL, target, real identity, real provider key, or
    a live metadata transport. Supported fault modes exercise failure gates.
    """
    allowed = {'success', 'master_failure', 'insert_uncertain', 'remove_uncertain', 'identity_cleanup_failure'}
    if mode not in allowed:
        raise ValueError('invalid synthetic fixture mode')
    transport = FixtureMetadata(mode)
    guard = InstanceKeyGuard(transport)
    wire = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + bytes(range(32))
    pub = 'ssh-ed25519 ' + base64.b64encode(wire).decode('ascii')
    entry = make_entry('asbfixture', pub, now=dt.datetime.now(dt.timezone.utc))
    events = []
    receipt = None
    cleanup_confirmed = False
    identity_removed = False
    uncertain = False
    result = None

    with tempfile.TemporaryDirectory(prefix='asb-iap-sender-fixture-') as directory:
        base = Path(directory).resolve()
        path = base / 'identity'
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, b'synthetic-fixture-only')
            os.fsync(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise RuntimeError('fixture identity invalid')
            identity_inode = (info.st_dev, info.st_ino)
        finally:
            os.close(fd)

        def remove_identity():
            nonlocal identity_removed
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or (info.st_dev, info.st_ino) != identity_inode
                    or mode == 'identity_cleanup_failure'):
                raise RuntimeError('fixture identity cleanup failed')
            path.unlink()
            parent = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            if path.exists() or path.is_symlink():
                raise RuntimeError('fixture identity cleanup unconfirmed')
            identity_removed = True
            events.append('identity_removed')

        def on_master_ready():
            nonlocal receipt, cleanup_confirmed, uncertain
            events.append('cleanup_started')
            try:
                guard.remove(entry, receipt)
                receipt = None
                events.append('metadata_removed')
                remove_identity()
                cleanup_confirmed = True
                return True
            except UncertainUpdate:
                uncertain = True
                return False
            except Exception:
                return False

        @contextmanager
        def fake_master(**kwargs):
            if mode == 'master_failure':
                raise sender.TransferError('synthetic master refused')
            if kwargs['identity_file'] != str(path) or not path.is_file():
                raise sender.TransferError('synthetic identity absent')
            events.append('master_authenticated')
            try:
                yield '/synthetic/control', '/synthetic/known_hosts'
            finally:
                events.append('master_closed')

        def fake_keychain_transfer(**_kwargs):
            if not cleanup_confirmed or not identity_removed or path.exists():
                raise sender.TransferError('synthetic cleanup was not confirmed')
            if any(x.get('key') == 'ssh-keys' for x in transport.read()['items']):
                raise sender.TransferError('synthetic metadata remains')
            events.append('synthetic_keychain_read')
            return {'status': 'SYNTHETIC_ONLY', 'recovery_required': False}

        try:
            try:
                receipt = guard.insert(entry)
                events.append('metadata_inserted')
            except UncertainUpdate:
                uncertain = True
                events.append('metadata_insert_uncertain')
                raise
            receiver = b'synthetic-receiver-source'
            with patch.object(sender, '_owned_master', fake_master), \
                    patch.object(sender, '_transfer_on_owned_master', fake_keychain_transfer):
                result = sender.transfer(port=22222, instance_id='12345', transaction_id='a' * 32,
                                         receiver_source=receiver, receiver_sha256=hashlib.sha256(receiver).hexdigest(),
                                         known_hosts_file='/synthetic/known_hosts', identity_file=str(path),
                                         on_master_ready=on_master_ready)
        except Exception:
            events.append('fixture_failed')
        finally:
            pending = receipt or guard._pending
            if pending is not None:
                try:
                    guard.remove(entry, pending)
                    events.append('best_effort_metadata_cleanup')
                except Exception:
                    events.append('metadata_cleanup_unconfirmed')
            # TemporaryDirectory owns only this synthetic identity and will
            # discard it; cleanup_confirmed remains false on any fault.
        return {'status': 'SYNTHETIC_PASSED' if result and cleanup_confirmed and not uncertain else 'SYNTHETIC_BLOCKED',
                'events': events, 'metadata_outcome_uncertain': uncertain, 'production_authorized': False,
                'unrelated_metadata_preserved': {'key': 'unrelated', 'value': 'kept'} in transport.read()['items']}
