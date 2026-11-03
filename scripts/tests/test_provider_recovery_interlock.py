import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from provider_recovery_interlock import InterlockError, run_guarded


class RecoveryInterlockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.state = root / 'backup'
        self.marker = root / 'provider'
        self.state.mkdir(mode=0o700)
        self.marker.mkdir(mode=0o700)

    def run_command(self, code):
        return run_guarded(state_dir=self.state, marker_dir=self.marker,
                           command=[sys.executable, '-c', code], timeout=10)

    def test_child_runs_only_while_shared_lock_is_held(self):
        code = ("import fcntl,os,sys; f=os.open(sys.argv[1],os.O_RDWR); "
                "\ntry: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
                "\nexcept BlockingIOError: sys.exit(0)"
                "\nsys.exit(1)")
        self.assertTrue(run_guarded(state_dir=self.state, marker_dir=self.marker,
                                   command=[sys.executable, '-c', code, str(self.state / 'backup.lock')], timeout=10))

    def test_marker_and_busy_lock_block_recovery(self):
        touched = self.marker / 'child-ran'
        (self.marker / 'recovery.json').write_text('{}')
        with self.assertRaises(InterlockError):
            self.run_command(f"from pathlib import Path; Path({str(touched)!r}).touch()")
        self.assertFalse(touched.exists())
        (self.marker / 'recovery.json').unlink()
        (self.marker / 'docker-mutation.json').write_text('{}')
        with self.assertRaises(InterlockError):
            self.run_command(f"from pathlib import Path; Path({str(touched)!r}).touch()")
        self.assertFalse(touched.exists())
        (self.marker / 'docker-mutation.json').unlink()
        fd = os.open(self.state / 'backup.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(InterlockError):
                self.run_command('pass')
        finally:
            os.close(fd)

    def test_killing_wrapper_does_not_release_live_child_lock(self):
        ready = self.marker / 'child-ready'
        child = ("from pathlib import Path; import time; "
                 f"Path({str(ready)!r}).touch(); time.sleep(1.5)")
        outer = ("from provider_recovery_interlock import run_guarded; "
                 f"run_guarded(state_dir={str(self.state)!r},marker_dir={str(self.marker)!r},"
                 f"command=[{sys.executable!r},'-c',{child!r}],timeout=10)")
        process = subprocess.Popen([sys.executable, '-c', outer], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists())
            process.kill()
            process.wait(timeout=5)
            fd = os.open(self.state / 'backup.lock', os.O_RDWR)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
            time.sleep(1.7)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def test_source_version_is_pinned_before_recovery_starts(self):
        script = self.marker / 'legacy.py'
        touched = self.marker / 'child-ran'
        script.write_text(f'from pathlib import Path; Path({str(touched)!r}).touch()')
        command = [sys.executable, str(script), '--recover']
        with self.assertRaises(InterlockError):
            run_guarded(state_dir=self.state, marker_dir=self.marker, command=command,
                        timeout=10, source_sha256='0' * 64)
        self.assertFalse(touched.exists())
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        self.assertTrue(run_guarded(state_dir=self.state, marker_dir=self.marker, command=command,
                                    timeout=10, source_sha256=digest))
        self.assertTrue(touched.exists())

    def test_verified_source_bytes_are_used_even_if_path_changes(self):
        script = self.marker / 'legacy.py'
        result = self.marker / 'result'
        script.write_text(f'from pathlib import Path; Path({str(result)!r}).write_text("verified")')
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        real_run = subprocess.run

        def replace_then_run(*args, **kwargs):
            script.write_text(f'from pathlib import Path; Path({str(result)!r}).write_text("replaced")')
            return real_run(*args, **kwargs)

        with mock.patch('provider_recovery_interlock.subprocess.run', side_effect=replace_then_run):
            self.assertTrue(run_guarded(state_dir=self.state, marker_dir=self.marker,
                                        command=[sys.executable, str(script), '--recover'], timeout=10,
                                        source_sha256=digest))
        self.assertEqual(result.read_text(), 'verified')


if __name__ == '__main__':
    unittest.main()
