import hashlib
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import provider_install_stage as install


def sha(data):
    return hashlib.sha256(data).hexdigest()


class StageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.boot, self.cut, self.target = (self.root / x for x in ('boot', 'cut', 'target'))
        for d in (self.boot, self.cut, self.target):
            d.mkdir(mode=0o700)
        self.boot_hash = self.bundle(self.boot, install.BOOT_FILES)
        self.cut_hash = self.bundle(self.cut, install.CUTOVER_FILES)
        self.name = 'provider-release-' + 'a' * 32

    def bundle(self, base, names):
        files = {}
        for name in names:
            path = base / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            data = ('synthetic ' + name).encode()
            path.write_bytes(data)
            files[name] = sha(data)
        manifest = {'version': 1, 'files': files}
        if base == self.cut:
            manifest.update(created_utc='2026-11-03T00:00:00Z',
                            destination_root='/opt/ai-story-book/current/scripts',
                            expected_previous_sha256={'check_backup_status.py':
                                'f40c28e9e28efa36c85304d5f392dadef444df8131363ed00a600d15cead871d'},
                            guard_manifest_sha256=self.boot_hash, installed=False, production_tested=False)
        raw = json.dumps(manifest, sort_keys=True).encode()
        (base / 'manifest.json').write_bytes(raw)
        return sha(raw)

    def stage(self):
        with patch.object(install, 'BOOT_MANIFEST_SHA256', self.boot_hash):
            return install.stage(boot_directory=str(self.boot), cutover_directory=str(self.cut),
                                 cutover_manifest_sha256=self.cut_hash, destination_parent=str(self.target),
                                 release_name=self.name, _safe_parent=False)

    def test_staging_and_rollback_do_not_touch_neighbors(self):
        other = self.target / 'unrelated'
        other.write_text('keep')
        result = self.stage()
        self.assertEqual(result['status'], 'STAGED_INERT')
        self.assertTrue((self.target / self.name / 'READY').is_file())
        self.assertEqual(install.rollback(destination_parent=str(self.target), release_name=self.name,
                                          ready_sha256=result['ready_sha256'], _safe_parent=False)['status'],
                         'STAGED_RELEASE_REMOVED')
        self.assertEqual(other.read_text(), 'keep')
        self.assertFalse((self.target / self.name).exists())

    def test_changed_source_is_rejected_before_creating_release(self):
        (self.cut / next(iter(install.CUTOVER_FILES))).write_text('changed')
        with self.assertRaises(install.InstallError):
            self.stage()
        self.assertFalse((self.target / self.name).exists())

    def test_existing_release_is_preserved(self):
        path = self.target / self.name
        path.mkdir()
        (path / 'keep').write_text('existing')
        with self.assertRaises(install.InstallError):
            self.stage()
        self.assertEqual((path / 'keep').read_text(), 'existing')

    def test_unexpected_file_blocks_rollback(self):
        result = self.stage()
        extra = self.target / self.name / 'do-not-delete'
        extra.write_text('keep')
        with self.assertRaises(install.InstallError):
            install.rollback(destination_parent=str(self.target), release_name=self.name,
                             ready_sha256=result['ready_sha256'], _safe_parent=False)
        self.assertEqual(extra.read_text(), 'keep')
        self.assertTrue((self.target / self.name / 'READY').exists())

    def test_changed_staged_file_blocks_rollback(self):
        result = self.stage()
        file = self.target / self.name / 'cutover' / next(iter(install.CUTOVER_FILES))
        file.write_text('changed')
        with self.assertRaises(install.InstallError):
            install.rollback(destination_parent=str(self.target), release_name=self.name,
                             ready_sha256=result['ready_sha256'], _safe_parent=False)
        self.assertTrue(file.exists())

    def test_symlink_source_is_rejected(self):
        name = next(iter(install.CUTOVER_FILES))
        path = self.cut / name
        path.unlink()
        path.symlink_to(self.boot / 'manifest.json')
        with self.assertRaises(install.InstallError):
            self.stage()
        self.assertFalse((self.target / self.name).exists())

    def test_interrupted_write_leaves_no_published_ready_marker(self):
        original = install._write
        count = 0

        def fail_second(fd, name, data):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('synthetic interruption')
            original(fd, name, data)

        with patch.object(install, '_write', side_effect=fail_second):
            with self.assertRaises(install.InstallError):
                self.stage()
        self.assertTrue((self.target / self.name).is_dir())
        self.assertFalse((self.target / self.name / 'READY').exists())

    def test_stage_refuses_shared_lock_contention(self):
        lock = self.target / '.provider-install.lock'
        with lock.open('w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(install.InstallError):
                self.stage()
        self.assertFalse((self.target / self.name).exists())

    def test_replaced_directory_never_deletes_outside_release(self):
        result = self.stage()
        release = self.target / self.name
        outside = self.root / 'outside'
        outside.mkdir()
        sentinel = outside / 'scripts'
        sentinel.mkdir()
        original = install.os.link

        def replace_after_validation(src, dst, **kwargs):
            original(src, dst, **kwargs)
            if src == 'READY':
                (release / 'boot').rename(release / 'old-boot')
                (release / 'boot').symlink_to(outside, target_is_directory=True)

        with patch.object(install.os, 'link', side_effect=replace_after_validation):
            with self.assertRaises(install.InstallError):
                install.rollback(destination_parent=str(self.target), release_name=self.name,
                                 ready_sha256=result['ready_sha256'], _safe_parent=False)
        self.assertTrue(sentinel.is_dir())


if __name__ == '__main__':
    unittest.main()
