import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'run_provider_boot_vm_fixture.py'
SPEC = importlib.util.spec_from_file_location('provider_boot_vm_runner', PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class BootVMRunnerTest(unittest.TestCase):
    token = 'a' * 32
    name = 'asb-boot-fixture-' + token[:16]
    instance = {'name': name, 'id': '123', 'labels': {'asb-fixture-owner': token},
                'disks': [{'boot': True, 'autoDelete': True, 'source': '/disks/' + name}]}
    disk = {'name': name, 'id': '456', 'users': ['/instances/' + name]}

    def test_startup_waits_until_quarantine_unit_has_really_finished(self):
        startup = runner.startup(b'synthetic', '0' * 64, self.token, test_mutation=True)
        waiting = startup.split('  complete=false\n', 1)[1].split('  if result=', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            counter = root / 'counter'
            fake = root / 'systemctl'
            fake.write_text('#!/bin/sh\n'
                            'case "$*" in\n'
                            '  *ActiveState*)\n'
                            '    if [ ! -e "$ASB_FAKE_COUNTER" ]; then touch "$ASB_FAKE_COUNTER"; printf activating;'
                            ' else printf failed; fi;;\n'
                            '  *ExecMainStartTimestampMonotonic*) printf 1;;\n'
                            'esac\n')
            fake.chmod(0o700)
            sleeper = root / 'sleep'
            sleeper.write_text('#!/bin/sh\nexit 0\n')
            sleeper.chmod(0o700)
            env = dict(__import__('os').environ, PATH=str(root) + ':' + __import__('os').environ['PATH'],
                       ASB_FAKE_COUNTER=str(counter))
            result = subprocess.run(['bash', '-c', 'set -e\ncomplete=false\n' + waiting + '\nprintf PASS'],
                                    env=env, capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, 'PASS')
            self.assertTrue(counter.exists())

    def test_exact_owner_and_boot_disk_required(self):
        self.assertEqual(runner.own_instance(self.instance, self.name, self.token), '123')
        with self.assertRaises(runner.FixtureError):
            runner.own_instance(self.instance, self.name, 'b' * 32)
        changed = {**self.instance, 'disks': [{**self.instance['disks'][0], 'autoDelete': False}]}
        with self.assertRaises(runner.FixtureError):
            runner.own_instance(changed, self.name, self.token)

    def test_successful_fixture_deletes_owned_instance_and_checks_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'payload'
            payload.write_bytes(b'synthetic')
            payload.chmod(0o600)
            responses = iter([None, None, self.instance, self.disk, self.instance, self.disk, None, None])
            calls = []

            def fake_gcloud(*args, **kwargs):
                calls.append(args)
                return 'ASB_RESULT=BOOT_QUARANTINE_VERIFIED_ON_FIXTURE' if 'get-serial-port-output' in args else ''

            with patch.object(runner, 'JOURNAL', root / 'journal'), patch.object(runner, 'LOCK', root / 'lock'), \
                 patch.object(runner.secrets, 'token_hex', return_value=self.token), \
                 patch.object(runner, 'resource', side_effect=lambda *_: next(responses)), \
                 patch.object(runner, 'gcloud', side_effect=fake_gcloud):
                result = runner.run_fixture(payload, hashlib.sha256(b'synthetic').hexdigest())
            self.assertTrue(result['cleanup_confirmed'])
            self.assertEqual(result['disk_id'], '456')
            self.assertEqual(sum('create' in x for x in calls), 1)
            self.assertEqual(sum('delete' in x for x in calls), 1)
            self.assertTrue((root / 'journal').is_file())

    def test_owned_orphan_disk_is_deleted_by_recorded_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'payload'
            payload.write_bytes(b'synthetic')
            payload.chmod(0o600)
            orphan = {**self.disk, 'users': []}
            responses = iter([None, None, self.instance, self.disk, self.instance,
                              self.disk, None, orphan, None])
            calls = []

            def fake_gcloud(*args, **_kwargs):
                calls.append(args)
                return 'ASB_RESULT=BOOT_QUARANTINE_VERIFIED_ON_FIXTURE' if 'get-serial-port-output' in args else ''

            with patch.object(runner, 'JOURNAL', root / 'journal'), patch.object(runner, 'LOCK', root / 'lock'), \
                 patch.object(runner.secrets, 'token_hex', return_value=self.token), \
                 patch.object(runner, 'resource', side_effect=lambda *_: next(responses)), \
                 patch.object(runner, 'gcloud', side_effect=fake_gcloud):
                result = runner.run_fixture(payload, hashlib.sha256(b'synthetic').hexdigest())
            self.assertTrue(result['cleanup_confirmed'])
            self.assertTrue(any('disks' in call and 'delete' in call for call in calls))

    def test_uncertain_creation_never_claims_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'payload'
            payload.write_bytes(b'synthetic')
            payload.chmod(0o600)
            def timed_out(*_args, **_kwargs):
                raise subprocess.TimeoutExpired('gcloud', 1)
            with patch.object(runner, 'JOURNAL', root / 'journal'), patch.object(runner, 'LOCK', root / 'lock'), \
                 patch.object(runner.secrets, 'token_hex', return_value=self.token), \
                 patch.object(runner, 'resource', return_value=None), patch.object(runner, 'gcloud', side_effect=timed_out), \
                 patch.object(runner.time, 'monotonic', side_effect=[0, 181]):
                with self.assertRaises(runner.FixtureError):
                    runner.run_fixture(payload, hashlib.sha256(b'synthetic').hexdigest())
            import json
            record = json.loads((root / 'journal').read_text())
            self.assertFalse(record['cleanup_confirmed'])
            self.assertEqual(record['result'], 'CREATE_RESPONSE_UNCERTAIN')
            self.assertTrue(record['vm_absent_observed'])
            self.assertTrue(record['disk_absent_observed'])

    def test_retest_requires_confirmed_prior_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'payload'
            payload.write_bytes(b'synthetic')
            payload.chmod(0o600)
            prior = root / 'prior'
            prior.write_text('{"cleanup_confirmed": false}')
            with patch.object(runner, 'INITIAL_JOURNAL', prior), patch.object(runner, 'JOURNAL', root / 'retest'), \
                 patch.object(runner, 'LOCK', root / 'lock'), patch.object(runner, 'gcloud') as cloud:
                with self.assertRaises(runner.FixtureError):
                    runner.run_fixture(payload, hashlib.sha256(b'synthetic').hexdigest(), retest=True)
                cloud.assert_not_called()

    def test_repaired_retest_requires_both_prior_cleanups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'payload'
            payload.write_bytes(b'synthetic')
            payload.chmod(0o600)
            prior = root / 'prior'
            prior.write_text('{"cleanup_confirmed": true, "vm_absent_observed": true, "disk_absent_observed": true}')
            second = root / 'second'
            second.write_text('{"cleanup_confirmed": false}')
            with patch.object(runner, 'INITIAL_JOURNAL', prior), patch.object(runner, 'RETEST_JOURNAL', second), \
                 patch.object(runner, 'JOURNAL', root / 'repair'), patch.object(runner, 'LOCK', root / 'lock'), \
                 patch.object(runner, 'gcloud') as cloud:
                with self.assertRaises(runner.FixtureError):
                    runner.run_fixture(payload, hashlib.sha256(b'synthetic').hexdigest(),
                                       retest=True, repair_retest=True)
                cloud.assert_not_called()

    def test_existing_journal_blocks_duplicate_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'payload'
            payload.write_bytes(b'synthetic')
            payload.chmod(0o600)
            (root / 'journal').write_text('{}')
            with patch.object(runner, 'JOURNAL', root / 'journal'), patch.object(runner, 'LOCK', root / 'lock'), \
                 patch.object(runner, 'gcloud') as cloud:
                with self.assertRaises(runner.FixtureError):
                    runner.run_fixture(payload, hashlib.sha256(b'synthetic').hexdigest())
                cloud.assert_not_called()


if __name__ == '__main__':
    unittest.main()
