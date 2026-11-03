import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from provider_key_receiver import ReceiverError, _lock_and_check_recovery, install, recover


class ProviderKeyReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = str(Path(self.tmp.name).resolve())
        self.path = Path(self.directory)
        self.token = 'a' * 32
        self.identity = {'directory': self.directory, 'token': self.token,
                         'directory_owner': os.geteuid(), 'target_uid': os.geteuid(), 'target_gid': os.getegid()}

    def test_installs_private_key_without_overwriting(self):
        self.assertEqual(install(io.BytesIO(b'synthetic-key\n'), **self.identity)['status'], 'KEY_FILE_INSTALLED')
        target = self.path / 'provider.key'
        self.assertEqual(target.read_bytes(), b'synthetic-key')
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ReceiverError):
            install(io.BytesIO(b'other-key'), **self.identity)
        self.assertEqual(target.read_bytes(), b'synthetic-key')

    def test_partial_stage_is_removed_but_existing_target_is_never_deleted(self):
        marker = self.path / ('.asb-key-' + self.token + '.json')
        stage = self.path / ('.asb-key-' + self.token + '.tmp')
        marker.write_text(json.dumps({'version': 1, 'token': self.token,
                                      'sha256': hashlib.sha256(b'key').hexdigest()}))
        marker.chmod(0o600)
        stage.write_bytes(b'partial')
        stage.chmod(0o600)
        self.assertEqual(recover(**self.identity)['status'], 'TRANSFER_CANCELLED')
        self.assertFalse(marker.exists())
        self.assertFalse(stage.exists())

    def test_published_key_can_be_recovered_but_changed_target_blocks(self):
        marker = self.path / ('.asb-key-' + self.token + '.json')
        stage = self.path / ('.asb-key-' + self.token + '.tmp')
        final = self.path / 'provider.key'
        marker.write_text(json.dumps({'version': 1, 'token': self.token,
                                      'sha256': hashlib.sha256(b'key').hexdigest()}))
        marker.chmod(0o600)
        stage.write_bytes(b'key')
        stage.chmod(0o600)
        os.link(stage, final)
        self.assertEqual(recover(**self.identity)['status'], 'KEY_FILE_PRESENT')
        self.assertEqual(final.read_bytes(), b'key')
        self.assertFalse(stage.exists())
        self.assertFalse(marker.exists())
        marker.write_text(json.dumps({'version': 1, 'token': self.token, 'sha256': '0' * 64}))
        marker.chmod(0o600)
        with self.assertRaises(ReceiverError):
            recover(**self.identity)
        self.assertEqual(final.read_bytes(), b'key')
        self.assertTrue(marker.exists())

    def test_interruption_preserves_marker_until_explicit_recovery(self):
        with mock.patch('provider_key_receiver.os.link', side_effect=OSError('fixture')):
            with self.assertRaises(ReceiverError):
                install(io.BytesIO(b'synthetic-key'), **self.identity)
        self.assertTrue((self.path / ('.asb-key-' + self.token + '.json')).exists())
        self.assertEqual(recover(**self.identity)['status'], 'TRANSFER_CANCELLED')
        self.assertFalse((self.path / 'provider.key').exists())

    def test_insecure_directory_or_key_input_is_rejected(self):
        self.path.chmod(0o755)
        with self.assertRaises(ReceiverError):
            install(io.BytesIO(b'synthetic-key'), **self.identity)
        self.path.chmod(0o700)
        with self.assertRaises(ReceiverError):
            install(io.BytesIO(b'bad key with spaces'), **self.identity)

    def test_unresolved_docker_mutation_blocks_receiver(self):
        def marker(path):
            if path.endswith('/docker-mutation.json'):
                return object()
            raise FileNotFoundError(path)

        directory_fd = os.open(self.directory, os.O_RDONLY)
        info = SimpleNamespace(st_mode=0o100600, st_uid=0, st_nlink=1)
        with mock.patch('provider_key_receiver._directory', return_value=directory_fd), \
             mock.patch('provider_key_receiver.os.fstat', return_value=info), \
             mock.patch('provider_key_receiver.os.lstat', side_effect=marker), \
             mock.patch('provider_key_receiver.fcntl.flock'):
            with self.assertRaises(ReceiverError):
                _lock_and_check_recovery()

    def test_unfinished_guard_install_blocks_receiver(self):
        def marker(path):
            if path.endswith('/provider-install/activation.json'):
                return object()
            raise FileNotFoundError(path)

        directory_fd = os.open(self.directory, os.O_RDONLY)
        info = SimpleNamespace(st_mode=0o100600, st_uid=0, st_nlink=1)
        with mock.patch('provider_key_receiver._directory', return_value=directory_fd), \
             mock.patch('provider_key_receiver.os.fstat', return_value=info), \
             mock.patch('provider_key_receiver.os.lstat', side_effect=marker), \
             mock.patch('provider_key_receiver.fcntl.flock'):
            with self.assertRaises(ReceiverError):
                _lock_and_check_recovery()

    def test_unresolved_other_transaction_blocks_install_and_recovery(self):
        foreign = self.path / ('.asb-key-' + 'b' * 32 + '.tmp')
        foreign.write_bytes(b'other transaction')
        foreign.chmod(0o600)
        with self.assertRaises(ReceiverError):
            install(io.BytesIO(b'synthetic-key'), **self.identity)
        with self.assertRaises(ReceiverError):
            recover(**self.identity)
        self.assertEqual(foreign.read_bytes(), b'other transaction')


if __name__ == '__main__':
    unittest.main()
