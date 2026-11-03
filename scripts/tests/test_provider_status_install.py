import hashlib
import os
import signal
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import provider_status_install as installer


class StatusInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # macOS /var is a symlink to /private/var. Use the actual directory so
        # the production no-symlink checks are exercised without weakening them.
        root = Path(self.temp.name).resolve()
        self.active = root / 'scripts'
        self.state = root / 'state'
        self.active.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)
        self.old, self.new = b'old synthetic monitor', b'new synthetic monitor'
        (self.active / installer.NAME).write_bytes(self.old)
        os.chmod(self.active / installer.NAME, 0o644)
        self.patches = [
            mock.patch.object(installer, 'OLD', hashlib.sha256(self.old).hexdigest()),
            mock.patch.object(installer, 'NEW', hashlib.sha256(self.new).hexdigest()),
            # The production installer deliberately requires root. The local
            # fixture is owned by the test user; root ownership itself is also
            # exercised separately in the Linux Docker run.
            mock.patch.object(installer, '_metadata', side_effect=lambda digest: {
                'sha256': digest, 'mode': 0o644, 'uid': os.geteuid(), 'gid': os.getegid()}),
            mock.patch.object(installer, '_source', return_value=self.new),
            mock.patch.object(installer, '_guard_checks'),
            mock.patch.object(installer.production, 'SCRIPTS', self.active),
            mock.patch.object(installer.production, 'STATE', self.state),
            mock.patch.object(installer.production, 'BLOCKERS', ()),
            mock.patch.object(installer.production, 'verify_instance'),
            mock.patch.object(installer.production, '_current_identity', return_value=(10, 20)),
            mock.patch.object(installer.production, '_pin_current'),
            mock.patch.object(installer.production, '_open_locks', return_value=()),
            mock.patch.object(installer.production, '_root', side_effect=lambda path, private: os.open(path, os.O_RDONLY)),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.temp.cleanup)

    def test_preflight_is_read_only(self):
        self.assertEqual(installer.run('preflight')['status'], 'STATUS_PREFLIGHT_PASSED')
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertEqual((self.active / installer.NAME).read_bytes(), self.old)

    def test_success_preserves_old_snapshot(self):
        self.assertEqual(installer.run('execute')['status'], 'STATUS_INSTALLED')
        self.assertEqual((self.active / installer.NAME).read_bytes(), self.new)
        self.assertEqual(next(self.state.glob('status-old-*')).read_bytes(), self.old)
        self.assertFalse((self.state / 'activation.json').exists())

    def test_interrupted_after_replacement_resumes(self):
        def interrupted():
            raise RuntimeError('synthetic crash')
        with self.assertRaises(RuntimeError):
            installer.run('execute', after_replace=interrupted)
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertEqual(installer.run('recover')['status'], 'STATUS_INSTALLED')
        self.assertFalse((self.state / 'activation.json').exists())

    def test_interruption_before_replacement_resumes(self):
        with mock.patch.object(installer, '_replace', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):
                installer.run('execute')
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertEqual(installer.run('recover')['status'], 'STATUS_INSTALLED')

    def test_interruption_after_temp_fsync_resumes(self):
        with mock.patch.object(installer.os, 'replace', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):
                installer.run('execute')
        self.assertTrue(list(self.active.glob('.check_backup_status.py.status-*')))
        self.assertEqual(installer.run('recover')['status'], 'STATUS_INSTALLED')
        self.assertEqual(list(self.active.glob('.check_backup_status.py.status-*')), [])

    @unittest.skipUnless(os.geteuid() == 0, 'production temp ownership requires root')
    def test_sigkill_during_temp_write_resumes(self):
        real_write = installer.core._write_new
        def write_then_kill(fd, name, data, mode):
            if name.startswith('.check_backup_status.py.status-'):
                handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
                os.write(handle, data[:3])
                os.fsync(handle)
                os.close(handle)
                os.kill(os.getpid(), signal.SIGKILL)
            return real_write(fd, name, data, mode)
        pid = os.fork()
        if pid == 0:
            with mock.patch.object(installer.core, '_write_new', side_effect=write_then_kill):
                installer.run('execute')
            os._exit(2)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertEqual(installer.run('recover')['status'], 'STATUS_INSTALLED')
        self.assertEqual((self.active / installer.NAME).read_bytes(), self.new)

    def test_unrelated_temp_contents_block_recovery(self):
        with mock.patch.object(installer, '_replace', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):
                installer.run('execute')
        record = __import__('json').loads((self.state / 'activation.json').read_text())
        path = self.active / ('.check_backup_status.py.status-' + record['transaction'])
        path.write_bytes(b'unrelated')
        os.chmod(path, 0o600)
        with self.assertRaises(installer.StatusInstallError):
            installer.run('recover')
        self.assertEqual(path.read_bytes(), b'unrelated')
        self.assertTrue((self.state / 'activation.json').exists())

    def test_external_change_blocks_recovery(self):
        with mock.patch.object(installer, '_replace', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):
                installer.run('execute')
        (self.active / installer.NAME).write_bytes(b'external')
        with self.assertRaises(installer.StatusInstallError):
            installer.run('recover')
        self.assertEqual((self.active / installer.NAME).read_bytes(), b'external')
        self.assertTrue((self.state / 'activation.json').exists())

    def test_symlink_target_is_rejected(self):
        (self.active / installer.NAME).unlink()
        (self.active / installer.NAME).symlink_to('/etc/passwd')
        with self.assertRaises(OSError):
            installer.run('preflight')


if __name__ == '__main__':
    unittest.main()
