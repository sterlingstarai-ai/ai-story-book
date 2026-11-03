import hashlib
import os
from contextlib import nullcontext
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

from provider_key_transfer import TransferError, _owned_master, _transfer_on_owned_master as transfer, transfer as orchestrate


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        self.path = str(Path(self.temp.name).resolve() / 'control')
        self.socket.bind(self.path)
        self.known_hosts = Path(self.temp.name).resolve() / 'known_hosts'
        self.known_hosts.write_text('compute.123456 ssh-ed25519 synthetic-fixture\n')
        self.known_hosts.chmod(0o600)
        self.source = b'print("receiver fixture")'
        self.args = {'control_socket': self.path, 'port': 12345, 'instance_id': '123456',
                     'transaction_id': 'a' * 32, 'receiver_source': self.source,
                     'receiver_sha256': hashlib.sha256(self.source).hexdigest(),
                     'known_hosts_file': str(self.known_hosts)}

    def test_secret_is_only_provided_as_receiver_stdin(self):
        outcomes = [subprocess.CompletedProcess([], 0, b''),
                    subprocess.CompletedProcess([], 0, b'123456\n'),
                    subprocess.CompletedProcess([], 0, b'synthetic-key\n'),
                    subprocess.CompletedProcess([], 0, b'{"status":"KEY_FILE_INSTALLED","recovery_required":false}')]
        with mock.patch('provider_key_transfer.subprocess.run', side_effect=outcomes) as run:
            self.assertEqual(transfer(**self.args)['status'], 'KEY_FILE_INSTALLED')
        self.assertEqual(run.call_count, 4)
        for call in run.call_args_list:
            self.assertNotIn('synthetic-key', repr(call.args))
            self.assertNotIn('synthetic-key', repr({k: v for k, v in call.kwargs.items() if k != 'input'}))
        self.assertEqual(run.call_args_list[-1].kwargs['input'], b'synthetic-key\n')
        self.assertEqual(run.call_args_list[2].kwargs['timeout'], 180)
        self.assertIn('StrictHostKeyChecking=yes', run.call_args_list[-1].args[0])
        self.assertIn('HostKeyAlias=compute.123456', run.call_args_list[-1].args[0])

    def test_wrong_instance_never_reads_keychain(self):
        outcomes = [subprocess.CompletedProcess([], 0, b''), subprocess.CompletedProcess([], 0, b'999999\n')]
        with mock.patch('provider_key_transfer.subprocess.run', side_effect=outcomes) as run:
            with self.assertRaises(TransferError):
                transfer(**self.args)
        self.assertEqual(run.call_count, 2)

    def test_recovery_does_not_read_keychain(self):
        outcomes = [subprocess.CompletedProcess([], 0, b''), subprocess.CompletedProcess([], 0, b'123456\n'),
                    subprocess.CompletedProcess([], 0, b'{"status":"TRANSFER_CANCELLED","recovery_required":false}')]
        with mock.patch('provider_key_transfer.subprocess.run', side_effect=outcomes) as run:
            self.assertEqual(transfer(**self.args, recover=True)['status'], 'TRANSFER_CANCELLED')
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args_list[-1].kwargs['input'], b'')

    def test_remote_failure_does_not_disclose_key_or_assume_transfer_failed(self):
        outcomes = [subprocess.CompletedProcess([], 0, b''),
                    subprocess.CompletedProcess([], 0, b'123456\n'),
                    subprocess.CompletedProcess([], 0, b'synthetic-key\n'),
                    subprocess.TimeoutExpired('ssh', 90, output=b'synthetic-key')]
        with mock.patch('provider_key_transfer.subprocess.run', side_effect=outcomes):
            with self.assertRaises(TransferError) as error:
                transfer(**self.args)
        self.assertNotIn('synthetic-key', str(error.exception))
        self.assertIn('not confirmed', str(error.exception))

    def test_keychain_timeout_never_invokes_receiver(self):
        outcomes = [subprocess.CompletedProcess([], 0, b''),
                    subprocess.CompletedProcess([], 0, b'123456\n'),
                    subprocess.TimeoutExpired('security', 180)]
        with mock.patch('provider_key_transfer.subprocess.run', side_effect=outcomes) as run:
            with self.assertRaises(TransferError):
                transfer(**self.args)
        self.assertEqual(run.call_count, 3)

    def test_replaced_control_socket_blocks_delivery(self):
        def run(args, **_kwargs):
            if args[0] == 'security':
                self.socket.close()
                os.unlink(self.path)
                return subprocess.CompletedProcess([], 0, b'synthetic-key\n')
            if '-O' in args:
                return subprocess.CompletedProcess([], 0, b'')
            return subprocess.CompletedProcess([], 0, b'123456\n')
        with mock.patch('provider_key_transfer.subprocess.run', side_effect=run):
            with self.assertRaises(TransferError):
                transfer(**self.args)

    def test_owned_master_uses_private_snapshot_and_strict_host_pin(self):
        private = Path(self.temp.name).resolve() / 'fixture-key'
        private.write_text('synthetic private key')
        private.chmod(0o600)
        sockets = []
        commands = []

        class Process:
            def poll(self):
                return None

            def terminate(self):
                for item in sockets:
                    item.close()

            def wait(self, **_kwargs):
                return 0

        def start(command, **_kwargs):
            commands.append(command)
            control = command[command.index('-S') + 1]
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(control)
            sockets.append(sock)
            return Process()

        with mock.patch('provider_key_transfer.subprocess.Popen', side_effect=start), \
             mock.patch('provider_key_transfer.subprocess.run', return_value=subprocess.CompletedProcess([], 0)):
            with _owned_master(port=12345, instance_id='123456', known_hosts_file=str(self.known_hosts),
                               identity_file=str(private)) as (control, snapshot):
                self.assertTrue(Path(control).exists())
                self.assertEqual(Path(snapshot).read_bytes(), self.known_hosts.read_bytes())
                self.assertIn('StrictHostKeyChecking=yes', commands[0])
                self.assertIn('HostKeyAlias=compute.123456', commands[0])
                self.assertIn('UserKnownHostsFile=' + snapshot, commands[0])

    def test_transfer_waits_for_confirmed_temporary_identity_cleanup(self):
        args = dict(self.args)
        args.pop('control_socket')
        args['identity_file'] = '/synthetic/key'
        with mock.patch('provider_key_transfer._owned_master', return_value=nullcontext((self.path, str(self.known_hosts)))), \
             mock.patch('provider_key_transfer._transfer_on_owned_master') as send:
            with self.assertRaises(TransferError):
                orchestrate(**args, on_master_ready=lambda: False)
            send.assert_not_called()
            send.return_value = {'status': 'KEY_FILE_INSTALLED', 'recovery_required': False}
            self.assertEqual(orchestrate(**args, on_master_ready=lambda: True)['status'], 'KEY_FILE_INSTALLED')
            send.assert_called_once()


if __name__ == '__main__':
    unittest.main()
