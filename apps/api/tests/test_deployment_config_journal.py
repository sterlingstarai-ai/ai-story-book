"""Synthetic env-file crash/recovery checks; no host settings or credentials."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[3] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
j = importlib.import_module('deployment_config_journal')


@pytest.fixture
def config(tmp_path, monkeypatch):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    paths = (private / 'provider-refresh.env', private / 'pilot.env')
    old = {path: f'SYNTHETIC_OLD={index}\n'.encode() for index, path in enumerate(paths)}
    new = {path: f'SYNTHETIC_NEW={index}\n'.encode() for index, path in enumerate(paths)}
    for path, data in old.items():
        path.write_bytes(data)
        path.chmod(0o600)
    state = tmp_path / 'state'
    state.mkdir(mode=0o700)
    monkeypatch.setattr(j, 'ENV_PATHS', paths)
    monkeypatch.setattr(j, '_ROOT_UID', os.geteuid())
    return j.DeploymentConfigJournal(state / 'config-journal'), old, new


def test_prepare_apply_and_idempotent_restore_preserve_metadata(config):
    journal, old, new = config
    metadata = {path: path.stat() for path in old}
    pin = journal.prepare(new)
    assert all(path.read_bytes() == data for path, data in old.items())
    assert hashlib.sha256(journal.path.read_bytes()).hexdigest() == pin
    assert stat.S_IMODE(journal.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(journal.path.stat().st_mode) == 0o600
    journal.apply(new, expected_sha256=pin)
    assert all(path.read_bytes() == data for path, data in new.items())
    assert journal.restore(expected_sha256=pin)
    assert journal.restore(expected_sha256=pin)
    for path, data in old.items():
        assert path.read_bytes() == data
        value = path.stat()
        assert (value.st_uid, value.st_gid, stat.S_IMODE(value.st_mode)) == (
            metadata[path].st_uid, metadata[path].st_gid, stat.S_IMODE(metadata[path].st_mode))
    assert journal.path.exists()  # The marker commit point belongs to the caller.


def test_crash_between_two_configuration_writes_is_recoverable(config, monkeypatch):
    journal, old, new = config
    pin = journal.prepare(new)
    atomic = j._atomic
    second = list(new)[1]

    def crash(path, *args, **kwargs):
        if path == second:
            raise OSError('synthetic power loss before second file')
        return atomic(path, *args, **kwargs)

    monkeypatch.setattr(j, '_atomic', crash)
    with pytest.raises(OSError):
        journal.apply(new, expected_sha256=pin)
    assert list(new)[0].read_bytes() == new[list(new)[0]]
    assert second.read_bytes() == old[second]
    monkeypatch.setattr(j, '_atomic', atomic)
    journal.restore(expected_sha256=pin)
    assert all(path.read_bytes() == data for path, data in old.items())


def test_crash_during_restore_can_retry_without_losing_rollback_data(config, monkeypatch):
    journal, old, new = config
    pin = journal.prepare(new)
    journal.apply(new, expected_sha256=pin)
    atomic = j._atomic

    def crash(path, *args, **kwargs):
        if path == list(new)[1]:
            raise OSError('synthetic interrupted restore')
        return atomic(path, *args, **kwargs)

    monkeypatch.setattr(j, '_atomic', crash)
    with pytest.raises(OSError):
        journal.restore(expected_sha256=pin)
    assert journal.path.exists()
    monkeypatch.setattr(j, '_atomic', atomic)
    journal.restore(expected_sha256=pin)
    assert all(path.read_bytes() == data for path, data in old.items())


@pytest.mark.parametrize('operation', ['apply', 'restore'])
def test_unknown_second_file_hash_blocks_every_replacement(config, operation):
    journal, old, new = config
    pin = journal.prepare(new)
    journal.apply(new, expected_sha256=pin)
    second = list(new)[1]
    second.write_bytes(b'SYNTHETIC_INDEPENDENT_OPERATOR_CHANGE=1\n')
    before = {path: path.read_bytes() for path in new}
    with pytest.raises(j.JournalError, match='outside this deployment'):
        if operation == 'apply':
            journal.apply(new, expected_sha256=pin)
        else:
            journal.restore(expected_sha256=pin)
    assert {path: path.read_bytes() for path in new} == before
    assert journal.path.exists()


@pytest.mark.parametrize('damage', ['directory', 'journal-file', 'target-file', 'journal-symlink',
                                   'target-symlink', 'directory-symlink', 'truncated', 'unknown-file'])
def test_missing_partial_or_symlink_state_fails_closed(config, damage):
    journal, _old, new = config
    pin = journal.prepare(new)
    journal.apply(new, expected_sha256=pin)
    first = list(new)[0]
    if damage == 'directory':
        journal.path.unlink()
        journal.directory.rmdir()
    elif damage == 'journal-file':
        journal.path.unlink()
    elif damage == 'target-file':
        first.unlink()
    elif damage == 'journal-symlink':
        copied = journal.directory.parent / 'copy.json'
        journal.path.rename(copied)
        journal.path.symlink_to(copied)
    elif damage == 'target-symlink':
        copied = first.parent / 'copy.env'
        first.rename(copied)
        first.symlink_to(copied)
    elif damage == 'directory-symlink':
        moved = journal.directory.with_name('moved')
        journal.directory.rename(moved)
        journal.directory.symlink_to(moved, target_is_directory=True)
    elif damage == 'truncated':
        journal.path.write_bytes(b'{"version":')
    elif damage == 'unknown-file':
        (journal.directory / 'unexpected').write_bytes(b'synthetic')
    before = {path: path.read_bytes() for path in new if path.exists()}
    with pytest.raises((j.JournalError, OSError)):
        journal.restore(expected_sha256=pin)
    assert {path: path.read_bytes() for path in new if path.exists()} == before


@pytest.mark.parametrize('damage', ['hash', 'previous-bytes', 'allowlist', 'duplicate', 'uid', 'mode'])
def test_journal_schema_and_previous_bytes_are_verified(config, damage):
    journal, _old, new = config
    journal.prepare(new)
    data = json.loads(journal.path.read_bytes())
    entry = data['files'][0]
    if damage == 'hash':
        entry['previous_sha256'] = '0' * 64
    elif damage == 'previous-bytes':
        entry['previous_b64'] = 'invalid!'
    elif damage == 'allowlist':
        entry['path'] = '/tmp/unapproved.env'
    elif damage == 'duplicate':
        data['files'][1] = dict(entry)
    elif damage == 'uid':
        entry['uid'] += 1
    elif damage == 'mode':
        entry['mode'] = 0o644
    encoded = json.dumps(data).encode()
    journal.path.write_bytes(encoded)
    pin = hashlib.sha256(encoded).hexdigest()
    with pytest.raises(j.JournalError, match='contents are invalid'):
        journal.restore(expected_sha256=pin)


def test_wrong_pin_or_unbound_journal_cannot_restore(config):
    journal, _old, new = config
    journal.prepare(new)
    with pytest.raises(j.JournalError, match='pin does not match'):
        journal.restore(expected_sha256='0' * 64)
    with pytest.raises(j.JournalError, match='not bound'):
        journal.restore()


def test_legacy_without_journal_is_compatible(config):
    journal, _old, _new = config
    assert journal.restore() is False
    assert journal.discard_committed() is False


def test_committed_leftovers_never_restore_even_an_unknown_live_hash(config):
    journal, _old, new = config
    pin = journal.prepare(new)
    journal.apply(new, expected_sha256=pin)
    list(new)[1].write_bytes(b'SYNTHETIC_LATER_COMMITTED_CHANGE=1\n')
    before = {path: path.read_bytes() for path in new}
    assert journal.discard_committed()
    assert {path: path.read_bytes() for path in new} == before
    assert not journal.directory.exists()


def test_committed_empty_directory_cleanup_can_resume(config):
    journal, old, new = config
    journal.prepare(new)
    journal.path.unlink()  # Simulate interruption between unlink and rmdir.
    assert journal.discard_committed()
    assert all(path.read_bytes() == data for path, data in old.items())


def test_prepare_never_overwrites_pending_journal_or_accepts_other_paths(config):
    journal, _old, new = config
    with pytest.raises(j.JournalError, match='allowlisted'):
        journal.prepare({Path('/tmp/other.env'): b'synthetic'})
    assert not journal.directory.exists()
    journal.prepare(new)
    previous = journal.path.read_bytes()
    with pytest.raises(j.JournalError, match='already exists'):
        journal.prepare(new)
    assert journal.path.read_bytes() == previous


def test_apply_requires_exact_prepared_intent(config):
    journal, old, new = config
    pin = journal.prepare(new)
    wrong = {path: b'SYNTHETIC_UNREVIEWED=1\n' for path in new}
    with pytest.raises(j.JournalError, match='intended update'):
        journal.apply(wrong, expected_sha256=pin)
    assert all(path.read_bytes() == data for path, data in old.items())


def test_metadata_change_fails_closed(config):
    journal, _old, new = config
    pin = journal.prepare(new)
    list(new)[1].chmod(0o400)
    with pytest.raises(j.JournalError, match='outside this deployment'):
        journal.restore(expected_sha256=pin)


def test_nonroot_and_nonprivate_directory_are_rejected(config, monkeypatch):
    journal, _old, new = config
    monkeypatch.setattr(j, '_ROOT_UID', os.geteuid() + 1)
    with pytest.raises(j.JournalError, match='requires root'):
        journal.prepare(new)
    monkeypatch.setattr(j, '_ROOT_UID', os.geteuid())
    journal.directory.parent.chmod(0o755)
    with pytest.raises(j.JournalError, match='directory is unsafe'):
        journal.prepare(new)
