"""Read-only audit of explicitly owned pre-ledger IAP SSH operations.

Unknown journal directories, partial records, unavailable GCE operations,
changed metadata fingerprints, or a remaining owned SSH row all block.
This does not cover future concurrent writers or close any legacy journal.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

try:
    from scripts.gcp_ssh_recovery_journal import RecoveryJournal
    from scripts.provider_iap_reconcile import (
        INSTANCE, INSTANCE_ID, PROJECT, ZONE, ReconcileError, _metadata_view, _valid_entry, _valid_operation,
    )
except ModuleNotFoundError:
    from gcp_ssh_recovery_journal import RecoveryJournal
    from provider_iap_reconcile import (
        INSTANCE, INSTANCE_ID, PROJECT, ZONE, ReconcileError, _metadata_view, _valid_entry, _valid_operation,
    )


class LegacyAuditError(RuntimeError):
    pass


# Only directories whose ownership was confirmed in this work session. Any new
# or unknown directory is deliberately rejected until separately investigated.
_OWNED_SUFFIXES = frozenset({
    '1sufxopc', '4d5aslrg', '4ifvmzd0', '6mw0t0mf', '6n9qnzs5', '6nspfuh6', '6qd1a0n8', '7sz20dds', 'axut213i', 'govmtffb', 'h9xf0z3e',
    'iiy9kiee', 'im3qzmxx', 'kc9ipy62', 'lehw03hx', 'm_kv7_do', 'mokump_q', 'nvw83c66', 'qcq70xd7', 'qme26tnt',
    'rkhn0f8p', 's0w8oz_w', 'sziwrogv', 'tn0d11cl', 'tvbi42xm', 'u4__307k', 'uzt2wlpa', 'w60adm0d', 'wau3yh7c', 'wotv21ec', 'y2quosh2', 'yzn89q_4',
})
_PREFIX = 'asb-ssh-recovery-'
_RECORD = re.compile(r'([0-9a-f]{32})\.(intent|started|operation)\.json\Z')
_FINGERPRINT = re.compile(r'[A-Za-z0-9_+/=-]{1,256}\Z')


def audit_owned_legacy_journals(*, client, root='/Users/jmac/.codex', _expected=None):
    """Verify exact known journals and fixed GCE operations without changing either.

    `_expected` exists solely to exercise isolated fixtures; production callers
    must use the fixed default. The result contains counts, never entry contents.
    """
    expected = _OWNED_SUFFIXES if _expected is None else frozenset(_expected)
    try:
        path = Path(root)
        info = path.lstat()
        if (not path.is_absolute() or path.resolve(strict=True) != path or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise ValueError()
        present = {x.name[len(_PREFIX):] for x in path.iterdir() if x.name.startswith(_PREFIX)}
        if present != expected:
            raise LegacyAuditError('Unknown or missing IAP legacy journal')
        before = client.metadata()
        metadata = before.get('metadata') if isinstance(before, dict) else None
        fingerprint = metadata.get('fingerprint') if isinstance(metadata, dict) else None
        if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
            raise ValueError()
        operations = 0
        for suffix in sorted(expected):
            directory = path / (_PREFIX + suffix)
            with RecoveryJournal(str(directory)) as journal:
                initial = os.fstat(journal._dir)
                files = set(os.listdir(journal._dir))
                parsed = [_RECORD.fullmatch(name) for name in files]
                if not parsed or any(match is None for match in parsed):
                    raise ValueError()
                identifiers = {match.group(1) for match in parsed}
                for identifier in identifiers:
                    intent = journal._read(identifier, 'intent')
                    started = journal._read(identifier, 'started')
                    operation = journal._read(identifier, 'operation')
                    if (not intent or not started or not operation
                            or set(intent) != {'version', 'id', 'kind', 'project', 'zone', 'instance', 'owned_entry'}
                            or set(started) != {'version', 'id', 'kind', 'request_id'}
                            or set(operation) != {'version', 'id', 'kind', 'operation'}
                            or (intent.get('project'), intent.get('zone'), intent.get('instance')) != (PROJECT, ZONE, INSTANCE)
                            or not _valid_entry(intent.get('owned_entry'))
                            or not isinstance(operation.get('operation'), str)
                            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', operation['operation'])):
                        raise ValueError()
                    state = client.operation(operation['operation'])
                    if (not _valid_operation(state, started.get('request_id'), operation['operation'])
                            or state['status'] != 'DONE' or 'error' in state
                            or _metadata_view(before, intent['owned_entry'], fingerprint)['owned_entry_count'] != 0):
                        raise ValueError()
                    operations += 1
                final = os.fstat(journal._dir)
                if (files != set(os.listdir(journal._dir)) or any(getattr(initial, name) != getattr(final, name)
                        for name in ('st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns'))):
                    raise ValueError()
        after = client.metadata()
        after_metadata = after.get('metadata') if isinstance(after, dict) else None
        if (not isinstance(after, dict) or str(after.get('id')) != INSTANCE_ID
                or after.get('name') != INSTANCE or not isinstance(after_metadata, dict)
                or after_metadata.get('fingerprint') != fingerprint):
            raise ValueError()
        if {x.name[len(_PREFIX):] for x in path.iterdir() if x.name.startswith(_PREFIX)} != expected:
            raise ValueError()
        return {'sessions_confirmed': len(expected), 'operations_confirmed': operations,
                'submitted_fingerprints_recorded': False}
    except (LegacyAuditError, ReconcileError):
        raise
    except Exception:
        raise LegacyAuditError('Earlier IAP operations remain unconfirmed') from None
