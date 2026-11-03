import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provider_cutover_production_adapter as adapter


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_patch = patch.object(adapter, 'STATE', self.root)
        self.state_patch.start()
        self.item = object.__new__(adapter.ProductionAdapter)
        self.item.ids = {'new_api': 'a' * 64, 'new_worker': 'b' * 64}
        self.item.transaction = 'c' * 32
        self.item.probe_id = 'd' * 64
        self.item.probe_owner = {'test': 'owned'}
        self.item.lock_fd = 1
        self.item.evidence = object()
        self.item.overlay_sha256 = 'e' * 64
        self.events = []
        self.running = False
        def run(args):
            self.events.append(args[0])
            if args[0] == 'start':
                self.running = True
            if args[0] == 'kill':
                self.running = False
        self.item.stage_runtime = SimpleNamespace(_run=run, inspect=lambda _: {'State': {'Running': self.running, 'ExitCode': 0, 'OOMKilled': False, 'Error': ''}},
                                                   remove=lambda _: self.events.append('remove'))

    def tearDown(self):
        self.state_patch.stop()
        self.tmp.cleanup()

    def test_portless_compound_orders_queue_provider_and_owned_removal(self):
        def inside(**_):
            marker = json.loads((self.root / 'docker-mutation.json').read_text())
            self.assertEqual(marker['action'], 'provider-probe')
            self.assertEqual(marker['container'], 'd' * 64)
            self.events.append('queue-and-provider')
        def clear(**_):
            self.events.append('clear-owner')
            return True
        with patch.object(adapter.portless, 'run_inside_owned_probe', side_effect=inside), \
             patch.object(adapter.stage, 'clear_probe_owner_after_compound', side_effect=clear):
            self.item.probe_equivalent_provider('a' * 64)
        self.assertEqual(self.events, ['start', 'queue-and-provider', 'kill', 'remove', 'clear-owner'])
        self.assertIsNone(self.item.probe_id)
        self.assertFalse((self.root / 'docker-mutation.json').exists())

    def test_unknown_provider_completion_leaves_journal_and_never_retries(self):
        with patch.object(adapter.portless, 'run_inside_owned_probe', side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):
                self.item.probe_equivalent_provider('a' * 64)
        self.assertEqual(self.events, ['start'])
        self.assertTrue((self.root / 'docker-mutation.json').exists())
        self.assertTrue(self.running)

    def test_failed_recovery_drain_keeps_live_worker_and_records(self):
        ids = {'old_api': '1' * 64, 'old_worker': '2' * 64,
               'new_api': 'a' * 64, 'new_worker': 'b' * 64}
        self.item.ids = ids
        states = {ident: {'running': False, 'restart_policy': 'no'} for ident in ids.values()}
        states[ids['new_api']]['running'] = True
        states[ids['new_worker']].update(running=True, restart_policy='unless-stopped')
        self.item.assert_no_unresolved_daemon_operations = lambda: None
        self.item.drain_ingress = lambda: self.events.append('drain-ingress')
        self.item.assert_ingress_drained = lambda: None
        self.item.inspect = lambda ident: dict(states[ident])
        self.item.disable_restart = lambda ident: states[ident].update(restart_policy='no')
        def stop(ident):
            self.events.append('stop-' + ident[0])
            states[ident]['running'] = False
        self.item.stop = stop
        self.item._wait_worker_queue_drain = lambda _: (_ for _ in ()).throw(adapter.AdapterError('busy'))
        with self.assertRaises(adapter.AdapterError):
            self.item.preserve_accepted_work_and_quarantine(ids)
        self.assertFalse(states[ids['new_api']]['running'])
        self.assertTrue(states[ids['new_worker']]['running'])
        self.assertEqual(states[ids['new_worker']]['restart_policy'], 'unless-stopped')
        self.assertNotIn('stop-b', self.events)

    def test_indeterminate_daemon_prevents_recovery_mutations(self):
        self.item.assert_no_unresolved_daemon_operations = lambda: (_ for _ in ()).throw(adapter.AdapterError('pending'))
        self.item.drain_ingress = lambda: self.events.append('unexpected')
        with self.assertRaises(adapter.AdapterError):
            self.item.preserve_accepted_work_and_quarantine(self.item.ids)
        self.assertEqual(self.events, [])

    def test_worker_drain_retries_only_completed_negative_result(self):
        self.item.ids['old_worker'] = '2' * 64
        with patch.object(adapter.portless, '_source', return_value=b'probe'), \
             patch.object(self.item, '_run_script', side_effect=[adapter.QueueDrainPending('busy'), None]) as run, \
             patch.object(adapter.time, 'sleep'):
            self.item._wait_worker_queue_drain(self.item.ids['old_worker'])
        self.assertEqual(run.call_count, 2)
        with patch.object(adapter.portless, '_source', return_value=b'probe'), \
             patch.object(self.item, '_run_script', side_effect=adapter.AdapterError('unknown')) as run:
            with self.assertRaises(adapter.AdapterError):
                self.item._wait_worker_queue_drain(self.item.ids['old_worker'])
        self.assertEqual(run.call_count, 1)

    def test_worker_exec_timeout_is_not_a_completed_negative_result(self):
        with patch.object(adapter.subprocess, 'run', side_effect=subprocess.TimeoutExpired('docker', 60)):
            with self.assertRaises(adapter.AdapterError) as caught:
                self.item._run_script('x', b'probe', '--worker', b'QUEUE_DRAIN_OK\n')
        self.assertNotIsInstance(caught.exception, adapter.QueueDrainPending)
        with patch.object(adapter.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout=b'QUEUE_DRAIN_FAILED\n')):
            with self.assertRaises(adapter.QueueDrainPending):
                self.item._run_script('x', b'probe', '--worker', b'QUEUE_DRAIN_OK\n')

    def test_running_nginx_bind_rejects_same_bytes_on_another_inode(self):
        first, second = self.root / 'source', self.root / 'replacement'
        first.write_bytes(b'synthetic nginx configuration')
        second.write_bytes(first.read_bytes())
        first.chmod(0o600)
        second.chmod(0o600)
        state = {'Running': True, 'Pid': 12345, 'StartedAt': 'synthetic-time'}
        self.item._call = lambda args: json.dumps([{'Id': adapter.NGINX_ID, 'State': state}]).encode()
        original_open, original_fstat = os.open, os.fstat
        target = [first]
        def fake_open(path, flags, *args, **kwargs):
            if str(path).startswith('/proc/12345/root/'):
                path = target[0]
            return original_open(path, flags, *args, **kwargs)
        class RootStat:
            def __init__(self, value): self.value = value
            @property
            def st_uid(self): return 0
            def __getattr__(self, name): return getattr(self.value, name)
        with patch.object(adapter, 'NGINX_CONF_SHA', hashlib.sha256(first.read_bytes()).hexdigest()),              patch.object(adapter.os, 'open', side_effect=fake_open),              patch.object(adapter.os, 'fstat', side_effect=lambda fd: RootStat(original_fstat(fd))):
            self.item._verify_running_proxy_bind({'State': state}, str(first))
            target[0] = second
            with self.assertRaises(adapter.AdapterError):
                self.item._verify_running_proxy_bind({'State': state}, str(first))

    def test_https_check_requires_local_tls_readiness_200(self):
        with patch.object(adapter.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'200')) as call:
            self.item._assert_https_ready()
            self.assertIn('--resolve', call.call_args.args[0])
        with patch.object(adapter.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'503')):
            with self.assertRaises(adapter.AdapterError):
                self.item._assert_https_ready()

    def test_worker_requires_pinned_hostname_and_celery_queue(self):
        self.item._bound = lambda *_: True
        self.item.stage_runtime.inspect = lambda _: {'Config': {'Hostname': 'worker-host'}}
        def call(args, **_):
            if 'ping' in args:
                return b'{"celery@worker-host":{"ok":"pong"}}'
            return b'{"celery@worker-host":[{"name":"celery"}]}'
        self.item._call = call
        self.item.assert_worker_healthy('b' * 64)
        self.item._call = lambda *_args, **_kwargs: b'{"celery@other":{"ok":"pong"}}'
        with patch.object(adapter.time, 'monotonic', side_effect=[0, 100]):
            with self.assertRaises(adapter.AdapterError):
                self.item.assert_worker_healthy('b' * 64)

    def test_wrong_probe_identity_does_not_touch_daemon(self):
        with self.assertRaises(adapter.AdapterError):
            self.item.probe_equivalent_provider('f' * 64)
        self.assertEqual(self.events, [])


if __name__ == '__main__':
    unittest.main()
