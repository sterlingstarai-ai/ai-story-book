"""Candidate staging must preserve the old runtime while removing raw keys."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from provider_candidate_stage import (BoundFileEvidence, DockerStageRuntime, StageError, _FileIdentity, _PROBE_CODE,
                                      _probe_contract, _verify_lock, _verify_provider_marker,
                                      clear_probe_owner_after_compound,
                                      create_stopped_probe,
                                      remove_stopped_probe, stage_candidates, verify_running_bound_files, verify_staged)


class Runtime:
    def __init__(self):
        self.old_ids = {'api': 'a' * 64, 'worker': 'b' * 64}
        self.new_ids = {'api': 'c' * 64, 'worker': 'd' * 64}
        self.images = {'api': 'sha256:' + '1' * 64, 'worker': 'sha256:' + '2' * 64}
        self.created = []
        self.items = {}
        for role in ('api', 'worker'):
            old_name = 'asb-pilot-' + role
            new_name = 'asb-provider-next-' + role
            command = (['/guard/entry.py', 'uvicorn', 'src.main:app', '--host', '0.0.0.0', '--port', '8000',
                        '--no-access-log'] if role == 'api' else
                       ['/guard/entry.py', 'celery', '-A', 'src.worker', 'worker', '--loglevel=warning',
                        '--concurrency=1'])
            mounts = [{'Type': 'bind', 'Destination': '/run/storybook-certs/neon-ca.pem',
                       'Source': '/etc/ai-story-book/pilot/private/neon-ca.pem', 'RW': False},
                      {'Type': 'bind', 'Destination': '/guard', 'Source': '/etc/ai-story-book/pilot/guard', 'RW': True},
                      {'Type': 'bind', 'Destination': '/run/storybook-secrets/journal.key',
                       'Source': '/etc/ai-story-book/pilot/private/privacy-journal-app.key', 'RW': False}]
            host = {'NetworkMode': 'asb-pilot-net', 'RestartPolicy': {'Name': 'unless-stopped'},
                    'PortBindings': {'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18081'}]}
                    if role == 'api' else {}}
            old = {'Id': self.old_ids[role], 'Image': self.images[role], 'Name': '/' + old_name,
                   'Config': {'Entrypoint': ['python'], 'Cmd': command, 'User': 'appuser',
                              'Env': ['LLM_API_KEY=synthetic-old', 'IMAGE_API_KEY=synthetic-old',
                                      'DATABASE_URL=synthetic-db'], 'Labels': {}},
                   'HostConfig': host, 'State': {'Running': True}, 'Mounts': mounts}
            new = copy.deepcopy(old)
            new.update(Id=self.new_ids[role], Name='/' + new_name)
            new['Config']['Labels'] = {'asb.provider.transaction': 'f' * 32}
            new['Config']['Env'] = ['DATABASE_URL=synthetic-db',
                                    'LLM_API_KEY_FILE=/run/asb-provider-keys/provider.key',
                                    'IMAGE_API_KEY_FILE=/run/asb-provider-keys/provider.key']
            new['HostConfig']['RestartPolicy'] = {'Name': 'no'}
            new['State']['Running'] = False
            new['Mounts'].extend([
                {'Type': 'bind', 'Destination': '/app/src/core/config.py',
                 'Source': '/etc/ai-story-book/pilot/private/provider-rotation/config.py', 'RW': False},
                {'Type': 'bind', 'Destination': '/run/asb-provider-keys/provider.key',
                 'Source': '/etc/ai-story-book/pilot/private/provider-rotation/provider.key', 'RW': False},
            ])
            self.items[self.old_ids[role]], self.items[self.new_ids[role]] = old, new

    def inspect(self, identifier):
        return copy.deepcopy(self.items[identifier])

    def create(self, args, fd):
        self.created.append((args, fd))
        return self.new_ids['api' if 'asb-provider-next-api' in args else 'worker']


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.runtime = Runtime()
        self.arguments = {'runtime': self.runtime, 'old_ids': self.runtime.old_ids, 'image_ids': self.runtime.images,
                          'environment': b'LLM_API_KEY=synthetic-old\nIMAGE_API_KEY=synthetic-old\nDATABASE_URL=synthetic-db\n',
                          'overlay_path': '/etc/ai-story-book/pilot/private/provider-rotation/config.py',
                          'overlay_sha256': 'e' * 64,
                          'key_path': '/etc/ai-story-book/pilot/private/provider-rotation/provider.key',
                          'transaction_id': 'f' * 32, 'lock_fd': 12}
        self.patches = [mock.patch('provider_candidate_stage._verify_lock'), mock.patch('provider_candidate_stage._file'),
                        mock.patch('provider_candidate_stage.create_environment_memfd', side_effect=lambda _x: os.open('/dev/null', os.O_RDONLY))]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_docker_socket_is_pinned_and_docker_environment_is_removed(self):
        with mock.patch.dict(os.environ, {'DOCKER_HOST': 'unix:///tmp/fake.sock',
                                         'DOCKER_CONTEXT': 'other', 'DOCKER_CONFIG': '/untrusted'}), \
             mock.patch('provider_candidate_stage.subprocess.run') as run:
            run.return_value = SimpleNamespace(returncode=0, stdout=b'[]')
            DockerStageRuntime()._run(['inspect', 'synthetic'])
        args, kwargs = run.call_args
        self.assertEqual(args[0][:3], ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock'])
        self.assertFalse(any(key.startswith('DOCKER_') for key in kwargs['env']))

    def test_stages_stopped_candidates_without_key_in_arguments(self):
        result = stage_candidates(**self.arguments)
        self.assertEqual(result['status'], 'STOPPED_CANDIDATES_VERIFIED')
        self.assertEqual(result['ids']['old_api'], self.runtime.old_ids['api'])
        self.assertEqual(result['ids']['new_worker'], self.runtime.new_ids['worker'])
        self.assertEqual(len(self.runtime.created), 2)
        for args, _ in self.runtime.created:
            self.assertNotIn('synthetic-old', repr(args))
            self.assertNotIn('synthetic-db', repr(args))
            self.assertIn('--restart=no', args)
            self.assertIn('--env-file', args)

    def test_candidate_raw_key_or_mount_change_fails_closed(self):
        self.runtime.items[self.runtime.new_ids['api']]['Config']['Env'].append('LLM_API_KEY=synthetic-old')
        with self.assertRaises(StageError):
            stage_candidates(**self.arguments)
        self.runtime.items[self.runtime.new_ids['api']]['Config']['Env'].pop()
        self.runtime.items[self.runtime.new_ids['api']]['Mounts'][-1]['RW'] = True
        with self.assertRaises(StageError):
            stage_candidates(**self.arguments)

    def test_candidate_runtime_config_must_match_old_container(self):
        for key, changed in (('WorkingDir', '/wrong'), ('StopSignal', 'SIGKILL'),
                             ('Healthcheck', {'Test': ['CMD', 'false']})):
            with self.subTest(field=key):
                candidate = self.runtime.items[self.runtime.new_ids['api']]['Config']
                candidate[key] = changed
                with self.assertRaises(StageError):
                    stage_candidates(**self.arguments)
                candidate.pop(key)

    def test_verification_requires_four_unique_container_ids(self):
        ids = {'old_api': self.runtime.old_ids['api'], 'old_worker': self.runtime.old_ids['worker'],
               'new_api': self.runtime.new_ids['api'], 'new_worker': self.runtime.new_ids['api']}
        args = dict(self.arguments)
        args.pop('old_ids')
        with self.assertRaises(StageError):
            verify_staged(ids=ids, **args)

    def test_invalid_environment_encoding_does_not_expose_contents(self):
        args = dict(self.arguments)
        args['environment'] += b'UNTRUSTED=secret-value-\xff\n'
        with self.assertRaises(StageError) as error:
            stage_candidates(**args)
        self.assertNotIn('secret-value', str(error.exception))

    def test_recheck_after_restart_disable_requires_both_disabled(self):
        ids = {'old_api': self.runtime.old_ids['api'], 'old_worker': self.runtime.old_ids['worker'],
               'new_api': self.runtime.new_ids['api'], 'new_worker': self.runtime.new_ids['worker']}
        args = dict(self.arguments)
        args.pop('old_ids')
        self.runtime.items[ids['old_api']]['HostConfig']['RestartPolicy']['Name'] = 'no'
        with self.assertRaises(StageError):
            verify_staged(ids=ids, old_restart='no', **args)
        self.runtime.items[ids['old_worker']]['HostConfig']['RestartPolicy']['Name'] = 'no'
        self.assertEqual(verify_staged(ids=ids, old_restart='no', **args)['status'],
                         'STOPPED_CANDIDATES_VERIFIED')

    def test_recovery_only_accepts_exact_old_api_stopped_worker_running_state(self):
        ids = {'old_api': self.runtime.old_ids['api'], 'old_worker': self.runtime.old_ids['worker'],
               'new_api': self.runtime.new_ids['api'], 'new_worker': self.runtime.new_ids['worker']}
        args = dict(self.arguments)
        args.pop('old_ids')
        for slot in ('old_api', 'old_worker'):
            self.runtime.items[ids[slot]]['HostConfig']['RestartPolicy']['Name'] = 'no'
        self.runtime.items[ids['old_api']]['State']['Running'] = False
        owner = {'version': 1, 'transaction': 'f' * 32, 'containers': ids}
        probe = {'version': 1, 'transaction': 'f' * 32, 'candidate': ids['new_api'],
                 'probe': '9' * 64, 'image': self.runtime.images['api']}
        options = {'old_restart': 'no', 'marker_state': 'owned', 'expected_candidate_owner': owner,
                   'expected_probe_owner': probe, 'old_running': {'api': False, 'worker': True}}
        self.assertEqual(verify_staged(ids=ids, **args, **options)['status'], 'STOPPED_CANDIDATES_VERIFIED')
        for changes in ({'marker_state': 'absent'}, {'expected_probe_owner': None},
                        {'old_running': {'api': 0, 'worker': True}}, {'old_restart': 'unless-stopped'}):
            with self.subTest(changes=changes), self.assertRaises(StageError):
                verify_staged(ids=ids, **args, **(options | changes))
        self.runtime.items[ids['old_worker']]['State']['Running'] = False
        with self.assertRaises(StageError):
            verify_staged(ids=ids, **args, **options)

    def test_probe_is_stopped_has_no_published_port_and_cleans_up_by_exact_id(self):
        probe_id = '9' * 64
        ids = {'old_api': self.runtime.old_ids['api'], 'old_worker': self.runtime.old_ids['worker'],
               'new_api': self.runtime.new_ids['api'], 'new_worker': self.runtime.new_ids['worker']}
        candidate = self.runtime.items[ids['new_api']]
        probe = copy.deepcopy(candidate)
        probe['Id'] = probe_id
        probe['Name'] = '/asb-provider-probe-' + 'f' * 32
        probe['Config']['Labels']['asb.provider.role'] = 'isolated-probe'
        probe['Config']['Cmd'] = ['-c', _PROBE_CODE]
        probe['HostConfig']['PortBindings'] = None
        probe['HostConfig']['PublishAllPorts'] = False
        self.runtime.items[probe_id] = probe
        self.runtime.create = mock.Mock(return_value=probe_id)
        self.runtime.remove = mock.Mock(side_effect=lambda identifier: self.runtime.items.pop(identifier))
        self.runtime.exists = mock.Mock(side_effect=lambda identifier: identifier in self.runtime.items)
        evidence = BoundFileEvidence(None, None)
        args = {k: self.arguments[k] for k in ('runtime', 'image_ids', 'environment', 'overlay_path',
                                                'overlay_sha256', 'key_path', 'transaction_id', 'lock_fd')}
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch('provider_candidate_stage._PROVIDER_STATE', folder), \
             mock.patch('provider_candidate_stage.verify_staged'), \
             mock.patch('provider_candidate_stage._verify_backup_lock_fd'), \
             mock.patch('provider_candidate_stage.capture_bound_file_evidence', return_value=evidence):
            result = create_stopped_probe(ids=ids, evidence=evidence, state_dir=folder, **args)
            self.assertEqual(result['probe_id'], probe_id)
            docker_args = self.runtime.create.call_args.args[0]
            self.assertNotIn('-p', docker_args)
            self.assertNotIn('synthetic-old', repr(docker_args))
            self.assertFalse((Path(folder) / 'docker-mutation.json').exists())
            owner = json.loads((Path(folder) / 'probe-owner.json').read_text())
            self.assertEqual(owner['probe'], probe_id)
            self.assertTrue(remove_stopped_probe(runtime=self.runtime, probe_id=probe_id,
                                                candidate_id=ids['new_api'], image_id=self.runtime.images['api'],
                                                transaction_id='f' * 32, lock_fd=12, overlay_path=self.arguments['overlay_path'],
                                                key_path=self.arguments['key_path'], state_dir=folder))
            self.assertFalse((Path(folder) / 'docker-mutation.json').exists())
            self.assertFalse((Path(folder) / 'probe-owner.json').exists())
        self.assertNotIn(probe_id, self.runtime.items)

    def test_owned_probe_is_recorded_before_create_journal_is_released(self):
        probe_id = '9' * 64
        ids = {'old_api': self.runtime.old_ids['api'], 'old_worker': self.runtime.old_ids['worker'],
               'new_api': self.runtime.new_ids['api'], 'new_worker': self.runtime.new_ids['worker']}
        probe = copy.deepcopy(self.runtime.items[ids['new_api']])
        probe['Id'], probe['Name'] = probe_id, '/asb-provider-probe-' + 'f' * 32
        probe['Config']['Labels']['asb.provider.role'] = 'isolated-probe'
        probe['Config']['Cmd'] = ['-c', _PROBE_CODE]
        probe['HostConfig']['PortBindings'] = None
        probe['HostConfig']['PublishAllPorts'] = False
        self.runtime.items[probe_id] = probe
        self.runtime.create = mock.Mock(return_value=probe_id)
        evidence = BoundFileEvidence(None, None)
        args = {k: self.arguments[k] for k in ('runtime', 'image_ids', 'environment', 'overlay_path',
                                                'overlay_sha256', 'key_path', 'transaction_id', 'lock_fd')}
        from provider_candidate_stage import _write_probe_owner
        def write_then_fail(directory, record):
            _write_probe_owner(directory, record)
            raise RuntimeError('synthetic interruption after durable owner write')
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch('provider_candidate_stage._PROVIDER_STATE', folder), \
             mock.patch('provider_candidate_stage.verify_staged'), \
             mock.patch('provider_candidate_stage.capture_bound_file_evidence', return_value=evidence), \
             mock.patch('provider_candidate_stage._write_probe_owner', side_effect=write_then_fail):
            with self.assertRaises(StageError):
                create_stopped_probe(ids=ids, evidence=evidence, state_dir=folder, **args)
            self.assertTrue((Path(folder) / 'probe-owner.json').is_file())
            self.assertTrue((Path(folder) / 'docker-mutation.json').is_file())

    def test_probe_owner_cannot_clear_before_matching_mutation_and_confirmed_absence(self):
        token, candidate_id, probe_id = 'f' * 32, self.runtime.new_ids['api'], '9' * 64
        image_id = self.runtime.images['api']
        owner = {'version': 1, 'transaction': token, 'candidate': candidate_id, 'probe': probe_id, 'image': image_id}
        mutation = {'version': 1, 'transaction': token, 'action': 'provider-probe', 'container': probe_id}
        self.runtime.exists = mock.Mock(return_value=True)
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch('provider_candidate_stage._PROVIDER_STATE', folder), \
             mock.patch('provider_candidate_stage._verify_backup_lock_fd'):
            owner_path = Path(folder) / 'probe-owner.json'
            mutation_path = Path(folder) / 'docker-mutation.json'
            owner_path.write_text(json.dumps(owner))
            owner_path.chmod(0o600)
            kwargs = {'runtime': self.runtime, 'probe_id': probe_id, 'candidate_id': candidate_id,
                      'image_id': image_id, 'transaction_id': token, 'lock_fd': 12, 'state_dir': folder}
            with self.assertRaises(StageError):
                clear_probe_owner_after_compound(**kwargs)
            mutation_path.write_text(json.dumps(mutation))
            mutation_path.chmod(0o600)
            with self.assertRaises(StageError):
                clear_probe_owner_after_compound(**kwargs)
            self.assertTrue(owner_path.exists())
            self.runtime.exists.return_value = False
            self.assertTrue(clear_probe_owner_after_compound(**kwargs))
            self.assertFalse(owner_path.exists())
            self.assertTrue(mutation_path.exists())

    def test_probe_rejects_publish_all_ports_even_without_explicit_bindings(self):
        probe_id = '9' * 64
        candidate = self.runtime.items[self.runtime.new_ids['api']]
        probe = copy.deepcopy(candidate)
        probe['Id'], probe['Name'] = probe_id, '/asb-provider-probe-' + 'f' * 32
        probe['Config']['Labels']['asb.provider.role'] = 'isolated-probe'
        probe['Config']['Cmd'] = ['-c', _PROBE_CODE]
        probe['HostConfig']['PortBindings'] = None
        probe['HostConfig']['PublishAllPorts'] = True
        with self.assertRaises(StageError):
            _probe_contract(probe, identifier=probe_id, image_id=self.runtime.images['api'],
                            transaction_id='f' * 32, candidate=candidate,
                            overlay_path=self.arguments['overlay_path'], key_path=self.arguments['key_path'])

    def test_probe_create_timeout_leaves_durable_mutation_marker(self):
        ids = {'old_api': self.runtime.old_ids['api'], 'old_worker': self.runtime.old_ids['worker'],
               'new_api': self.runtime.new_ids['api'], 'new_worker': self.runtime.new_ids['worker']}
        evidence = BoundFileEvidence(None, None)
        self.runtime.create = mock.Mock(side_effect=TimeoutError('synthetic'))
        args = {k: self.arguments[k] for k in ('runtime', 'image_ids', 'environment', 'overlay_path',
                                                'overlay_sha256', 'key_path', 'transaction_id', 'lock_fd')}
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch('provider_candidate_stage._PROVIDER_STATE', folder), \
             mock.patch('provider_candidate_stage.verify_staged'), \
             mock.patch('provider_candidate_stage.capture_bound_file_evidence', return_value=evidence):
            with self.assertRaises(StageError):
                create_stopped_probe(ids=ids, evidence=evidence, state_dir=folder, **args)
            marker = json.loads((Path(folder) / 'docker-mutation.json').read_text())
            self.assertEqual(marker['action'], 'probe-create')
            self.assertEqual(marker['container'], ids['new_api'])

    def test_running_candidate_must_match_pre_start_bind_inodes_and_contents(self):
        overlay = _FileIdentity(1, 10, 12, 20, 30, 1000, 1000, 0o600, b'overlay-digest')
        key = _FileIdentity(1, 11, 16, 21, 31, 1000, 1000, 0o600, b'synthetic-secret-hash')
        evidence = BoundFileEvidence(overlay, key)
        identifier = self.runtime.new_ids['api']
        item = self.runtime.items[identifier]
        item['State'].update(Running=True, Restarting=False, Pid=4321, StartedAt='2026-11-03T00:00:00Z')
        args = {'runtime': self.runtime, 'identifier': identifier, 'image_id': self.runtime.images['api'],
                'transaction_id': 'f' * 32, 'evidence': evidence,
                'overlay_path': self.arguments['overlay_path'], 'overlay_sha256': 'e' * 64,
                'key_path': self.arguments['key_path']}
        with mock.patch('provider_candidate_stage.capture_bound_file_evidence', return_value=evidence), \
             mock.patch('provider_candidate_stage._container_file', side_effect=[overlay, key]):
            self.assertTrue(verify_running_bound_files(**args))
        with mock.patch('provider_candidate_stage.capture_bound_file_evidence', return_value=evidence), \
             mock.patch('provider_candidate_stage._container_file', side_effect=[overlay, overlay]):
            with self.assertRaises(StageError):
                verify_running_bound_files(**args)
        changed = BoundFileEvidence(overlay, _FileIdentity(1, 12, 16, 21, 31, 1000, 1000, 0o600, b'other'))
        with mock.patch('provider_candidate_stage.capture_bound_file_evidence', return_value=changed):
            with self.assertRaises(StageError):
                verify_running_bound_files(**args)
        self.assertNotIn('synthetic-secret', repr(evidence))

    def test_running_candidate_restart_during_check_is_rejected(self):
        overlay = _FileIdentity(1, 10, 12, 20, 30, 1000, 1000, 0o600, b'a')
        key = _FileIdentity(1, 11, 16, 21, 31, 1000, 1000, 0o600, b'b')
        evidence = BoundFileEvidence(overlay, key)
        identifier = self.runtime.new_ids['api']
        before = self.runtime.inspect(identifier)
        before['State'].update(Running=True, Restarting=False, Pid=4321, StartedAt='before')
        after = copy.deepcopy(before)
        after['State']['StartedAt'] = 'after'
        self.runtime.inspect = mock.Mock(side_effect=[before, after])
        with mock.patch('provider_candidate_stage.capture_bound_file_evidence', return_value=evidence), \
             mock.patch('provider_candidate_stage._container_file', side_effect=[overlay, key]):
            with self.assertRaises(StageError):
                verify_running_bound_files(runtime=self.runtime, identifier=identifier,
                                           image_id=self.runtime.images['api'], transaction_id='f' * 32,
                                           evidence=evidence, overlay_path=self.arguments['overlay_path'],
                                           overlay_sha256='e' * 64, key_path=self.arguments['key_path'])

    def test_candidate_owner_must_match_transaction_and_all_four_ids(self):
        ids = {'old_api': self.runtime.old_ids['api'], 'old_worker': self.runtime.old_ids['worker'],
               'new_api': self.runtime.new_ids['api'], 'new_worker': self.runtime.new_ids['worker']}
        owner = {'version': 1, 'transaction': 'f' * 32, 'containers': ids}
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch('provider_candidate_stage._PROVIDER_STATE', folder), \
             mock.patch('provider_candidate_stage._PENDING', (str(Path(folder) / 'recovery.json'),)), \
             mock.patch('provider_candidate_stage._verify_backup_lock_fd'):
            marker = Path(folder) / 'candidate-owner.json'
            marker.write_text(json.dumps(owner))
            marker.chmod(0o600)
            with self.assertRaises(StageError):
                _verify_lock(12)
            _verify_lock(12, expected_candidate_owner=owner)
            altered = {**owner, 'containers': {**ids, 'new_worker': '8' * 64}}
            with self.assertRaises(StageError):
                _verify_lock(12, expected_candidate_owner=altered)
            marker.unlink()
            with self.assertRaises(StageError):
                _verify_lock(12, expected_candidate_owner=owner)

    def test_only_exact_owned_candidate_create_mutation_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch('provider_candidate_stage._PROVIDER_STATE', folder), \
             mock.patch('provider_candidate_stage._PENDING',
                        (str(Path(folder) / 'docker-mutation.json'), str(Path(folder) / 'recovery.json'))), \
             mock.patch('provider_candidate_stage._verify_backup_lock_fd'):
            mutation_path = Path(folder) / 'docker-mutation.json'
            mutation = {'version': 1, 'transaction': 'f' * 32, 'action': 'candidate-create',
                        'container': self.runtime.old_ids['api']}
            with self.assertRaises(StageError):
                _verify_lock(12, expected_mutation=mutation)
            mutation_path.write_text(json.dumps(mutation))
            mutation_path.chmod(0o600)
            with self.assertRaises(StageError):
                _verify_lock(12)
            _verify_lock(12, expected_mutation=mutation)
            with self.assertRaises(StageError):
                _verify_lock(12, expected_mutation={**mutation, 'transaction': 'e' * 32})
            (Path(folder) / 'recovery.json').write_text('{}')
            with self.assertRaises(StageError):
                _verify_lock(12, expected_mutation=mutation)

    def test_unresolved_daemon_mutation_blocks_staging(self):
        item = SimpleNamespace(st_mode=0o100600, st_uid=0, st_nlink=1, st_dev=1, st_ino=2)

        def inspect_path(path):
            if path == '/var/lib/ai-story-book/backup-state/backup.lock':
                return item
            if path == '/var/lib/ai-story-book/provider-rotation/docker-mutation.json':
                return item
            raise FileNotFoundError(path)

        # setUp patches _verify_lock for other staging tests; restore it here.
        with mock.patch('provider_candidate_stage.os.fstat', return_value=item), \
             mock.patch('provider_candidate_stage.os.lstat', side_effect=inspect_path), \
             mock.patch('provider_candidate_stage.fcntl.flock'):
            with self.assertRaises(StageError):
                _verify_lock(12)

    def test_owned_marker_must_match_all_exact_identities_and_be_private(self):
        ids = {'old_api': 'a' * 64, 'old_worker': 'b' * 64, 'new_api': 'c' * 64, 'new_worker': 'd' * 64}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'recovery.json'
            path.write_text(json.dumps({'version': 1, 'containers': ids}))
            path.chmod(0o600)
            _verify_provider_marker(str(path), ids, owner=os.geteuid())
            changed = dict(ids, new_api='e' * 64)
            with self.assertRaises(StageError):
                _verify_provider_marker(str(path), changed, owner=os.geteuid())
            path.write_text(json.dumps({'version': True, 'containers': ids}))
            with self.assertRaises(StageError):
                _verify_provider_marker(str(path), ids, owner=os.geteuid())
            path.write_text(json.dumps({'version': 1, 'containers': ids}))
            path.chmod(0o644)
            with self.assertRaises(StageError):
                _verify_provider_marker(str(path), ids, owner=os.geteuid())


if __name__ == '__main__':
    unittest.main()
