"""No provider calls, credentials or production resources are used here."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('key_receiver_fixture', ROOT / 'scripts/provider_key_receiver_fixture.py')
receiver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receiver)
FAKE = b'synthetic-fixture-only-key'


class ReceiverFixtureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='asb-key-receiver-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(os.path.realpath(self.temp.name))
        self.directory.chmod(0o700)

    def install(self, value=FAKE, **overrides):
        args = {'directory': str(self.directory), 'filename': 'provider.key',
                'expected_uid': os.geteuid(), 'expected_gid': os.getegid()}
        args.update(overrides)
        receiver.install_from_stream(BytesIO(value), **args)

    def test_private_file_and_cli_have_no_secret_output(self):
        command = [sys.executable, str(ROOT / 'scripts/provider_key_receiver_fixture.py'),
                   '--synthetic-fixture', '--directory', str(self.directory)]
        result = subprocess.run(command, input=FAKE + b'\n', capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(FAKE, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'SYNTHETIC_FIXTURE_WRITTEN')
        path = self.directory / 'provider.key'
        self.assertEqual(path.read_bytes(), FAKE)
        self.assertEqual(path.stat().st_uid, os.geteuid())
        self.assertEqual(path.stat().st_gid, os.getegid())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in self.directory.iterdir()], ['provider.key'])

    def test_cli_refuses_nonfixture_input(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/provider_key_receiver_fixture.py'),
            '--synthetic-fixture', '--directory', str(self.directory)], input=b'not-a-fixture',
            capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b'not-a-fixture', result.stdout + result.stderr)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_existing_file_or_symlink_is_never_replaced(self):
        target = self.directory / 'provider.key'
        target.write_bytes(b'keep-me')
        with self.assertRaises(receiver.ReceiverError):
            self.install()
        self.assertEqual(target.read_bytes(), b'keep-me')
        target.unlink()
        target.symlink_to(self.directory / 'missing')
        with self.assertRaises(receiver.ReceiverError):
            self.install()
        self.assertTrue(target.is_symlink())
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_directory_symlinks_traversal_and_permissions_are_rejected(self):
        link = self.directory / 'link'
        link.symlink_to(self.directory, target_is_directory=True)
        for directory in (str(link), str(self.directory / '..'), 'relative/path'):
            with self.assertRaises(receiver.ReceiverError):
                self.install(directory=directory)
        self.directory.chmod(0o750)
        with self.assertRaises(receiver.ReceiverError):
            self.install()
        self.assertFalse((self.directory / 'provider.key').exists())

    def test_wrong_owner_name_and_invalid_input_fail_without_disclosure(self):
        for kwargs in ({'expected_uid': os.geteuid() + 1}, {'expected_gid': os.getegid() + 1},
                       {'filename': '../provider.key'}):
            with self.assertRaises(receiver.ReceiverError):
                self.install(**kwargs)
        for value in (b'', b'contains\nnewline', b'contains space', b'\xff', b'x' * 4097):
            with self.assertRaises(receiver.ReceiverError) as error:
                self.install(value)
            readable = value.decode('ascii', errors='ignore')
            if readable:
                self.assertNotIn(readable, str(error.exception))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_write_and_fsync_failures_never_report_success(self):
        real_sync = os.fsync
        for fail_on in (1, 2, 3):
            count = [0]
            def failing_sync(fd):
                count[0] += 1
                if count[0] == fail_on:
                    raise OSError('injected failure')
                return real_sync(fd)
            with mock.patch.object(receiver.os, 'fsync', side_effect=failing_sync):
                with self.assertRaises(receiver.ReceiverError):
                    self.install()
            self.assertEqual(list(self.directory.iterdir()), [])
        with mock.patch.object(receiver.os, 'write', side_effect=OSError('injected failure')):
            with self.assertRaises(receiver.ReceiverError):
                self.install()
        self.assertEqual(list(self.directory.iterdir()), [])
        with mock.patch.object(receiver.os, 'fchmod', side_effect=OSError('injected failure')):
            with self.assertRaises(receiver.ReceiverError):
                self.install()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_restrictive_umask_keeps_owner_read_permission(self):
        previous = os.umask(0o777)
        try:
            self.install()
        finally:
            os.umask(previous)
        self.assertEqual((self.directory / 'provider.key').stat().st_mode & 0o777, 0o600)

    def test_competing_publishers_never_overwrite(self):
        values = [b'synthetic-fixture-first', b'synthetic-fixture-second']
        def publish(value):
            try:
                self.install(value)
                return True
            except receiver.ReceiverError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, values))
        self.assertEqual(results.count(True), 1)
        self.assertIn((self.directory / 'provider.key').read_bytes(), values)
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_interrupted_publish_is_complete_but_retry_stays_blocked(self):
        program = '''import io, os, stat, sys
import provider_key_receiver_fixture as r
old = os.fsync
def crash(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode): os._exit(79)
    return old(fd)
r.os.fsync = crash
r.install_from_stream(io.BytesIO(b"synthetic-fixture-crash"), directory=sys.argv[1],
                      filename="provider.key", expected_uid=os.geteuid(), expected_gid=os.getegid())
'''
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(ROOT / 'scripts')}
        process = subprocess.run([sys.executable, '-c', program, str(self.directory)], env=env,
                                 capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 79)
        self.assertEqual((self.directory / 'provider.key').read_bytes(), b'synthetic-fixture-crash')
        with self.assertRaises(receiver.ReceiverError):
            self.install()
        self.assertEqual((self.directory / 'provider.key').read_bytes(), b'synthetic-fixture-crash')


if __name__ == '__main__':
    unittest.main()
