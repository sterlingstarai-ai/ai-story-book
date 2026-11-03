import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from provider_cutover_production_runtime import (API_IMAGE, OLD_API, OLD_WORKER, WORKER_IMAGE,
                                                  ProductionDockerRuntime, ProductionRuntimeError)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ids = {'old_api': OLD_API, 'old_worker': OLD_WORKER, 'new_api': 'a' * 64, 'new_worker': 'b' * 64}
        self.images = {'old_api': API_IMAGE, 'new_api': API_IMAGE,
                       'old_worker': WORKER_IMAGE, 'new_worker': WORKER_IMAGE}
        self.transaction = 'c' * 32
        names = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
                 'new_api': 'asb-provider-next-api', 'new_worker': 'asb-provider-next-worker'}
        self.raw = {}
        for slot, ident in self.ids.items():
            old = slot.startswith('old_')
            self.raw[ident] = {'Id': ident, 'Image': self.images[slot], 'Name': '/' + names[slot],
                'State': {'Running': old, 'ExitCode': 0, 'OOMKilled': False, 'Error': ''}, 'Config': {'Env': ['SYNTHETIC=ok'], 'Labels': (
                    {} if old else {'asb.provider.transaction': self.transaction})},
                'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped' if old else 'no'},
                               'NetworkMode': 'asb-pilot-net'}, 'Mounts': [],
                'NetworkSettings': {'Networks': {'asb-pilot-net': {}}}}
        self.operations = []
        self.timeout = False
        self.slow_exit = False
        self.runtime = ProductionDockerRuntime(ids=self.ids, transaction=self.transaction,
                                                directory=self.root, stage_verify=lambda *_a, **_kw: None,
                                                runner=self.run_docker)

    def tearDown(self):
        self.tmp.cleanup()

    def run_docker(self, command, **_):
        args = command[3:]
        if args[0] == 'inspect':
            return SimpleNamespace(returncode=0, stdout=json.dumps([self.raw[args[1]]]).encode())
        self.operations.append(args)
        if self.timeout:
            raise subprocess.TimeoutExpired('docker', 90)
        if args[0] == 'update':
            self.raw[args[-1]]['HostConfig']['RestartPolicy']['Name'] = args[1].split('=', 1)[1]
        if args[0] == 'kill':
            self.assertEqual(args[1], '--signal=TERM')
            if not self.slow_exit:
                self.raw[args[-1]]['State']['Running'] = False
        if args[0] == 'start':
            self.raw[args[1]]['State']['Running'] = True
        if args[0] == 'rename':
            self.raw[args[1]]['Name'] = '/' + args[2]
        return SimpleNamespace(returncode=0, stdout=b'')

    def admit(self):
        self.runtime.assert_candidate_and_interlocks(self.ids, self.images, lock_fd=1, old_restart='unless-stopped')

    def test_lifecycle_requires_staging_and_never_starts_old(self):
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.disable_restart(OLD_API)
        self.assertEqual(self.operations, [])
        self.admit()
        self.runtime.disable_restart(OLD_API)
        self.runtime.stop(OLD_API)
        self.runtime.rename(OLD_API, 'asb-pilot-api-before-provider')
        self.runtime.rename(self.ids['new_api'], 'asb-pilot-api')
        self.runtime.start(self.ids['new_api'])
        self.runtime.enable_restart(self.ids['new_api'])
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.start(OLD_API)
        self.runtime.assert_no_unresolved_daemon_operations()
        self.assertFalse((self.root / 'docker-mutation.json').exists())

    def test_docker_default_oom_representation_only_is_normalized(self):
        item = copy.deepcopy(self.raw[self.ids['new_api']])
        item['HostConfig']['OomKillDisable'] = False
        before = self.runtime._fingerprint(item)
        item['HostConfig']['OomKillDisable'] = None
        self.assertEqual(before, self.runtime._fingerprint(item))
        item['HostConfig']['OomKillDisable'] = True
        self.assertNotEqual(before, self.runtime._fingerprint(item))

    def test_mount_order_does_not_hide_actual_mount_changes(self):
        item = self.raw[self.ids['new_api']]
        item['Mounts'] = [
            {'Destination': '/one', 'Source': '/safe/one', 'RW': False},
            {'Destination': '/two', 'Source': '/safe/two', 'RW': False},
        ]
        self.admit()
        item['Mounts'].reverse()
        self.runtime.inspect(self.ids['new_api'])
        item['Mounts'][0]['Source'] = '/other'
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.inspect(self.ids['new_api'])

    def test_invalid_or_duplicate_mount_destinations_fail_closed(self):
        for mounts in ([{'Destination': '/same'}, {'Destination': '/same'}],
                       [{'Destination': 'relative'}], [{'Destination': None}], [None], {}):
            with self.subTest(mounts=mounts):
                item = copy.deepcopy(self.raw[self.ids['new_api']])
                item['Mounts'] = mounts
                with self.assertRaises(ProductionRuntimeError):
                    self.runtime._fingerprint(item)

    def test_changed_config_fails_before_mutation(self):
        self.admit()
        self.raw[OLD_API]['Config']['Env'].append('DIFFERENT=value')
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.disable_restart(OLD_API)
        self.assertEqual(self.operations, [])

    def test_timeout_is_durable_and_cannot_resume(self):
        self.admit()
        self.timeout = True
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.disable_restart(OLD_API)
        self.assertTrue((self.root / 'docker-mutation.json').exists())
        self.timeout = False
        self.slow_exit = False
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.disable_restart(OLD_API)
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.assert_no_unresolved_daemon_operations()
        self.assertEqual(len(self.operations), 1)

    def test_graceful_stop_timeout_never_escalates_to_sigkill(self):
        self.admit()
        self.runtime.disable_restart(OLD_API)
        self.slow_exit = True
        ticks = iter((0, 0, 91))
        self.runtime._clock = lambda: next(ticks)
        self.runtime._sleep = lambda _: None
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.stop(OLD_API)
        self.assertTrue((self.root / 'docker-mutation.json').exists())
        kills = [entry for entry in self.operations if entry[0] == 'kill']
        self.assertEqual(kills, [['kill', '--signal=TERM', OLD_API]])
        self.assertTrue(self.raw[OLD_API]['State']['Running'])

    def test_nonzero_exit_does_not_claim_a_graceful_stop(self):
        self.admit()
        self.runtime.disable_restart(OLD_API)
        self.raw[OLD_API]['State']['ExitCode'] = 137
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.stop(OLD_API)
        self.assertTrue((self.root / 'docker-mutation.json').exists())

    def test_untrusted_identity_and_restart_preconditions(self):
        bad = copy.copy(self.ids)
        bad['old_api'] = 'd' * 64
        with self.assertRaises(ProductionRuntimeError):
            ProductionDockerRuntime(ids=bad, transaction=self.transaction, directory=self.root,
                                    stage_verify=lambda *_a, **_kw: None, runner=self.run_docker)
        self.admit()
        with self.assertRaises(ProductionRuntimeError):
            self.runtime.stop(OLD_API)
        self.assertEqual(self.operations, [])


if __name__ == '__main__':
    unittest.main()
