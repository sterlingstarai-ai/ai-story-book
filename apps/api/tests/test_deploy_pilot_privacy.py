"""Recovery after any interrupted two-container swap."""
import importlib.util
import fcntl
import itertools
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("deploy_pilot_privacy", SCRIPTS / "deploy_pilot_privacy.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize("stages", itertools.product(range(3), repeat=2))
def test_partial_swap_rollback(tmp_path, monkeypatch, stages):
    monkeypatch.setattr(m, "STATE", tmp_path)
    monkeypatch.setattr(m, "MARKER", tmp_path / "rollback.json")
    monkeypatch.setattr(m, "BACKUP_STATE", tmp_path)
    old = {m.API: "a" * 64, m.WORKER: "b" * 64}
    new = {m.API: "c" * 64, m.WORKER: "d" * 64}
    state = {}
    for name, stage in zip((m.API, m.WORKER), stages):
        state[old[name]] = {"name": name if stage == 0 else m.OLD[name], "running": False}
        state[new[name]] = {"name": name if stage == 2 else m.NEXT[name], "running": stage == 2}
    m.MARKER.write_text(json.dumps({"version": 1, "old": old, "new": new}))

    def identify(value):
        return value if value in state else next((key for key, item in state.items() if item["name"] == value), None)

    def inspect(value, fmt):
        item = state[identify(value)]
        return "/" + item["name"] if fmt == "{{.Name}}" else str(item["running"]).lower()

    def docker(*args):
        if args[0] == "stop":
            state[identify(args[-1])]["running"] = False
        elif args[0] == "start":
            state[identify(args[-1])]["running"] = True
        elif args[0] == "rename":
            state[identify(args[1])]["name"] = args[2]
        return ""

    monkeypatch.setattr(m, "exists", lambda value: identify(value) is not None)
    monkeypatch.setattr(m, "inspect", inspect)
    monkeypatch.setattr(m, "docker", docker)
    assert m.rollback()
    assert not m.MARKER.exists()
    assert all(state[old[name]] == {"name": name, "running": True} for name in old)
    assert all(state[new[name]] == {"name": m.NEXT[name], "running": False} for name in new)


def test_old_recovery_does_not_restart_while_narration_marker_exists(tmp_path, monkeypatch):
    import backup_service_guard

    monkeypatch.setattr(m, 'MARKER', tmp_path / 'rollback.json')
    monkeypatch.setattr(m, 'BACKUP_STATE', tmp_path)
    monkeypatch.setattr(backup_service_guard, 'NARRATION_RECOVERY_MARKER', tmp_path / 'narration-recovery.json')
    m.MARKER.write_text('{}')
    backup_service_guard.NARRATION_RECOVERY_MARKER.write_text('invalid still fences')
    calls = []
    monkeypatch.setattr(m, 'docker', lambda *args: calls.append(args))
    with pytest.raises(backup_service_guard.GuardError, match='automatic restart blocked'):
        m.rollback()
    assert calls == [] and m.MARKER.exists()


def test_old_recovery_does_not_restart_during_provider_rotation(tmp_path, monkeypatch):
    import backup_service_guard

    monkeypatch.setattr(m, 'MARKER', tmp_path / 'rollback.json')
    monkeypatch.setattr(m, 'BACKUP_STATE', tmp_path)
    monkeypatch.setattr(backup_service_guard, 'NARRATION_RECOVERY_MARKER', tmp_path / 'absent')
    monkeypatch.setattr(backup_service_guard, 'PROVIDER_ROTATION_RECOVERY_MARKER', tmp_path / 'provider-rotation.json')
    m.MARKER.write_text('{}')
    backup_service_guard.PROVIDER_ROTATION_RECOVERY_MARKER.write_text('invalid still fences')
    calls = []
    monkeypatch.setattr(m, 'docker', lambda *args: calls.append(args))
    with pytest.raises(backup_service_guard.GuardError, match='automatic restart blocked'):
        m.rollback()
    assert calls == [] and m.MARKER.exists()


def test_old_recovery_requires_shared_backup_lock(tmp_path, monkeypatch):
    import backup_service_guard

    monkeypatch.setattr(m, 'MARKER', tmp_path / 'rollback.json')
    monkeypatch.setattr(m, 'BACKUP_STATE', tmp_path)
    m.MARKER.write_text('{}')
    with (tmp_path / 'backup.lock').open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(backup_service_guard.GuardError, match='Another backup'):
            m.rollback()
    assert m.MARKER.exists()
