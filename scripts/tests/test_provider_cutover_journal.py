import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provider_cutover_journal import JournalError, run_journaled


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'docker-mutation.json'
        self.args = dict(transaction='a' * 32, action='start', container='b' * 64)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, execute=lambda: None, verify=lambda: True):
        return run_journaled(self.root, **self.args, execute=execute, verify=verify)

    def test_success_journal_visible_before_execute_and_removed_after_verified(self):
        def execute():
            self.assertEqual(json.loads(self.path.read_text())['action'], 'start')
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.call(execute=execute)
        self.assertFalse(self.path.exists())

    def test_error_and_unverified_leave_marker_and_prevent_retry(self):
        with self.assertRaises(TimeoutError):
            self.call(execute=lambda: (_ for _ in ()).throw(TimeoutError()))
        original = self.path.read_bytes()
        with self.assertRaises(JournalError):
            self.call()
        self.assertEqual(self.path.read_bytes(), original)
        self.path.unlink()
        with self.assertRaises(JournalError):
            self.call(verify=lambda: False)
        self.assertTrue(self.path.exists())

    def test_keyboard_interrupt_and_symlink(self):
        with self.assertRaises(KeyboardInterrupt):
            self.call(execute=lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertTrue(self.path.exists())
        self.path.unlink()
        target = self.root / 'target'
        target.write_text('unchanged')
        self.path.symlink_to(target)
        with self.assertRaises(JournalError):
            self.call()
        self.assertEqual(target.read_text(), 'unchanged')

    def test_marker_replacement_does_not_get_removed(self):
        def replace():
            os.rename(self.path, self.root / 'original')
            self.path.write_text('other')
            return True
        with self.assertRaises(JournalError):
            self.call(verify=replace)
        self.assertEqual(self.path.read_text(), 'other')

    def test_process_kill_leaves_a_durable_intent(self):
        script = (
            "import os, signal, sys; "
            "from pathlib import Path; "
            "from provider_cutover_journal import run_journaled; "
            "run_journaled(Path(sys.argv[1]), transaction='a'*32, action='start', "
            "container='b'*64, execute=lambda: os.kill(os.getpid(), signal.SIGKILL), "
            "verify=lambda: True)"
        )
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        result = subprocess.run([sys.executable, '-c', script, str(self.root)], env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(self.path.read_text())['container'], 'b' * 64)
        with self.assertRaises(JournalError):
            self.call()

    def test_invalid_identity_no_side_effect(self):
        self.args['container'] = 'not-an-id'
        with self.assertRaises(JournalError):
            self.call()
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
