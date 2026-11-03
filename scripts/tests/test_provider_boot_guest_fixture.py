import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'provider_boot_guest_fixture.py'
SPEC = importlib.util.spec_from_file_location('provider_boot_guest_fixture', PATH)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


class BootFixtureIdentityTest(unittest.TestCase):
    token = 'a' * 32
    instance = '123456'

    @patch.object(fixture.os, 'geteuid', return_value=0)
    @patch.object(fixture, 'run')
    @patch.object(fixture, 'metadata')
    def test_accepts_only_exact_owned_vm(self, metadata, run, _uid):
        run.side_effect = ['systemd', '27.0']
        metadata.side_effect = [self.instance, 'asb-boot-fixture-' + self.token[:16], self.token]
        fixture.assert_fixture(self.token, self.instance)
        self.assertEqual(metadata.call_count, 3)

    @patch.object(fixture.os, 'geteuid', return_value=0)
    @patch.object(fixture, 'run', return_value='systemd')
    @patch.object(fixture, 'metadata')
    def test_rejects_other_vm_before_docker(self, metadata, run, _uid):
        metadata.return_value = '999'
        with self.assertRaises(fixture.FixtureError):
            fixture.assert_fixture(self.token, self.instance)
        self.assertEqual(run.call_count, 1)

    @patch.object(fixture.os, 'geteuid', return_value=0)
    @patch.object(fixture, 'run', return_value='init')
    @patch.object(fixture, 'metadata')
    def test_requires_real_systemd(self, metadata, _run, _uid):
        with self.assertRaises(fixture.FixtureError):
            fixture.assert_fixture(self.token, self.instance)
        metadata.assert_not_called()

    @patch.object(fixture, 'assert_fixture', side_effect=fixture.FixtureError('not ours'))
    @patch.object(fixture, 'verify_package')
    def test_never_reads_package_or_mutates_before_identity(self, package, _guard):
        with self.assertRaises(fixture.FixtureError):
            fixture.prepare(self.token, self.instance, '/none', '/none', 'sha256:' + 'a' * 64)
        package.assert_not_called()


if __name__ == '__main__':
    unittest.main()
