"""Exercise the real pinned legacy source against owned temporary fixtures."""
import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import provider_legacy_backup_guard as builder


class FakeRuntime:
    def __init__(self):
        self.state = {'asb-pilot-api': True, 'asb-pilot-worker': True}
        self.events = []

    def running(self, name):
        return self.state[name]

    def stop(self, name):
        self.events.append(('stop', name))
        self.state[name] = False

    def start(self, name):
        self.events.append(('start', name))
        self.state[name] = True

    def reload_proxy(self):
        self.events.append(('reload', 'proxy'))


class LegacyBackupOverlayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('ASB_LEGACY_BACKUP_SOURCE')
        if not path:
            raise unittest.SkipTest('isolated legacy source not supplied')
        cls.source = Path(path).read_bytes()
        if hashlib.sha256(cls.source).hexdigest() != builder.SOURCE_SHA256:
            raise AssertionError('unexpected legacy source identity')
        cls.namespace = {'__name__': 'isolated_legacy_backup_guard'}
        exec(compile(builder.build_overlay(cls.source), '<isolated>', 'exec'), cls.namespace)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='asb-legacy-backup-test-')
        self.addCleanup(self.tmp.cleanup)
        # macOS /var is a symlink; test a canonical, symlink-free parent path.
        self.root = Path(self.tmp.name).resolve()
        self.state = self.root / 'backup-state'
        self.marker = self.root / 'provider-rotation' / 'recovery.json'
        self.namespace['PROVIDER_ROTATION_RECOVERY_MARKER'] = self.marker
        self.narration_marker = self.root / 'narration-deploy' / 'narration-recovery.json'
        self.namespace['NARRATION_RECOVERY_MARKER'] = self.narration_marker
        self.mutation_marker = self.root / 'provider-rotation' / 'docker-mutation.json'
        self.namespace['DOCKER_MUTATION_MARKER'] = self.mutation_marker
        self.runtime = FakeRuntime()
        self.guard = self.namespace['BackupServiceGuard'](self.state, self.runtime)
        self.error = self.namespace['GuardError']

    def test_absent_marker_preserves_legacy_backup_and_recovery(self):
        result = self.guard.run(verify_idle=lambda: None, backup=lambda: 'ok')
        self.assertEqual(result, 'ok')
        self.assertEqual(self.runtime.events, [('stop', 'asb-pilot-api'), ('stop', 'asb-pilot-worker'),
                                               ('start', 'asb-pilot-worker'), ('start', 'asb-pilot-api'),
                                               ('reload', 'proxy')])
        self.assertFalse((self.state / 'restart-required.json').exists())

    def test_pending_marker_blocks_before_stopping_services(self):
        self.marker.parent.mkdir()
        self.marker.write_text('pending')
        with self.assertRaises(self.error):
            self.guard.run(verify_idle=lambda: self.fail('must not drain'), backup=lambda: self.fail('must not backup'))
        self.assertEqual(self.runtime.events, [])
        self.assertFalse((self.state / 'restart-required.json').exists())

    def test_pending_marker_blocks_old_restart_and_retains_backup_marker(self):
        self.guard._write_marker()
        self.runtime.state = {name: False for name in self.runtime.state}
        self.marker.parent.mkdir()
        self.marker.write_text('pending')
        with self.assertRaises(self.error):
            self.guard.recover()
        self.assertEqual(self.runtime.events, [])
        self.assertTrue((self.state / 'restart-required.json').exists())

    def test_pending_narration_marker_also_blocks_legacy_restart(self):
        self.guard._write_marker()
        self.narration_marker.parent.mkdir()
        self.narration_marker.write_text('pending')
        with self.assertRaises(self.error):
            self.guard.recover()
        self.assertTrue((self.state / 'restart-required.json').exists())
        self.assertEqual(self.runtime.events, [])

    def test_pending_docker_mutation_blocks_backup_and_legacy_restart(self):
        self.mutation_marker.parent.mkdir()
        self.mutation_marker.write_text('pending')
        with self.assertRaises(self.error):
            self.guard.run(verify_idle=lambda: None, backup=lambda: None)
        self.guard._write_marker()
        with self.assertRaises(self.error):
            self.guard.recover()
        self.assertTrue((self.state / 'restart-required.json').exists())
        self.assertEqual(self.runtime.events, [])

    def test_dangling_marker_and_symlink_parent_are_blocked(self):
        self.marker.parent.mkdir()
        self.marker.symlink_to(self.root / 'missing')
        with self.assertRaises(self.error):
            self.guard.recover()
        self.marker.unlink()
        self.marker.parent.rmdir()
        self.marker.parent.symlink_to(self.root / 'missing-parent')
        with self.assertRaises(self.error):
            self.guard.recover()

    def test_backup_lock_and_marker_cooperate(self):
        fd = self.guard._locked()
        try:
            self.marker.parent.mkdir()
            self.marker.write_text('pending')
            competing = self.namespace['BackupServiceGuard'](self.state, self.runtime)
            with self.assertRaises(self.error):
                competing.run(verify_idle=lambda: None, backup=lambda: None)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        with self.assertRaises(self.error):
            self.guard.run(verify_idle=lambda: None, backup=lambda: None)
        self.assertEqual(self.runtime.events, [])

    def test_rejects_changed_source(self):
        with self.assertRaises(ValueError):
            builder.build_overlay(self.source + b'\n')

    def test_fresh_recovery_process_refuses_pending_rotation(self):
        self.guard._write_marker()
        self.marker.parent.mkdir()
        self.marker.write_text('pending')
        # Redirect the absolute marker to the owned fixture, preserving the
        # actual entry point and all other generated legacy code.
        patched = builder.build_overlay(self.source).decode().replace(
            "Path('/var/lib/ai-story-book/provider-rotation/recovery.json')",
            'Path(' + repr(str(self.marker)) + ')', 1).replace(
            "Path('/var/lib/ai-story-book/provider-rotation/docker-mutation.json')",
            'Path(' + repr(str(self.mutation_marker)) + ')', 1).replace(
            "Path('/var/lib/ai-story-book/narration-deploy/narration-recovery.json')",
            'Path(' + repr(str(self.narration_marker)) + ')', 1)
        script = self.root / 'backup_service_guard.py'
        script.write_text(patched)
        result = subprocess.run([sys.executable, str(script), '--recover', '--state-dir', str(self.state)],
                                capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), '{"status": "RECOVERY_FAILED"}')
        self.assertTrue((self.state / 'restart-required.json').exists())
        self.assertEqual(self.runtime.events, [])


if __name__ == '__main__':
    unittest.main()
