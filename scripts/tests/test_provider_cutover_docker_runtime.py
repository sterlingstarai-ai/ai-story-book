"""Disposable daemon adapter checks; no production host or credentials."""
import json
import subprocess
import unittest

from scripts.provider_cutover_docker_runtime import (
    ContainerTarget, DockerCutoverRuntime, DockerRuntimeError, UncertainDockerOperation,
)

ID = 'a' * 64
IMAGE = 'sha256:' + 'b' * 64
OWNER = 'c' * 32


class FakeDocker:
    def __init__(self):
        self.item = {'id': ID, 'name': '/test-before', 'image_id': IMAGE, 'running': True,
                     'status': 'running', 'paused': False, 'restart_policy': 'unless-stopped',
                     'network': 'none', 'attachments': {}, 'owner': OWNER}
        self.network = {'id': 'd' * 64, 'name': 'fixture-net', 'internal': True, 'owner': OWNER}
        self.commands = []
        self.fail_after = None

    def __call__(self, args, **kwargs):
        self.commands.append(args[1])
        action = args[1]
        if action == 'inspect':
            return subprocess.CompletedProcess(args, 0, json.dumps(self.item), '')
        if action == 'network':
            return subprocess.CompletedProcess(args, 0, json.dumps(self.network), '')
        if action == 'stop':
            self.item.update(running=False, status='exited')
        elif action == 'start':
            self.item.update(running=True, status='running')
        elif action == 'rename':
            self.item['name'] = '/' + args[-1]
        elif action == 'update':
            self.item['restart_policy'] = args[2].split('=', 1)[1]
        if self.fail_after == action:
            raise subprocess.TimeoutExpired(args, kwargs['timeout'], output='secret-should-not-leak')
        return subprocess.CompletedProcess(args, 0, '', '')


class DockerRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.docker = FakeDocker()
        self.target = ContainerTarget(ID, IMAGE, 'test-before', frozenset({'test-before', 'test-after'}))
        self.runtime = DockerCutoverRuntime([self.target], owner_token=OWNER, runner=self.docker,
                                            daemon_quiescence=lambda: True)

    def test_pinned_lifecycle_rechecks_each_result(self):
        self.runtime.disable_restart(ID)
        self.runtime.stop(ID)
        self.runtime.rename(ID, 'test-after')
        self.runtime.start(ID)
        self.runtime.enable_restart(ID)
        self.runtime.assert_no_unresolved_daemon_operations()
        self.assertEqual(self.runtime.inspect(ID), {'id': ID, 'name': 'test-after', 'image_id': IMAGE,
                                                    'running': True, 'restart_policy': 'unless-stopped'})
        self.assertGreaterEqual(self.docker.commands.count('inspect'), 11)

    def test_foreign_owner_image_network_and_unexpected_name_fail_closed(self):
        for key, value in [('owner', 'd' * 32), ('image_id', 'sha256:' + 'e' * 64),
                           ('network', 'bridge'), ('name', '/someone-else')]:
            before = self.docker.item[key]
            self.docker.item[key] = value
            with self.subTest(key=key), self.assertRaises(DockerRuntimeError):
                self.runtime.stop(ID)
            self.assertNotIn('stop', self.docker.commands)
            self.docker.item[key] = before

    def test_timeout_remains_unresolved_even_if_state_looks_correct(self):
        self.runtime.disable_restart(ID)
        self.docker.fail_after = 'stop'
        with self.assertRaises(UncertainDockerOperation) as error:
            self.runtime.stop(ID)
        self.assertNotIn('secret-should-not-leak', str(error.exception))
        self.assertFalse(self.runtime.inspect(ID)['running'])
        with self.assertRaises(UncertainDockerOperation):
            self.runtime.assert_no_unresolved_daemon_operations()
        with self.assertRaises(UncertainDockerOperation):
            self.runtime.start(ID)

    def test_after_uncertain_rename_containment_can_disable_and_stop(self):
        self.runtime.disable_restart(ID)
        self.runtime.stop(ID)
        self.docker.fail_after = 'rename'
        with self.assertRaises(UncertainDockerOperation):
            self.runtime.rename(ID, 'test-after')
        self.docker.fail_after = None
        self.assertEqual(self.runtime.inspect(ID)['name'], 'test-after')
        self.runtime.disable_restart(ID)
        self.runtime.stop(ID)
        with self.assertRaises(UncertainDockerOperation):
            self.runtime.assert_no_unresolved_daemon_operations()

    def test_daemon_quiescence_needs_independent_assertion(self):
        runtime = DockerCutoverRuntime([self.target], owner_token=OWNER, runner=self.docker)
        with self.assertRaises(UncertainDockerOperation):
            runtime.assert_no_unresolved_daemon_operations()

    def test_unowned_identifier_or_name_never_calls_daemon(self):
        with self.assertRaises(DockerRuntimeError):
            self.runtime.stop('d' * 64)
        with self.assertRaises(DockerRuntimeError):
            self.runtime.rename(ID, 'outside-target')
        self.assertEqual(self.docker.commands, [])

    def test_restart_and_start_preconditions_fail_before_mutation(self):
        with self.assertRaises(DockerRuntimeError):
            self.runtime.stop(ID)  # restart policy still active
        self.runtime.disable_restart(ID)
        self.runtime.stop(ID)
        with self.assertRaises(DockerRuntimeError):
            self.runtime.enable_restart(ID)  # must be running first
        self.assertEqual(self.docker.commands.count('update'), 1)

    def test_invalid_target_and_callback_are_rejected(self):
        with self.assertRaises(ValueError):
            DockerCutoverRuntime([ContainerTarget(None, IMAGE, 'test-before', frozenset({'test-before'}))],
                                 owner_token=OWNER, runner=self.docker)
        with self.assertRaises(ValueError):
            DockerCutoverRuntime([self.target], owner_token=OWNER, runner=self.docker, daemon_quiescence=True)

    def test_interrupted_daemon_operation_is_sticky_unresolved(self):
        self.runtime.disable_restart(ID)
        original = self.runtime._run

        def interrupt(args, **kwargs):
            if args[1] == 'stop':
                raise KeyboardInterrupt()
            return original(args, **kwargs)

        self.runtime._run = interrupt
        with self.assertRaises(UncertainDockerOperation):
            self.runtime.stop(ID)
        with self.assertRaises(UncertainDockerOperation):
            self.runtime.assert_no_unresolved_daemon_operations()

    def test_owned_internal_network_requires_exact_id_and_no_extra_attachments(self):
        self.docker.item['network'] = 'fixture-net'
        self.docker.item['attachments'] = {'fixture-net': {'NetworkID': 'd' * 64}}
        runtime = DockerCutoverRuntime([self.target], owner_token=OWNER, runner=self.docker,
                                       internal_network_id='d' * 64)
        self.assertTrue(runtime.inspect(ID)['running'])
        for key, value in [('internal', False), ('owner', 'e' * 32), ('id', 'e' * 64)]:
            before = self.docker.network[key]
            self.docker.network[key] = value
            with self.subTest(key=key), self.assertRaises(DockerRuntimeError):
                runtime.inspect(ID)
            self.docker.network[key] = before
        self.docker.item['attachments']['unapproved'] = {'NetworkID': 'f' * 64}
        with self.assertRaises(DockerRuntimeError):
            runtime.inspect(ID)

    def test_created_container_may_have_unresolved_network_id_before_first_start(self):
        self.docker.item.update(network='fixture-net', attachments={'fixture-net': {'NetworkID': ''}},
                                status='created', running=False, restart_policy='no')
        runtime = DockerCutoverRuntime([self.target], owner_token=OWNER, runner=self.docker,
                                       internal_network_id='d' * 64)
        self.assertFalse(runtime.inspect(ID)['running'])
        self.docker.item.update(status='running', running=True)
        with self.assertRaises(DockerRuntimeError):
            runtime.inspect(ID)

    def test_target_label_key_is_constrained(self):
        with self.assertRaises(ValueError):
            DockerCutoverRuntime([ContainerTarget(ID, IMAGE, 'test-before', frozenset({'test-before'}),
                                                  owner_label='unrelated.label')],
                                 owner_token=OWNER, runner=self.docker)


if __name__ == '__main__':
    unittest.main()
