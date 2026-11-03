import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock

from provider_activate_guard import (ActivationError, BOOT_FILES, activate_fixture, recover_fixture,
                                     restore_committed_fixture)


class GuardActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.active, self.staged, self.state = (self.root / name for name in ('active', 'staged', 'state'))
        for directory in (self.active, self.staged, self.state):
            directory.mkdir(mode=0o700)
        self.old, self.new = {}, {}
        self.names = sorted(BOOT_FILES)
        for index, name in enumerate(self.names):
            for base in (self.active, self.staged):
                (base / name).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            data = ('new-' + name).encode()
            (self.staged / name).write_bytes(data)
            (self.staged / name).chmod(0o600)
            self.new[name] = hashlib.sha256(data).hexdigest()
            if index % 2:
                old = ('old-' + name).encode()
                (self.active / name).write_bytes(old)
                (self.active / name).chmod(0o600)
                self.old[name] = {'sha256': hashlib.sha256(old).hexdigest(), 'mode': 0o600,
                                  'uid': os.geteuid(), 'gid': os.getegid()}
            else:
                self.old[name] = None
        self.args = {'active_directory': self.active, 'staged_directory': self.staged,
                     'state_directory': self.state, 'expected_old': self.old, 'expected_new': self.new,
                     'transaction': 'a' * 32}

    def activate(self, reload=lambda _mode, _baseline: True, after=None):
        return activate_fixture(**self.args, reload_and_verify=reload, after_replace=after)

    def recover(self, reload=lambda _mode, _baseline: True):
        return recover_fixture(active_directory=self.active, state_directory=self.state, reload_and_verify=reload)

    def test_complete_activation_and_reload(self):
        calls = []
        result = self.activate(reload=lambda mode, _baseline: calls.append(mode) or True)
        self.assertEqual(result['status'], 'FIXTURE_ACTIVATED')
        self.assertEqual(calls, ['new'])
        self.assertFalse((self.state / 'activation.json').exists())
        self.assertTrue((self.state / ('new-verified-' + 'a' * 32 + '.json')).is_file())
        for name in self.names:
            self.assertEqual(hashlib.sha256((self.active / name).read_bytes()).hexdigest(), self.new[name])

    def test_partial_failure_restores_old_and_absent_files(self):
        def crash(index, _name):
            if index == 2:
                raise RuntimeError('synthetic interruption')
        with self.assertRaises(ActivationError):
            self.activate(after=crash)
        self.assertTrue((self.state / 'activation.json').is_file())
        calls = []
        self.assertEqual(self.recover(reload=lambda mode, _baseline: calls.append(mode) or True)['status'], 'FIXTURE_RECOVERED')
        self.assertEqual(calls, ['old'])
        for name, meta in self.old.items():
            if meta is None:
                self.assertFalse((self.active / name).exists())
            else:
                self.assertEqual(hashlib.sha256((self.active / name).read_bytes()).hexdigest(), meta['sha256'])
        self.assertFalse((self.state / 'activation.json').exists())
        self.assertTrue((self.state / ('recovered-' + 'a' * 32 + '.json')).is_file())

    def test_recovery_after_each_replacement_boundary(self):
        for stop_at in range(len(self.names)):
            with self.subTest(stop_at=stop_at):
                nested = GuardActivationTests(methodName='test_complete_activation_and_reload')
                nested.setUp()
                try:
                    def crash(index, _name):
                        if index == stop_at:
                            raise RuntimeError('synthetic interruption')
                    with self.assertRaises(ActivationError):
                        nested.activate(after=crash)
                    self.assertEqual(nested.recover()['status'], 'FIXTURE_RECOVERED')
                    for name, meta in nested.old.items():
                        target = nested.active / name
                        if meta is None:
                            self.assertFalse(target.exists())
                        else:
                            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), meta['sha256'])
                finally:
                    nested.doCleanups()

    def test_sigkill_before_marker_reuses_exact_snapshot(self):
        payload = {**self.args, 'active_directory': str(self.active), 'staged_directory': str(self.staged),
                   'state_directory': str(self.state)}
        code = ("import json,os,signal,sys; import provider_activate_guard as m; "
                "args=json.load(sys.stdin); original=m._write_new;\n"
                "def stop(directory,name,data,mode):\n"
                " original(directory,name,data,mode)\n"
                " if name.startswith('old-'): os.kill(os.getpid(),signal.SIGKILL)\n"
                "m._write_new=stop; m.activate_fixture(**args,reload_and_verify=lambda *_:True)")
        result = subprocess.run([sys.executable, '-c', code], input=json.dumps(payload), text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, -9)
        self.assertFalse((self.state / 'activation.json').exists())
        self.assertEqual(self.activate()['status'], 'FIXTURE_ACTIVATED')

    def test_sigkill_between_replacements_preserves_recovery_record(self):
        payload = {**self.args, 'active_directory': str(self.active), 'staged_directory': str(self.staged),
                   'state_directory': str(self.state)}
        code = ("import json,os,signal,sys; from provider_activate_guard import activate_fixture; "
                "args=json.load(sys.stdin); "
                "stop=lambda index,name: os.kill(os.getpid(),signal.SIGKILL) if index==2 else None; "
                "activate_fixture(**args,reload_and_verify=lambda *_:True,after_replace=stop)")
        result = subprocess.run([sys.executable, '-c', code], input=json.dumps(payload), text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, -9)
        self.assertTrue((self.state / 'activation.json').is_file())
        self.assertEqual(self.recover()['status'], 'FIXTURE_RECOVERED')
        for name, meta in self.old.items():
            if meta is None:
                self.assertFalse((self.active / name).exists())
            else:
                self.assertEqual(hashlib.sha256((self.active / name).read_bytes()).hexdigest(), meta['sha256'])

    def test_sigkill_between_new_file_link_and_temp_unlink_recovers(self):
        payload = {**self.args, 'active_directory': str(self.active), 'staged_directory': str(self.staged),
                   'state_directory': str(self.state)}
        code = ("import json,os,signal,sys; import provider_activate_guard as m; "
                "args=json.load(sys.stdin); original=os.unlink; "
                "def stop(path,*a,**kw):\n"
                " if str(path).endswith('.activate-'+'a'*32): os.kill(os.getpid(),signal.SIGKILL)\n"
                " return original(path,*a,**kw)\n"
                "os.unlink=stop; m.activate_fixture(**args,reload_and_verify=lambda *_:True)")
        # A compound statement cannot follow a semicolon before `def`.
        code = code.replace('; def stop', '\ndef stop')
        result = subprocess.run([sys.executable, '-c', code], input=json.dumps(payload), text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, -9)
        self.assertTrue((self.state / 'activation.json').is_file())
        self.assertEqual(self.recover()['status'], 'FIXTURE_RECOVERED')
        for name, meta in self.old.items():
            target = self.active / name
            self.assertEqual(target.exists(), meta is not None)

    def test_sigkill_after_restore_temp_write_reuses_exact_owned_temp(self):
        def crash(index, _name):
            if index == 1:
                raise RuntimeError('synthetic interruption')
        with self.assertRaises(ActivationError):
            self.activate(after=crash)
        code = ("import os,signal,sys; import provider_activate_guard as m; original=m._write_new;\n"
                "def stop(directory,name,data,mode):\n"
                " original(directory,name,data,mode)\n"
                " if name.endswith('-restore'): os.kill(os.getpid(),signal.SIGKILL)\n"
                "m._write_new=stop; "
                "m.recover_fixture(active_directory=sys.argv[1],state_directory=sys.argv[2],reload_and_verify=lambda *_:True)")
        result = subprocess.run([sys.executable, '-c', code, str(self.active), str(self.state)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, -9)
        self.assertTrue((self.state / 'activation.json').is_file())
        self.assertEqual(self.recover()['status'], 'FIXTURE_RECOVERED')

    def test_torn_recovery_record_can_resume_without_losing_marker(self):
        def crash(index, _name):
            if index == 1:
                raise RuntimeError('synthetic interruption')
        with self.assertRaises(ActivationError):
            self.activate(after=crash)
        code = ("import os,signal,sys; import provider_activate_guard as m; original=m._write_new;\n"
                "def stop(directory,name,data,mode):\n"
                " if name.startswith('.recovered-'):\n"
                "  f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode,dir_fd=directory);"
                "os.write(f,data[:20]);os.fsync(f);os.close(f);os.kill(os.getpid(),signal.SIGKILL)\n"
                " return original(directory,name,data,mode)\n"
                "m._write_new=stop; "
                "m.recover_fixture(active_directory=sys.argv[1],state_directory=sys.argv[2],reload_and_verify=lambda *_:True)")
        result = subprocess.run([sys.executable, '-c', code, str(self.active), str(self.state)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, -9)
        self.assertTrue((self.state / 'activation.json').is_file())
        self.assertEqual(self.recover()['status'], 'FIXTURE_RECOVERED')

    def test_sigkill_after_restore_record_is_idempotent(self):
        def crash(index, _name):
            if index == 1:
                raise RuntimeError('synthetic interruption')
        with self.assertRaises(ActivationError):
            self.activate(after=crash)
        code = ("import os,signal,sys; import provider_activate_guard as m; original=m._write_matching_record;\n"
                "def stop(directory,name,data):\n"
                " original(directory,name,data)\n"
                " if name.startswith('recovered-'): os.kill(os.getpid(),signal.SIGKILL)\n"
                "m._write_matching_record=stop; "
                "m.recover_fixture(active_directory=sys.argv[1],state_directory=sys.argv[2],reload_and_verify=lambda *_:True)")
        result = subprocess.run([sys.executable, '-c', code, str(self.active), str(self.state)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, -9)
        self.assertTrue((self.state / 'activation.json').is_file())
        self.assertEqual(self.recover()['status'], 'FIXTURE_RECOVERED')
        self.assertFalse((self.state / 'activation.json').exists())

    def test_verified_new_record_does_not_override_pending_recovery(self):
        payload = {**self.args, 'active_directory': str(self.active), 'staged_directory': str(self.staged),
                   'state_directory': str(self.state)}
        code = ("import json,os,signal,sys; import provider_activate_guard as m; "
                "args=json.load(sys.stdin); original=m._write_matching_record;\n"
                "def stop(directory,name,data):\n"
                " original(directory,name,data)\n"
                " if name.startswith('new-verified-'): os.kill(os.getpid(),signal.SIGKILL)\n"
                "m._write_matching_record=stop; m.activate_fixture(**args,reload_and_verify=lambda *_:True)")
        result = subprocess.run([sys.executable, '-c', code], input=json.dumps(payload), text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.assertEqual(result.returncode, -9)
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertTrue((self.state / ('new-verified-' + 'a' * 32 + '.json')).exists())
        self.assertEqual(self.recover()['status'], 'FIXTURE_RECOVERED')
        self.assertTrue((self.state / ('recovered-' + 'a' * 32 + '.json')).exists())

    def test_systemd_baseline_survives_interruption_and_is_used_on_restore(self):
        baseline = {'synthetic-unit': {'LoadState': 'loaded', 'ExecStart': ['old-command']}}
        self.args['systemd_before'] = baseline
        def crash(index, _name):
            if index == 1:
                raise RuntimeError('synthetic interruption')
        with self.assertRaises(ActivationError):
            self.activate(after=crash)
        self.assertEqual(json.loads((self.state / 'activation.json').read_text())['systemd_before'], baseline)
        seen = []
        self.assertEqual(self.recover(reload=lambda mode, previous: seen.append((mode, previous)) or True)['status'],
                         'FIXTURE_RECOVERED')
        self.assertEqual(seen, [('old', baseline)])

    def test_verified_activation_can_restore_original_before_transition(self):
        self.activate()
        result = restore_committed_fixture(active_directory=self.active, state_directory=self.state,
                                           transaction='a' * 32, reload_and_verify=lambda *_: True)
        self.assertEqual(result['status'], 'FIXTURE_RECOVERED')
        for name, old in self.old.items():
            target = self.active / name
            if old is None:
                self.assertFalse(target.exists())
            else:
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), old['sha256'])

    def test_committed_restore_is_blocked_by_new_transition_marker(self):
        self.activate()
        blocker = self.state / 'candidate-owner.json'
        blocker.write_text('{}')
        blocker.chmod(0o600)
        before = {name: (self.active / name).read_bytes() for name in self.names}
        with self.assertRaises(ActivationError):
            restore_committed_fixture(active_directory=self.active, state_directory=self.state,
                                      transaction='a' * 32, reload_and_verify=lambda *_: True)
        self.assertEqual(before, {name: (self.active / name).read_bytes() for name in self.names})
        self.assertFalse((self.state / 'activation.json').exists())

    def test_external_change_blocks_before_any_rollback(self):
        def crash(index, _name):
            if index == 2:
                raise RuntimeError('synthetic interruption')
        with self.assertRaises(ActivationError):
            self.activate(after=crash)
        changed = self.active / self.names[2]
        changed.write_bytes(b'external edit')
        before = {name: (self.active / name).read_bytes() if (self.active / name).exists() else None for name in self.names}
        with self.assertRaises(ActivationError):
            self.recover()
        after = {name: (self.active / name).read_bytes() if (self.active / name).exists() else None for name in self.names}
        self.assertEqual(before, after)
        self.assertTrue((self.state / 'activation.json').exists())

    def test_other_recovery_blocks_before_guard_restoration(self):
        def crash(index, _name):
            if index == 1:
                raise RuntimeError('synthetic interruption')
        with self.assertRaises(ActivationError):
            self.activate(after=crash)
        blocker = self.state / 'docker-mutation.json'
        blocker.write_text('{}')
        blocker.chmod(0o600)
        before = {name: (self.active / name).read_bytes() if (self.active / name).exists() else None for name in self.names}
        with self.assertRaises(ActivationError):
            self.recover()
        after = {name: (self.active / name).read_bytes() if (self.active / name).exists() else None for name in self.names}
        self.assertEqual(before, after)
        self.assertTrue((self.state / 'activation.json').exists())
        blocker.unlink()
        self.assertEqual(self.recover()['status'], 'FIXTURE_RECOVERED')

    def test_failed_reload_retains_marker_and_recovery_is_retryable(self):
        with self.assertRaises(ActivationError):
            self.activate(reload=lambda _mode, _baseline: False)
        with self.assertRaises(ActivationError):
            self.recover(reload=lambda _mode, _baseline: False)
        self.assertTrue((self.state / 'activation.json').exists())
        self.assertEqual(self.recover()['status'], 'FIXTURE_RECOVERED')

    def test_extended_metadata_blocks_before_target_changes(self):
        before = {name: (self.active / name).read_bytes() if (self.active / name).exists() else None for name in self.names}
        with mock.patch('provider_activate_guard.os.listxattr', create=True, return_value=['system.posix_acl_access']):
            with self.assertRaises(ActivationError):
                self.activate()
        after = {name: (self.active / name).read_bytes() if (self.active / name).exists() else None for name in self.names}
        self.assertEqual(before, after)
        self.assertFalse((self.state / 'activation.json').exists())

    def test_input_change_and_prior_recovery_block_mutation(self):
        (self.staged / self.names[0]).write_bytes(b'wrong')
        with self.assertRaises(ActivationError):
            self.activate()
        self.assertFalse((self.state / 'activation.json').exists())
        (self.staged / self.names[0]).write_bytes(('new-' + self.names[0]).encode())
        (self.state / 'docker-mutation.json').write_text('{}')
        (self.state / 'docker-mutation.json').chmod(0o600)
        with self.assertRaises(ActivationError):
            self.activate()
        self.assertFalse((self.state / 'activation.json').exists())


if __name__ == '__main__':
    unittest.main()
