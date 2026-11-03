"""Container restart adapter refuses foreign, running old and unsafe state."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('narration_container_controls')


IDS = dict(zip(('old_api', 'old_worker', 'new_api', 'new_worker'), (c * 64 for c in 'abcd')))


class Runtime:
    def __init__(self):
        names = ('asb-pilot-api-before-narration', 'asb-pilot-worker-before-narration',
                 'asb-narration-next-api', 'asb-narration-next-worker')
        self.items = {identifier: {'id': identifier, 'name': name, 'running': slot.startswith('new_'),
                                   'restart_policy': 'no'}
                      for (slot, identifier), name in zip(IDS.items(), names)}
        self.changed = []

    def inspect(self, identifier):
        return dict(self.items[identifier])

    def disable_restart(self, identifier):
        self.changed.append(identifier)
        self.items[identifier]['restart_policy'] = 'no'

    def enable_restart(self, identifier):
        self.changed.append(identifier)
        self.items[identifier]['restart_policy'] = 'unless-stopped'

    def stop(self, identifier):
        self.changed.append(identifier)
        self.items[identifier]['running'] = False

    def _run(self, *_args):
        return '{"worker@fixture": []}'


def test_disable_checks_all_identities_before_touching_any(module):
    runtime = Runtime()
    runtime.items[IDS['new_worker']]['name'] = 'unrelated-container'
    with pytest.raises(module.ContainerControlError):
        module.NarrationContainerControls(runtime).disable_restart(IDS)
    assert runtime.changed == []


def test_image_identity_verification_fails_before_mutation(module):
    runtime = Runtime()
    expected = {slot: 'sha256:' + 'e' * 64 for slot in IDS}
    for item in runtime.items.values():
        item['image_id'] = 'sha256:' + 'e' * 64
    assert module.NarrationContainerControls(runtime).verify_pinned_images(IDS, expected)
    runtime.items[IDS['new_api']]['image_id'] = 'sha256:' + 'f' * 64
    with pytest.raises(module.ContainerControlError, match='differs from the reviewed image'):
        module.NarrationContainerControls(runtime).verify_pinned_images(IDS, expected)
    assert runtime.changed == []


def test_enable_only_new_images_after_state_checks(module):
    runtime = Runtime()
    control = module.NarrationContainerControls(runtime)
    assert control.enable_new_restart(IDS) is True
    assert set(runtime.changed) == {IDS['new_api'], IDS['new_worker']}
    assert runtime.items[IDS['old_api']]['restart_policy'] == 'no'


def test_enable_refuses_running_old_image_without_mutation(module):
    runtime = Runtime()
    runtime.items[IDS['old_api']]['running'] = True
    with pytest.raises(module.ContainerControlError):
        module.NarrationContainerControls(runtime).enable_new_restart(IDS)
    assert runtime.changed == []


def test_drain_stops_api_then_idle_worker(module):
    runtime = Runtime()
    runtime.items[IDS['old_api']].update(name='asb-pilot-api', running=True)
    runtime.items[IDS['old_worker']].update(name='asb-pilot-worker', running=True)
    assert module.NarrationContainerControls(runtime).stop_and_drain(IDS)
    assert runtime.changed == [IDS['old_api'], IDS['old_worker']]
    assert not runtime.items[IDS['old_worker']]['running']


def test_drain_refuses_busy_worker(module):
    runtime = Runtime()
    runtime.items[IDS['old_api']].update(name='asb-pilot-api', running=True)
    runtime.items[IDS['old_worker']].update(name='asb-pilot-worker', running=True)
    runtime._run = lambda *_args: '{"worker@fixture": [{"id": "busy"}]}'
    with pytest.raises(module.ContainerControlError, match='drain cannot be verified'):
        module.NarrationContainerControls(runtime).stop_and_drain(IDS)
    assert runtime.changed == [IDS['old_api']]
    assert runtime.items[IDS['old_worker']]['running']
