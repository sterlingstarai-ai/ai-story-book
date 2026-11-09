"""Legacy recovery must not start through a present or uncheckable marker."""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def guard(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'scripts'))
    return importlib.import_module('narration_marker_exec_condition')


def test_absent_present_and_dangling_marker(guard, tmp_path):
    marker = tmp_path / 'narration-recovery.json'
    assert guard.exit_code(marker) == 0
    marker.write_text('invalid contents still block')
    assert guard.exit_code(marker) == 1
    marker.unlink()
    marker.symlink_to(tmp_path / 'missing')
    assert guard.exit_code(marker) == 1


def test_marker_access_error_fails_unit(guard, monkeypatch, tmp_path):
    def denied(_path):
        raise PermissionError('synthetic')
    monkeypatch.setattr(guard.os, 'lstat', denied)
    assert guard.exit_code(tmp_path / 'marker') == 255


def test_untrusted_state_directory_fails_unit(guard, tmp_path):
    directory = tmp_path / 'world-readable'
    directory.mkdir()
    directory.chmod(0o755)
    assert guard.exit_code(directory / 'narration-recovery.json') == 255
    link = tmp_path / 'state-link'
    link.symlink_to(tmp_path, target_is_directory=True)
    assert guard.exit_code(link / 'narration-recovery.json') == 255


def test_provider_rotation_marker_blocks_legacy_boot_recovery(guard, tmp_path):
    narration = tmp_path / 'narration.json'
    rotation = tmp_path / 'rotation.json'
    assert guard.combined_exit_code(narration, rotation) == 0
    rotation.write_text('invalid marker still blocks')
    assert guard.combined_exit_code(narration, rotation) == 1
    rotation.unlink()
    rotation.symlink_to(tmp_path / 'missing')
    assert guard.combined_exit_code(narration, rotation) == 1


def test_untrusted_provider_marker_parent_fails_even_if_other_marker_present(guard, tmp_path):
    narration = tmp_path / 'narration.json'
    narration.write_text('armed')
    untrusted = tmp_path / 'untrusted'
    untrusted.mkdir()
    untrusted.chmod(0o755)
    assert guard.combined_exit_code(narration, untrusted / 'rotation.json') == 255
