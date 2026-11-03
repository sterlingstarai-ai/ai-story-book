import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provider_cutover_production_guards as guards


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        hashes = {}
        for rel in guards.GUARD_HASHES:
            dest = self.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = ("owned test fixture " + rel).encode()
            dest.write_bytes(data)
            dest.chmod(0o600)
            hashes[rel] = hashlib.sha256(data).hexdigest()
        self.hashes = patch.dict(guards.GUARD_HASHES, hashes, clear=True)
        self.hashes.start()

    def tearDown(self):
        self.hashes.stop()
        self.tmp.cleanup()

    def verify(self):
        return guards.verify_installed_guard_files(scripts_dir=self.root / 'scripts',
                                                    systemd_dir=self.root / 'systemd', uid=os.geteuid())

    def test_exact_hashes_and_metadata(self):
        self.assertTrue(self.verify())
        p = self.root / 'scripts/provider_recovery_interlock.py'
        p.write_bytes(p.read_bytes() + b'\n')
        with self.assertRaises(guards.GuardError):
            self.verify()

    def test_symlink_and_group_write_rejected(self):
        p = self.root / 'scripts/provider_recovery_interlock.py'
        original = p.read_bytes()
        p.unlink()
        target = self.root / 'other'
        target.write_bytes(original)
        p.symlink_to(target)
        with self.assertRaises(guards.GuardError):
            self.verify()
        p.unlink()
        p.write_bytes(original)
        p.chmod(0o620)
        with self.assertRaises(guards.GuardError):
            self.verify()

    def test_systemd_state_and_unknown_dropin_rejected(self):
        unit = 'asb-provider-rotation-quarantine.service'
        def service(name, dropin):
            return {'LoadState': 'loaded', 'NeedDaemonReload': 'no', 'UnitFileState': 'enabled',
                    'FragmentPath': '/etc/systemd/system/' + name, 'KillMode': 'control-group',
                    'Requires': 'docker.service',
                    'DropInPaths': f'/etc/systemd/system/{name}.d/{dropin}',
                    'After': unit + ' docker.service', 'Wants': unit,
                    'ExecStart': '{ argv[]=/usr/bin/python3 /opt/ai-story-book/current/scripts/provider_recovery_interlock.py ; }'}
        units = {unit: {'LoadState': 'loaded', 'UnitFileState': 'enabled',
                        'FragmentPath': '/etc/systemd/system/' + unit, 'NeedDaemonReload': 'no',
                        'KillMode': 'control-group', 'Requires': 'docker.service', 'After': 'docker.service',
                        'ExecStart': '{ argv[]=/usr/bin/python3 /opt/ai-story-book/current/scripts/provider_rotation_quarantine.py --recover ; }'},
                 'asb-privacy-deploy-recover.service': service('asb-privacy-deploy-recover.service', 'provider-interlock.conf'),
                 'asb-backup-recover.service': service('asb-backup-recover.service', 'provider-order.conf')}
        units['asb-backup-recover.service']['ExecStart'] = ('{ argv[]=/usr/bin/python3 /opt/ai-story-book/current/scripts/backup_service_guard.py --recover --state-dir /var/lib/ai-story-book/backup-state ; }')
        self.assertTrue(guards.verify_loaded_units(units.__getitem__))
        units['asb-privacy-deploy-recover.service']['DropInPaths'] += ' /tmp/unknown.conf'
        with self.assertRaises(guards.GuardError):
            guards.verify_loaded_units(units.__getitem__)


if __name__ == '__main__':
    unittest.main()
