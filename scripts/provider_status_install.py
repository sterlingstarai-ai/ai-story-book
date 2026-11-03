"""Install the pinned backup monitor update with resumable atomic replacement."""
from __future__ import annotations

import argparse
import json
import os
import re
import uuid

import provider_activate_guard as core
import provider_activate_production as production
import provider_install_stage as staging
from provider_cutover_production_guards import verify_installed_guard_files, verify_loaded_units

NAME = 'check_backup_status.py'
OLD = 'f40c28e9e28efa36c85304d5f392dadef444df8131363ed00a600d15cead871d'
NEW = '1549a5146ead147ba55c341844709c369361c46e468d468eb03803431e9be3ea'
TOKEN = re.compile(r'[0-9a-f]{32}\Z')


class StatusInstallError(RuntimeError):
    pass


def _source():
    production._read_release(production.PINNED_RELEASE, production.PINNED_READY_SHA)
    fd = production._root(production.PINNED_RELEASE, private=True)
    try:
        data = staging._read_file(fd, 'cutover/' + NAME)
        if core._sha(data) != NEW:
            raise StatusInstallError('Pinned status monitor differs')
        return data
    finally:
        os.close(fd)


def _metadata(digest):
    return {'sha256': digest, 'mode': 0o644, 'uid': 0, 'gid': 0}


def _guard_checks():
    verify_installed_guard_files()
    verify_loaded_units(production.systemd.show)


def _replace(fd, source, token):
    before = core._read_at(fd, NAME)
    if core._describe(before) != _metadata(OLD):
        raise StatusInstallError('Original monitor differs')
    temporary = '.' + NAME + '.status-' + token
    pending = core._read_at(fd, temporary, absent=True)
    if pending is None:
        core._write_new(fd, temporary, source, 0o644)
    elif pending[0] != source:
        info = pending[1]
        # An interruption can leave only a prefix of this transaction's file.
        # Remove it only when the name, owner, mode, bytes and inode all match.
        if (info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o777 not in (0o600, 0o644)
                or not source.startswith(pending[0])):
            raise StatusInstallError('Monitor temporary differs')
        current = os.stat(temporary, dir_fd=fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise StatusInstallError('Monitor temporary changed')
        os.unlink(temporary, dir_fd=fd)
        os.fsync(fd)
        core._write_new(fd, temporary, source, 0o644)
    elif core._describe(pending) != _metadata(NEW):
        raise StatusInstallError('Monitor temporary differs')
    current = os.stat(NAME, dir_fd=fd, follow_symlinks=False)
    if (before[1].st_dev, before[1].st_ino) != (current.st_dev, current.st_ino):
        raise StatusInstallError('Original monitor changed')
    os.replace(temporary, NAME, src_dir_fd=fd, dst_dir_fd=fd)
    os.fsync(fd)


def run(mode, *, after_replace=None):
    if mode not in ('preflight', 'execute', 'recover'):
        raise StatusInstallError('Unsupported mode')
    production.verify_instance()
    identity = production._current_identity()
    source = _source()
    locks = ()
    active = state = None
    try:
        locks = production._open_locks()
        for marker in production.BLOCKERS:
            production._absent(marker)
        production._absent(production.STATE / 'systemd-op.json')
        production._pin_current(identity)
        _guard_checks()
        active = production._root(production.SCRIPTS, private=False)
        state = production._root(production.STATE, private=True)
        original = core._read_at(active, NAME)
        before = core._describe(original)
        if mode != 'recover':
            if core._read_at(state, 'activation.json', absent=True) is not None:
                raise StatusInstallError('Prior installation is unresolved')
            if before != _metadata(OLD):
                raise StatusInstallError('Original monitor differs')
            if mode == 'preflight':
                return {'status': 'STATUS_PREFLIGHT_PASSED', 'production_changed': False}
            token = uuid.uuid4().hex
            snapshot_name = 'status-old-' + token
            core._write_new(state, snapshot_name, original[0], 0o600)
            os.fsync(state)
            snapshot = core._read_at(state, snapshot_name)
            if core._sha(snapshot[0]) != OLD or snapshot[1].st_mode & 0o777 != 0o600:
                raise StatusInstallError('Monitor original snapshot differs')
            record = {'version': 1, 'kind': 'backup-monitor', 'transaction': token,
                      'current_identity': list(identity), 'old': OLD, 'new': NEW}
            raw = (json.dumps(record, sort_keys=True) + '\n').encode()
            core._write_matching_record(state, 'activation.json', raw)
        else:
            raw = core._read_at(state, 'activation.json')[0]
            record = json.loads(raw)
            if (not isinstance(record, dict) or set(record) !=
                    {'version', 'kind', 'transaction', 'current_identity', 'old', 'new'}
                    or record['version'] != 1 or record['kind'] != 'backup-monitor'
                    or not isinstance(record['transaction'], str) or not TOKEN.fullmatch(record['transaction'])
                    or record['current_identity'] != list(identity) or record['old'] != OLD or record['new'] != NEW):
                raise StatusInstallError('Monitor recovery record differs')
            token = record['transaction']
            snapshot = core._read_at(state, 'status-old-' + token)
            if core._sha(snapshot[0]) != OLD or snapshot[1].st_mode & 0o777 != 0o600:
                raise StatusInstallError('Monitor original snapshot differs')
            if before not in (_metadata(OLD), _metadata(NEW)):
                raise StatusInstallError('Monitor target changed outside transaction')
        production._pin_current(identity)
        if before == _metadata(OLD):
            _replace(active, source, token)
        if after_replace is not None:
            after_replace()
        if core._describe(core._read_at(active, NAME)) != _metadata(NEW):
            raise StatusInstallError('Monitor update not verified')
        production._pin_current(identity)
        _guard_checks()
        core._write_matching_record(state, 'status-verified-' + token + '.json', raw)
        os.unlink('activation.json', dir_fd=state)
        os.fsync(state)
        return {'status': 'STATUS_INSTALLED', 'production_changed': True}
    finally:
        if state is not None:
            os.close(state)
        if active is not None:
            os.close(active)
        production._close_all(list(locks))


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--preflight', action='store_true')
    actions.add_argument('--execute', action='store_true')
    actions.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(run('preflight' if args.preflight else 'recover' if args.recover else 'execute')))
    except Exception:
        print(json.dumps({'status': 'STATUS_INSTALLATION_UNCONFIRMED', 'activation_marker_state': 'unknown'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
