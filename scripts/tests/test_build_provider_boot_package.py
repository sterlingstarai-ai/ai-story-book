import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from build_provider_boot_package import PackageError, build_package, rebuild_from_verified_overlay


class BootPackageTests(unittest.TestCase):
    def test_package_is_private_pinned_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve() / 'package'
            with mock.patch('build_provider_boot_package._private_source', side_effect=[b'backup', b'privacy']), \
                 mock.patch('build_provider_boot_package.build_overlay', return_value=b'# synthetic guard\n'):
                manifest = build_package(backup_source='/synthetic/backup', privacy_source='/synthetic/privacy',
                                         output=target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertFalse(manifest['installed'])
            self.assertFalse(manifest['boot_verified'])
            self.assertEqual(json.loads((target / 'manifest.json').read_bytes()), manifest)
            for name, expected in manifest['files'].items():
                path = target / name
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
            with mock.patch('build_provider_boot_package._private_source', side_effect=[b'backup', b'privacy']), \
                 mock.patch('build_provider_boot_package.build_overlay', return_value=b'# synthetic guard\n'):
                with self.assertRaises(PackageError):
                    build_package(backup_source='/synthetic/backup', privacy_source='/synthetic/privacy', output=target)

    def test_rebuild_accepts_only_pinned_overlay_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve() / 'package'
            with self.assertRaises(PackageError):
                rebuild_from_verified_overlay(backup_overlay='/backup', overlay_sha256='0' * 64,
                                              privacy_source='/privacy', output=target)
            with mock.patch('build_provider_boot_package._private_source',
                            side_effect=[b'# synthetic overlay\n', b'privacy']):
                manifest = rebuild_from_verified_overlay(
                    backup_overlay='/backup',
                    overlay_sha256='d5a8f2b2e5ce6f4b0524429300186eed8068ecaf35535f1b8c30e41df36b7ba8',
                    privacy_source='/privacy', output=target)
            self.assertEqual(manifest['files']['scripts/backup_service_guard.py'],
                             hashlib.sha256(b'# synthetic overlay\n').hexdigest())

    def test_private_source_symlink_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'source'
            source.write_bytes(b'synthetic')
            source.chmod(0o600)
            link = root / 'link'
            os.symlink(source, link)
            with self.assertRaises(PackageError):
                build_package(backup_source=link, privacy_source=source, output=root / 'package')


if __name__ == '__main__':
    unittest.main()
