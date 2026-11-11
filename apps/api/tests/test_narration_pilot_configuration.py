"""Staged narration mode is pinned without inspecting real containers."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    module = importlib.import_module('narration_pilot_adapter')
    adapter = module.NarrationPilotAdapter.__new__(module.NarrationPilotAdapter)
    adapter.identities = {name: name for name in ('old_api', 'old_worker', 'new_api', 'new_worker')}
    adapter.expected_google_project = 'test-project-123'
    adapter.expected_daily_limit = 3
    adapter.expected_monthly_limit = 10
    adapter.expected_narration_only = False
    adapter.expected_gcs_media = False
    adapter.storage_only = False
    base = ['UNRELATED=unchanged', 'AUDIO_FEATURE_ENABLED=false']
    staged = ['UNRELATED=unchanged', 'AUDIO_FEATURE_ENABLED=true', 'TTS_PROVIDER=google_gemini',
              'GOOGLE_GEMINI_TTS_PROJECT=test-project-123', 'GOOGLE_GEMINI_TTS_DAILY_REQUEST_LIMIT=3',
              'GOOGLE_GEMINI_TTS_MONTHLY_REQUEST_LIMIT=10']
    def item(env):
        return {'Config': {'Env': env}, 'Mounts': [], 'HostConfig': {'NetworkMode': 'isolated'}}
    items = {key: item(list(base if key.startswith('old_') else staged)) for key in adapter.identities}
    adapter._full_inspect = lambda identifier: items[identifier]
    return module, adapter, items


def test_legacy_mode_accepts_absent_flag(sample):
    _, adapter, _ = sample
    adapter._verify_configurations()


@pytest.mark.parametrize(('arguments', 'reload', 'passes'), [
    ('--journal-witness-bucket ${ASB_JOURNAL_WITNESS_BUCKET}', 'no', True),
    ('', 'no', False),
    ('--journal-witness-bucket hard-coded-bucket', 'no', False),
    ('--journal-witness-bucket ${ASB_JOURNAL_WITNESS_BUCKET} --journal-witness-bucket other', 'no', False),
    ('--journal-witness-bucket ${ASB_JOURNAL_WITNESS_BUCKET}', 'yes', False),
])
@pytest.mark.parametrize('python_flags', ['', '-B ', '-I ', '-B -B ', '-B -I '])
def test_pilot_preflight_checks_loaded_backup_witness_argument(sample, monkeypatch, arguments, reload, passes,
                                                              python_flags):
    module, _, _ = sample
    unit = (f'ExecStart={{ argv[]=/opt/pilot/bin/python {python_flags}'
            f'/opt/pilot/run_scheduled_backup.py --execute {arguments} ; }}')
    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs:
                        SimpleNamespace(stdout=f'{unit}\nNeedDaemonReload={reload}\n'))
    if passes and python_flags in ('', '-B '):
        module._verify_backup_witness_argument()
    else:
        with pytest.raises(module.PilotAdapterError, match='staged journal witness'):
            module._verify_backup_witness_argument()


def test_staged_witness_rejects_a_legacy_scheduler_before_reading_staged_files(sample, monkeypatch):
    module, adapter, items = sample
    adapter.service_config_generation = 'fixture'
    for name in ('new_api', 'new_worker'):
        items[name]['Config']['Env'].append('PRIVACY_JOURNAL_WITNESS_BUCKET=fixture-witness')
    monkeypatch.setattr(module.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(
        stdout='ExecStart={ argv[]=/opt/pilot/bin/python /opt/pilot/run_scheduled_backup.py --execute ; }\n'
               'NeedDaemonReload=no\n',
    ))
    monkeypatch.setattr(module, 'private_file', lambda *_args, **_kwargs: pytest.fail('read staged files'))
    with pytest.raises(module.PilotAdapterError, match='staged journal witness'):
        adapter._verified_service_configs()


@pytest.mark.parametrize('value', ['true', 1, None])
def test_constructor_requires_boolean_mode(sample, monkeypatch, value):
    module, _, _ = sample
    monkeypatch.setattr(module, '_validate_ids', lambda ids: ids)
    with pytest.raises(module.PilotAdapterError, match='explicitly boolean'):
        module.NarrationPilotAdapter(
            runtime=None, identities={}, image_ids={}, backup_arguments={},
            expected_google_project='test-project-123', expected_daily_limit=3,
            expected_monthly_limit=10, proxy_id='a' * 64, proxy_image_id='sha256:' + 'b' * 64,
            expected_proxy_config_sha256='c' * 64, expected_monitor_manifest_sha256='d' * 64,
            expected_narration_only=value,
        )


def test_narration_only_requires_explicit_match_on_both_containers(sample):
    module, adapter, items = sample
    adapter.expected_narration_only = True
    for name in ('new_api', 'new_worker'):
        items[name]['Config']['Env'].append('AUDIO_NARRATION_ONLY_ENABLED=true')
    adapter._verify_configurations()
    items['new_worker']['Config']['Env'][-1] = 'AUDIO_NARRATION_ONLY_ENABLED=false'
    with pytest.raises(module.PilotAdapterError):
        adapter._verify_configurations()


def test_mode_is_not_silently_enabled(sample):
    module, adapter, items = sample
    for name in ('new_api', 'new_worker'):
        items[name]['Config']['Env'].append('AUDIO_NARRATION_ONLY_ENABLED=true')
    with pytest.raises(module.PilotAdapterError):
        adapter._verify_configurations()


@pytest.mark.parametrize('value', ['1', 'yes', '', 'false ', 'TRUE-ish'])
def test_mode_rejects_ambiguous_values(sample, value):
    module, adapter, items = sample
    items['new_api']['Config']['Env'].append('AUDIO_NARRATION_ONLY_ENABLED=' + value)
    with pytest.raises(module.PilotAdapterError):
        adapter._verify_configurations()


def test_unrelated_environment_cannot_change(sample):
    module, adapter, items = sample
    adapter.expected_narration_only = True
    for name in ('new_api', 'new_worker'):
        items[name]['Config']['Env'].append('AUDIO_NARRATION_ONLY_ENABLED=true')
    items['new_api']['Config']['Env'][0] = 'UNRELATED=changed'
    with pytest.raises(module.PilotAdapterError):
        adapter._verify_configurations()


def test_service_config_install_rejects_drift_before_replacing_any_file(sample, monkeypatch, tmp_path):
    module, adapter, _ = sample
    monkeypatch.setattr(module, 'PRIVATE_CONFIG_DIR', tmp_path)
    backup, refresh = (tmp_path / name for name in ('backup-config.env', 'provider-refresh.env'))
    for path in (backup, refresh):
        path.write_bytes(b'OLD=1\n')
        path.chmod(0o600)
    configs = {path: (b'OLD=1\n', b'NEW=1\n') for path in (backup, refresh)}
    refresh.write_bytes(b'CHANGED=1\n')
    with pytest.raises(module.PilotAdapterError, match='changed before'):
        adapter._install_service_configs(configs)
    assert backup.read_bytes() == b'OLD=1\n'
    refresh.write_bytes(b'OLD=1\n')
    adapter._install_service_configs(configs)
    assert all(path.read_bytes() == b'NEW=1\n' and path.stat().st_mode & 0o777 == 0o600
               for path in (backup, refresh))


def test_gcs_transition_pins_credentials_legacy_urls_and_overlay(sample, monkeypatch):
    module, adapter, items = sample
    adapter.expected_gcs_media = True
    monkeypatch.setattr(module, 'private_file', lambda *_a, **_k:
                        b'S3_ACCESS_KEY=fixtureaccess\nS3_SECRET_KEY=fixturesecret\n')
    old_base = 'https://old.example.invalid/media'
    overlay = dict(zip(('Type', 'Source', 'Destination', 'RW'), module.OLD_CONFIG_OVERLAY))
    for role in ('api', 'worker'):
        old, new = items['old_' + role], items['new_' + role]
        old['Config']['Env'].append('S3_PUBLIC_URL=' + old_base)
        old['Mounts'] = [overlay]
        new['Config']['Env'].extend(f'{k}={v}' for k, v in adapter._expected_media_changes(
            adapter._environment(old)).items())
    adapter._verify_configurations()
    new['Mounts'] = [overlay]
    with pytest.raises(module.PilotAdapterError, match='mounts differ'):
        adapter._verify_configurations()
    new['Mounts'] = []
    new['Config']['Env'].remove('S3_LEGACY_PUBLIC_URLS=' + old_base)
    with pytest.raises(module.PilotAdapterError, match='settings'):
        adapter._verify_configurations()


def test_live_network_rejects_extra_peer_and_published_broker(sample):
    module, adapter, _ = sample
    adapter.proxy_id = 'proxy'
    names = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
             'proxy': 'asb-pilot-nginx', 'redis': 'asb-pilot-redis'}
    network = {'Name': 'asb-pilot-net', 'Driver': 'bridge',
               'Containers': {key: {'Name': name} for key, name in names.items()}}
    redis = {'Id': 'redis', 'Name': '/asb-pilot-redis', 'State': {'Running': True},
             'HostConfig': {'PortBindings': {}, 'PublishAllPorts': False}}
    adapter.runtime = SimpleNamespace(_run=lambda *_: json.dumps([network]))
    adapter._full_inspect = lambda key: redis if key == 'redis' else None
    adapter._verify_live_network()
    network['Containers']['unexpected'] = {'Name': 'unexpected'}
    with pytest.raises(module.PilotAdapterError, match='network'):
        adapter._verify_live_network()
    del network['Containers']['unexpected']
    redis['HostConfig']['PublishAllPorts'] = True
    with pytest.raises(module.PilotAdapterError, match='broker'):
        adapter._verify_live_network()


def test_isolated_readiness_requires_closed_proxy_and_empty_queue(sample, monkeypatch):
    module, adapter, _ = sample
    adapter.expected_gcs_media = True
    adapter._migrated = adapter._preflight_complete = True
    adapter._isolated_verified = False
    adapter._verify_stopped_proxy = lambda: None
    adapter._verify_candidate_ports = lambda: None
    adapter._verify_live_network = lambda *, isolated: None if isolated else pytest.fail('not isolated')
    adapter._verify_api_and_worker = lambda: None
    adapter._candidate_generation = lambda: ('api', 'worker')
    monkeypatch.setattr(module, '_source', lambda *_: b'fixture')
    reply = SimpleNamespace(stdout=b'QUEUE_DRAIN_FAILED\n', returncode=1)
    monkeypatch.setattr(module.subprocess, 'run', lambda *_a, **_k: reply)
    with pytest.raises(module.PilotAdapterError, match='queue'):
        adapter.verify_isolated()
    assert not adapter._isolated_verified
    reply.stdout, reply.returncode = b'QUEUE_DRAIN_OK\n', 0
    assert adapter.verify_isolated() is True
    assert adapter._isolated_verified


def test_worker_drain_uses_full_probe_budget_but_respects_total_deadline(sample, monkeypatch):
    module, adapter, _ = sample
    now = 0
    budgets = []

    def run(*_args, timeout, **_kwargs):
        nonlocal now
        budgets.append(timeout)
        now += 149
        if len(budgets) == 1:
            return SimpleNamespace(stdout=b'QUEUE_DRAIN_FAILED\n', returncode=1)
        raise module.subprocess.TimeoutExpired('docker', timeout)

    def sleep(seconds):
        nonlocal now
        now += seconds

    monkeypatch.setattr(module, '_source', lambda *_: b'fixture')
    monkeypatch.setattr(module.time, 'monotonic', lambda: now)
    monkeypatch.setattr(module.time, 'sleep', sleep)
    monkeypatch.setattr(module.subprocess, 'run', run)
    with pytest.raises(module.PilotAdapterError, match='subprocess deadline'):
        adapter._verify_worker_queue('old_worker', wait_seconds=300)
    assert budgets == [150, 148]


@pytest.mark.parametrize('change', [None, 'expired', 'api_restart', 'worker_restart'])
def test_isolated_health_proof_only_follows_same_running_processes(sample, monkeypatch, change):
    module, adapter, _ = sample
    adapter.image_ids = {'new_api': 'api-image', 'new_worker': 'worker-image'}
    items = {slot: {'Id': slot, 'Image': image, 'RestartCount': 0,
        'State': {'Running': True, 'Restarting': False, 'StartedAt': '2026-11-04T01:00:00Z'}}
        for slot, image in adapter.image_ids.items()}
    adapter._full_inspect = items.__getitem__
    adapter._isolated_generation = (100, adapter._candidate_generation())
    monkeypatch.setattr(module.time, 'monotonic', lambda: 281 if change == 'expired' else 110)
    if change in ('api_restart', 'worker_restart'):
        slot = 'new_' + change.split('_')[0]
        items[slot]['State']['StartedAt'] = '2026-11-04T01:01:00Z'
    if change:
        with pytest.raises(module.PilotAdapterError, match='generation changed or expired'):
            adapter._verify_fresh_isolated_generation()
    else:
        adapter._verify_fresh_isolated_generation()


def test_matching_configuration_does_not_authorize_release(sample):
    module, adapter, _ = sample
    adapter.expected_narration_only = True
    names = {'old_api': 'asb-pilot-api', 'old_worker': 'asb-pilot-worker',
             'new_api': 'asb-narration-next-api', 'new_worker': 'asb-narration-next-worker'}
    adapter.image_ids = {}
    adapter.controls = SimpleNamespace(verify_pinned_images=lambda *_: None)
    adapter.runtime = SimpleNamespace(inspect=lambda ident: {
        'id': ident, 'name': names[ident], 'running': ident.startswith('old_'), 'restart_policy': 'no',
    }, _run=lambda *_: '')
    adapter._ids = lambda _: None
    adapter._verify_configurations = lambda: None
    adapter._verify_monitor_precedes_candidate = lambda: None
    adapter._verify_proxy = lambda: None
    with pytest.raises(module.PilotAdapterError, match='guards are not yet implemented'):
        adapter.preflight(adapter.identities)


@pytest.mark.parametrize(('later_events', 'journal_changes'), [(0, False), (1, False), (0, True)])
def test_migration_requires_exact_privacy_history_after_media_restore(
        sample, monkeypatch, later_events, journal_changes):
    from contextlib import ExitStack, nullcontext
    from unittest.mock import Mock

    module, adapter, _ = sample
    fence = Mock()
    checkpoint = {'event_count': 4, 'journal_sha256': 'a' * 64}
    adapter._preflight_complete = True
    adapter._restore_verified = False
    adapter._quarantine_live = False
    adapter.stack = ExitStack()
    adapter.fence = None
    adapter.backup_arguments = {'store': object(), 'verify_journal': lambda: checkpoint}
    adapter.quarantine_arguments = {}
    adapter.witness_factory = object()
    monkeypatch.setattr(adapter, '_discard_quarantine', lambda: None)
    monkeypatch.setattr(module, 'fenced_backup_probe', lambda **_: nullcontext((fence, {
        'status': 'FENCED_BACKUP_DATABASE_PROBED', 'run_id': 'fixture',
        'manifest_sha256': 'b' * 64, 'revision': 'fixture', 'journal_checkpoint': dict(checkpoint),
        'media_restore_verified': False, 'migration_authorized': False,
    })))
    monkeypatch.setattr(module, 'ingest_verified_backup', lambda **_: {
        'status': 'BACKUP_IMPORTED_QUARANTINED', 'restore_authorized': False,
        'privacy_replay_verified': False,
    })
    monkeypatch.setattr(module, 'restore_in_owned_sandbox', lambda **_: {
        'status': 'DATABASE_AND_MEDIA_RESTORED_QUARANTINED', 'restore_authorized': False,
        'privacy_replay_verified': False,
    })
    monkeypatch.setattr(module, 'prepare_isolated_replay', lambda **_: {
        'status': 'RESTORED_OUTBOX_MATCHES_FENCED_LIVE_HISTORY',
        'target_verified_at_preflight': True, 'backup_event_count': 4,
        'later_event_count': later_events, 'privacy_replay_applied': False,
        'restore_authorized': False,
    })

    with adapter:
        if later_events:
            with pytest.raises(module.PilotAdapterError, match='replay preflight'):
                adapter.backup_and_restore_verify()
            fence.migrate.assert_not_called()
        else:
            assert adapter.backup_and_restore_verify() is True
            if journal_changes:
                checkpoint['journal_sha256'] = 'c' * 64
                with pytest.raises(module.PilotAdapterError, match='journal changed before migration'):
                    adapter.migrate()
                fence.migrate.assert_not_called()
                return
            assert adapter.migrate() is True
            assert fence.migrate.call_args.kwargs['assert_backup_restored']() is True
            fence.commit.assert_called_once_with()


def test_media_rollback_must_match_old_container_except_storage(sample, monkeypatch):
    from copy import deepcopy

    module, adapter, items = sample
    rollback_ids = {'api': 'a' * 64, 'worker': 'b' * 64}
    monkeypatch.setattr(adapter, '_expected_media_changes', lambda _: {
        'S3_BUCKET': 'fixture-target', 'PRIVACY_JOURNAL_WITNESS_BUCKET': 'new-journal',
    })
    adapter.runtime = SimpleNamespace(inspect=lambda name: {'id': rollback_ids[name.rsplit('-', 1)[1]]})
    for role, identifier in rollback_ids.items():
        old = items['old_' + role]
        old['Image'] = 'old-image-' + role
        old['Config'].update(Entrypoint=['python'], Cmd=['fixture'], User='1000')
        old['HostConfig']['PortBindings'] = {}
        candidate = deepcopy(old)
        candidate['Name'] = '/asb-media-rollback-' + role
        candidate['State'] = {'Running': False}
        candidate['HostConfig']['RestartPolicy'] = {'Name': 'no'}
        candidate['HostConfig']['PublishAllPorts'] = False
        candidate['Config']['Env'].append('S3_BUCKET=fixture-target')
        items[identifier] = candidate

    adapter._verify_media_rollback_candidates()
    items[rollback_ids['worker']]['HostConfig']['RestartPolicy']['Name'] = 'always'
    with pytest.raises(module.PilotAdapterError, match='rollback candidates'):
        adapter._verify_media_rollback_candidates()


def test_isolated_candidate_rejects_loopback_port_publication(sample):
    module, adapter, items = sample
    for role in ('api', 'worker'):
        items['new_' + role]['HostConfig'].update(PortBindings={}, PublishAllPorts=False)
    adapter._verify_candidate_ports()
    items['new_api']['HostConfig']['PortBindings'] = {
        '8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18081'}],
    }
    with pytest.raises(module.PilotAdapterError, match='must not publish host ports'):
        adapter._verify_candidate_ports()


def test_service_config_install_restores_prior_generation_on_partial_failure(sample, tmp_path, monkeypatch):
    module, adapter, _ = sample
    monkeypatch.setattr(module, 'PRIVATE_CONFIG_DIR', tmp_path)
    first, second = (tmp_path / name for name in ('backup.env', 'provider.env'))
    for path in (first, second):
        path.write_bytes(b'OLD=1\n')
        path.chmod(0o600)
    real_replace = module.os.replace

    def fail_second_replace(source, destination):
        if destination == second:
            raise OSError('fixture write failure')
        real_replace(source, destination)

    monkeypatch.setattr(module.os, 'replace', fail_second_replace)
    with pytest.raises(OSError, match='fixture write failure'):
        adapter._install_service_configs({path: (b'OLD=1\n', b'NEW=1\n') for path in (first, second)})
    assert {path.name for path in tmp_path.iterdir()} == {first.name, second.name}
    assert all(path.read_bytes() == b'OLD=1\n' for path in (first, second))


def test_storage_only_switch_checks_empty_storage_without_migrating(sample, monkeypatch):
    from unittest.mock import Mock

    module, adapter, _ = sample
    adapter.expected_gcs_media = adapter.storage_only = adapter._preflight_complete = True
    adapter._restore_verified = True
    adapter.fence = Mock()
    source, target = {'S3_BUCKET': 'source'}, {'S3_BUCKET': 'target'}
    adapter._media_cutover = (source, {}, target)
    checkpoint = {'event_count': 4, 'journal_sha256': 'a' * 64}
    adapter.evidence = {'journal_checkpoint': checkpoint}
    adapter.backup_arguments = {'verify_journal': lambda: checkpoint}
    verify = Mock()
    monkeypatch.setattr(module, 'verify_empty_media_detach', verify)
    assert adapter.migrate() is True
    verify.assert_called_once_with(adapter.fence, source, target, expected_revision=module.SOURCE_REVISION)
    adapter.fence.verify_revision.assert_called_once_with(module.SOURCE_REVISION)
    adapter.fence.migrate.assert_not_called()
    adapter.fence.commit.assert_not_called()


def test_retired_media_names_do_not_block_narration_preflight(sample):
    module, adapter, _ = sample
    occupied = {'asb-pilot-api-before-media', 'asb-pilot-worker-before-media'}

    def list_containers(*args):
        assert args[:-1] == ('container', 'ls', '-aq', '--filter')
        return 'owned-fixture-container' if args[-1][7:-1] in occupied else ''

    adapter.runtime = SimpleNamespace(_run=list_containers)
    adapter._verify_retired_names_available()
    adapter.storage_only = True
    with pytest.raises(module.PilotAdapterError, match='already in use'):
        adapter._verify_retired_names_available()


@pytest.mark.parametrize('prefix', ['old_', 'new_'])
def test_storage_generation_starts_worker_only_after_api_is_ready(sample, monkeypatch, prefix):
    module, adapter, _ = sample
    adapter.storage_only = True
    calls = []
    adapter.runtime = SimpleNamespace(_run=lambda *args: calls.append(args), inspect=lambda _: {'running': True})
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)

    def check(api):
        calls.append(('ready', api))
        if calls.count(('ready', api)) == 1:
            raise module.safety.NarrationSafetyError('API is warming up')

    adapter._verify_api_ready = check
    adapter._start_generation(prefix)
    assert calls == [('start', prefix + 'api'), ('ready', prefix + 'api'),
                     ('ready', prefix + 'api'), ('start', prefix + 'worker')]


def test_post_detach_narration_checks_live_api_before_probing_tts(sample, monkeypatch):
    module, adapter, _ = sample
    adapter.gcs_narration = True
    adapter.image_ids = {'new_api': 'candidate-image'}
    calls = []
    adapter.runtime = SimpleNamespace(_run=lambda *args: calls.append(args))
    adapter._verify_api_ready = lambda api, *, live=False: calls.append(('live' if live else 'ready', api))
    monkeypatch.setattr(module, 'bootstrap_isolated_narration',
                        lambda api, image, _ledger: calls.append(('tts', api, image)))

    adapter._start_generation('new_')

    assert calls == [('start', 'new_api'), ('live', 'new_api'), ('tts', 'new_api', 'candidate-image'),
                     ('ready', 'new_api'), ('start', 'new_worker')]


@pytest.mark.parametrize('drift', [None, 'worker_running', 'candidate_renamed', 'different_marker'])
@pytest.mark.parametrize('post_detach', [False, True])
def test_operator_recovery_requires_exact_unpublished_generation(sample, monkeypatch, tmp_path, drift, post_detach):
    import os
    from contextlib import nullcontext
    from unittest.mock import Mock

    module, adapter, _ = sample
    runner = importlib.import_module('run_pilot_media_detach')
    for name in ('STATE', 'BACKUP_STATE', 'PRIVACY_RECOVERY_MARKER', 'PROVIDER_ROTATION_RECOVERY_MARKER'):
        monkeypatch.setattr(runner, name, tmp_path if name in ('STATE', 'BACKUP_STATE') else tmp_path / name)
    monkeypatch.setattr(runner, 'BackupServiceGuard', lambda *_: SimpleNamespace(
        _locked=lambda: os.open(tmp_path, os.O_RDONLY)))
    adapter.storage_only = not post_detach
    adapter.gcs_narration = post_detach
    adapter._verify_stopped_proxy = Mock()
    adapter.resume_original_storage_before_publication = Mock(return_value=True)
    plan = {'containers': adapter.identities, 'images': dict.fromkeys(adapter.identities, 'image'),
            'proxy_id': 'proxy', 'proxy_image_id': 'proxy-image'}
    marker = tmp_path / 'narration-recovery.json'
    marker.write_text('{}')
    recorded = {'version': 3 if drift == 'different_marker' else 2, 'containers': plan['containers'],
                'proxy': {'id': 'proxy', 'image_id': 'proxy-image'}}
    monkeypatch.setattr(module.safety, '_read_recovery_marker', lambda _: recorded)
    quarantine = Mock()
    monkeypatch.setattr(module.safety, 'quarantine', quarantine)
    monkeypatch.setattr(runner, '_adapter', lambda *_, **_kw: nullcontext(adapter))

    def inspect(slot):
        phase, role = slot.split('_')
        name = 'asb-pilot-' + role if phase == 'old' else adapter._staged_name(role)
        if drift == 'candidate_renamed' and slot == 'new_api':
            name = 'asb-pilot-api'
        return {'id': slot, 'name': name, 'image_id': 'image', 'restart_policy': 'no',
                'running': drift == 'worker_running' and slot == 'old_worker'}

    adapter.runtime = SimpleNamespace(inspect=inspect)
    options = {'retired_neon': {}, 'freeze_canary': 'asb-narration-freeze-canary-' + 'c' * 32} if post_detach else {}
    if drift is None or (post_detach and drift == 'worker_running'):
        runner._recover_original(plan, None, **options)
        if post_detach:
            quarantine.assert_not_called()
            adapter.resume_original_storage_before_publication.assert_called_once_with(
                worker_running=drift == 'worker_running')
        else:
            quarantine.assert_called_once_with(tmp_path, adapter.runtime)
            adapter.resume_original_storage_before_publication.assert_called_once_with()
        assert not marker.exists()
    else:
        with pytest.raises(runner.MediaDetachError):
            runner._recover_original(plan, None, **options)
        quarantine.assert_not_called()
        adapter.resume_original_storage_before_publication.assert_not_called()
        assert marker.exists()
