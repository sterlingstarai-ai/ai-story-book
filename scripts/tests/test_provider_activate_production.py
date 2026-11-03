import hashlib
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import provider_activate_production as prod


@unittest.skipUnless(os.geteuid() == 0, 'requires isolated Linux root fixture')
class ProductionLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.scripts, self.units = root / 'scripts', root / 'systemd'
        self.state, self.backup, self.releases = root / 'state', root / 'backup', root / 'releases'
        self.control = root / 'system.control'
        for path in (self.scripts, self.units, self.backup, self.releases):
            path.mkdir(mode=0o700)
        for path in (self.backup / 'backup.lock', self.releases / '.provider-install.lock'):
            path.touch(mode=0o600)
        for name in ('multi-user.target.wants', 'timers.target.wants'):
            (self.units / name).mkdir(mode=0o755)
        for path, target in prod.PRIOR_LINKS.items():
            (self.units / path).symlink_to(target)
        self.old = b'synthetic legacy guard\n'
        old_path = self.scripts / 'backup_service_guard.py'
        old_path.write_bytes(self.old)
        old_path.chmod(0o644)
        self.files = {name: ('synthetic-' + name).encode() for name in prod.ORDER}
        self.baseline = {'synthetic': 'baseline'}
        self.states = {'synthetic': 'units'}
        self.patches = [
            mock.patch.object(prod, 'SCRIPTS', self.scripts), mock.patch.object(prod, 'SYSTEMD', self.units),
            mock.patch.object(prod, 'STATE', self.state), mock.patch.object(prod, 'BACKUP', self.backup),
            mock.patch.object(prod, 'RELEASES', self.releases), mock.patch.object(prod, 'CONTROL', self.control),
            mock.patch.object(prod, 'BLOCKERS', (root / 'blocker',)),
            mock.patch.object(prod, 'LEGACY_GUARD_SHA', hashlib.sha256(self.old).hexdigest()),
            mock.patch.object(prod, '_verify_systemd_platform'),
            mock.patch.object(prod, 'verify_instance'), mock.patch.object(prod, '_current_identity', return_value=(1, 2)),
            mock.patch.object(prod, '_pin_current'), mock.patch.object(prod, '_read_release', return_value=self.files),
            mock.patch.object(prod, '_baseline', return_value=self.baseline),
            mock.patch.object(prod, '_verify_base_units'),
            mock.patch.object(prod, '_initial_unit_states', return_value=self.states),
            mock.patch.object(prod, '_assert_inactive_units'), mock.patch.object(prod, '_assert_no_jobs'),
            mock.patch.object(prod, '_unit_state', return_value={'LoadState': 'masked', 'ActiveState': 'inactive'}),
            mock.patch.object(prod, '_stop_timer_if_active'),
            mock.patch.object(prod, '_verify_restored_timer', return_value=None), mock.patch.object(prod, '_timer'),
            mock.patch.object(prod.systemd, '_reload'), mock.patch.object(prod.systemd, 'reload_new'),
            mock.patch.object(prod.systemd, 'reload_old'), mock.patch.object(prod.systemd, 'verify_installed_guard_files'),
            mock.patch.object(prod.systemd, 'show', return_value={'LoadState': 'loaded', 'UnitFileState': 'enabled',
                                                                'NeedDaemonReload': 'no'}),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        # Fixture parent is /tmp; real implementation requires root-owned,
        # non-writable ancestors and is independently tested by staging tests.
        def fixture_root(path, *, private):
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(fd)
            if info.st_uid != 0 or (private and (info.st_mode & 0o777) != 0o700):
                os.close(fd)
                raise ValueError()
            return fd
        patch = mock.patch.object(prod, '_root', side_effect=fixture_root)
        patch.start()
        self.addCleanup(patch.stop)

    def install(self, after=None):
        return prod._install(release=self.releases / 'synthetic', ready_sha='1' * 64,
                             transaction='a' * 32, after_replace=after)

    def assert_original(self):
        self.assertEqual((self.scripts / 'backup_service_guard.py').read_bytes(), self.old)
        self.assertEqual((self.scripts / 'backup_service_guard.py').stat().st_mode & 0o777, 0o644)
        for name in prod.ORDER:
            if name == 'scripts/backup_service_guard.py':
                continue
            base = self.scripts if name.startswith('scripts/') else self.units
            self.assertFalse((base / name.split('/', 1)[1]).exists())
        for path, target in prod.PRIOR_LINKS.items():
            self.assertEqual(os.readlink(self.units / path), target)
        self.assertFalse((self.units / prod.ENABLED_DIR / prod.ENABLED_NAME).exists())

    def test_preflight_does_not_create_state_or_change_original_links(self):
        result = prod._preflight(release=self.releases / 'synthetic', ready_sha='1' * 64)
        self.assertEqual(result['status'], 'GUARD_PREFLIGHT_PASSED')
        self.assertFalse(self.state.exists())
        self.assertFalse(self.control.exists())
        prod._timer.assert_not_called()
        self.assert_original()

    def test_missing_shared_lock_is_not_created(self):
        (self.backup / 'backup.lock').unlink()
        with self.assertRaises(prod.ProductionInstallError):
            prod._preflight(release=self.releases / 'synthetic', ready_sha='1' * 64)
        self.assertFalse((self.backup / 'backup.lock').exists())
        self.assertFalse(self.state.exists())

    def test_full_install_preserves_original_and_restores_timer(self):
        result = self.install()
        self.assertEqual(result['status'], 'GUARDS_INSTALLED')
        self.assertFalse((self.state / 'activation.json').exists())
        self.assertEqual(os.readlink(self.units / prod.ENABLED_DIR / prod.ENABLED_NAME), prod.ENABLED_TARGET)
        for path, target in prod.PRIOR_LINKS.items():
            self.assertEqual(os.readlink(self.units / path), target)
        self.assertEqual(prod._timer.call_args_list, [mock.call('stop'), mock.call('start')])
        self.assertTrue((self.state / ('new-verified-' + 'a' * 32 + '.json')).exists())

    def test_sigkill_during_file_replacement_restores_originals_and_links(self):
        pid = os.fork()
        if pid == 0:
            def kill(index, _name):
                if index == 3:
                    os.kill(os.getpid(), signal.SIGKILL)
            try:
                self.install(after=kill)
            finally:
                os._exit(2)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
        self.assertTrue((self.state / 'activation.json').exists())
        for unit in prod._INHIBIT_UNITS:
            self.assertEqual(os.readlink(self.control / unit), '/dev/null')
            self.assertTrue((self.state / prod._mask_record_name(unit, 'a' * 32)).is_file())
        self.assertEqual(prod._recover()['status'], 'GUARDS_RESTORED')
        self.assertFalse(self.control.exists())
        self.assert_original()
        self.assertFalse((self.state / 'activation.json').exists())

    def test_interruption_before_directories_exist_is_recoverable(self):
        original = prod._timer
        original.side_effect = [RuntimeError('synthetic timer failure'), None]
        with self.assertRaises(RuntimeError):
            self.install()
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertTrue((self.state / 'systemd-op.json').exists())
        with self.assertRaises(prod.ProductionInstallError):
            prod._recover()
        self.assertTrue((self.state / 'systemd-op.json').exists())
        self.assert_original()

    def test_crash_during_mask_removal_completes_verified_guard_installation(self):
        pid = os.fork()
        if pid == 0:
            original = prod._remove_owned_masks
            def remove_one_then_die(state_fd, transaction):
                fd = os.open(self.control, os.O_RDONLY | os.O_DIRECTORY)
                os.unlink(prod._INHIBIT_UNITS[0], dir_fd=fd)
                os.fsync(fd)
                os.close(fd)
                os.kill(os.getpid(), signal.SIGKILL)
            prod._remove_owned_masks = remove_one_then_die
            try:
                self.install()
            finally:
                prod._remove_owned_masks = original
                os._exit(2)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertTrue((self.state / ('new-files-verified-' + 'a' * 32 + '.json')).exists())
        self.assertEqual(prod._recover()['status'], 'GUARDS_INSTALLATION_COMPLETED')
        self.assertFalse(self.control.exists())
        self.assertFalse((self.state / 'activation.json').exists())
        self.assertTrue((self.state / ('new-verified-' + 'a' * 32 + '.json')).exists())

    def test_crash_before_mask_identity_record_preserves_unknown_link(self):
        pid = os.fork()
        if pid == 0:
            original = prod.core._write_matching_record
            def crash_on_mask(directory, name, data):
                if name.startswith('mask-'):
                    os.kill(os.getpid(), signal.SIGKILL)
                return original(directory, name, data)
            prod.core._write_matching_record = crash_on_mask
            try:
                self.install()
            finally:
                prod.core._write_matching_record = original
                os._exit(2)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertEqual(os.readlink(self.control / prod._INHIBIT_UNITS[0]), '/dev/null')
        with self.assertRaises(Exception):
            prod._recover()
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertEqual(os.readlink(self.control / prod._INHIBIT_UNITS[0]), '/dev/null')
        self.assertEqual((self.scripts / 'backup_service_guard.py').read_bytes(), self.old)

    def test_every_guard_replacement_boundary_recovers_original(self):
        for stop_at in range(len(prod.ORDER)):
            with self.subTest(stop_at=stop_at):
                nested = ProductionLayoutTests(methodName='test_full_install_preserves_original_and_restores_timer')
                nested.setUp()
                try:
                    def crash(index, _name):
                        if index == stop_at:
                            raise RuntimeError('synthetic interruption')
                    with self.assertRaises(RuntimeError):
                        nested.install(after=crash)
                    self.assertEqual(prod._recover()['status'], 'GUARDS_RESTORED')
                    nested.assert_original()
                    self.assertFalse(nested.control.exists())
                finally:
                    nested.doCleanups()

    def test_unloaded_mask_blocks_before_guard_replacement(self):
        with mock.patch.object(prod, '_unit_state', return_value={'LoadState': 'loaded', 'ActiveState': 'inactive'}):
            with self.assertRaises(prod.ProductionInstallError):
                self.install()
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertEqual((self.scripts / 'backup_service_guard.py').read_bytes(), self.old)
        self.assertEqual(prod._recover()['status'], 'GUARDS_RESTORED')
        self.assert_original()

    def test_unknown_operator_control_directory_blocks_without_changes(self):
        self.control.mkdir(mode=0o755)
        foreign = self.control / 'operator.service'
        foreign.symlink_to('/dev/null')
        with self.assertRaises(prod.ProductionInstallError):
            self.install()
        self.assertEqual(os.readlink(foreign), '/dev/null')
        self.assertEqual((self.scripts / 'backup_service_guard.py').read_bytes(), self.old)
        self.assertFalse((self.state / 'activation.json').exists())

    def test_queued_backup_job_blocks_before_mask_or_file_changes(self):
        with mock.patch.object(prod, '_assert_no_jobs', side_effect=prod.ProductionInstallError('synthetic job')):
            with self.assertRaises(prod.ProductionInstallError):
                self.install()
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertFalse(self.control.exists())
        self.assertEqual((self.scripts / 'backup_service_guard.py').read_bytes(), self.old)

    def test_unexpected_existing_file_blocks_without_replacement(self):
        other = self.scripts / 'narration_deploy_safety.py'
        other.write_bytes(b'user file')
        other.chmod(0o644)
        with self.assertRaises(prod.ProductionInstallError):
            self.install()
        self.assertEqual(other.read_bytes(), b'user file')
        self.assertEqual((self.scripts / 'backup_service_guard.py').read_bytes(), self.old)
        self.assertFalse((self.state / 'activation.json').exists())

    def test_unverified_inhibition_blocks_before_target_state(self):
        with mock.patch.object(prod, '_verify_systemd_platform', side_effect=prod.ProductionInstallError('synthetic')):
            with self.assertRaises(prod.ProductionInstallError):
                self.install()
        self.assertFalse(self.state.exists())
        self.assert_original()


class SystemdPreflightTests(unittest.TestCase):
    def test_platform_requires_257_override_precedence_and_no_target_jobs(self):
        version = SimpleNamespace(returncode=0, stdout=b'systemd 257 (257.13)\n')
        paths = SimpleNamespace(returncode=0, stdout=b'/etc/systemd/system.control\n/etc/systemd/system\n')
        jobs = SimpleNamespace(returncode=0, stdout=b'')
        with mock.patch.object(prod.subprocess, 'run', side_effect=[version, paths, jobs]):
            self.assertIsNone(prod._verify_systemd_platform())
        bad_jobs = SimpleNamespace(returncode=0, stdout=b'42 asb-backup.service start waiting\n')
        with mock.patch.object(prod.subprocess, 'run', side_effect=[version, paths, bad_jobs]):
            with self.assertRaises(prod.ProductionInstallError):
                prod._verify_systemd_platform()
        bad_order = SimpleNamespace(returncode=0, stdout=b'/etc/systemd/system\n/etc/systemd/system.control\n')
        with mock.patch.object(prod.subprocess, 'run', side_effect=[version, bad_order]):
            with self.assertRaises(prod.ProductionInstallError):
                prod._verify_systemd_platform()

    def test_masked_unit_may_have_subset_of_systemd_properties(self):
        unit = 'asb-backup.service'
        output = (f'Id={unit}\nLoadState=masked\nActiveState=inactive\nSubState=dead\n').encode()
        with mock.patch.object(prod.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=output)):
            self.assertEqual(prod._unit_state(unit, allow_masked=True)['LoadState'], 'masked')
            with self.assertRaises(prod.ProductionInstallError):
                prod._unit_state(unit)


if __name__ == '__main__':
    unittest.main()
