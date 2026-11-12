"""Bind online backup privacy checks to an imported PostgreSQL snapshot.

API imports are intentionally lazy: the scheduler first selects the same pinned
API source mirror as its live writers. These checks never publish journal data,
approve restoration, or substitute a historical checkpoint for latest history.
"""

from collections import defaultdict
from collections.abc import Mapping
import hmac
import re


class OnlinePrivacyCheckpointError(RuntimeError):
    pass


_SNAPSHOT = re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{8}-[1-9][0-9]{0,9}')
_HASH = re.compile(r'[0-9a-f]{64}')
_FIELDS = ('event_id', 'action', 'user_key', 'revision', 'credential_state',
           'resource_id', 'consent_state', 'deletion_receipt', 'published_at')
_OUTBOX = 'SELECT ' + ', '.join(_FIELDS) + ' FROM public.privacy_journal_outbox'


def cut_checkpoint(connection, scan0) -> dict:
    """Compare every row of the caller's active fenced snapshot with scan0.

    The caller owns the real source fence and snapshot handoff. A scan from an
    earlier instant is accepted only if its entire canonical contents still
    exactly match this snapshot, including completed publication and revisions.
    """
    try:
        from psycopg.pq import TransactionStatus
        from src.services.privacy_journal import (
            JournalEntry, JournalScan, consent_state_from_payload,
            credential_state_from_payload, deletion_receipt_from_payload,
        )
        from src.services.privacy_journal_verify import fingerprint_entries

        if connection.closed or connection.info.transaction_status != TransactionStatus.INTRANS:
            raise OnlinePrivacyCheckpointError('An active source snapshot transaction is required')
        if (not isinstance(scan0, JournalScan) or scan0.restore_authorized is not False
                or type(scan0.pending_count) is not int or scan0.pending_count != 0):
            raise OnlinePrivacyCheckpointError('The source journal scan is incomplete')
        expected = {}
        revisions = defaultdict(list)
        for row in connection.execute(_OUTBOX).fetchall():
            if isinstance(row, Mapping):
                if set(row) != set(_FIELDS):
                    raise OnlinePrivacyCheckpointError('The source outbox row is invalid')
                values = tuple(row[name] for name in _FIELDS)
            else:
                values = tuple(row)
            if len(values) != len(_FIELDS):
                raise OnlinePrivacyCheckpointError('The source outbox row is invalid')
            event_id, action, subject, revision, credential, resource, consent, receipt, published = values
            if (published is None or event_id in expected or type(revision) is not int or revision < 1):
                raise OnlinePrivacyCheckpointError('The source outbox publication is incomplete')
            expected[event_id] = JournalEntry(
                event_id, action, subject, revision, credential_state_from_payload(credential),
                resource, consent_state_from_payload(consent), deletion_receipt_from_payload(receipt),
            )
            revisions[subject].append(revision)
        if any(sorted(values) != list(range(1, len(values) + 1)) for values in revisions.values()):
            raise OnlinePrivacyCheckpointError('The source outbox revision history is incomplete')
        actual = {}
        for entry in scan0.committed:
            if not isinstance(entry, JournalEntry) or entry.event_id in actual:
                raise OnlinePrivacyCheckpointError('The source journal contains invalid or duplicate events')
            actual[entry.event_id] = entry
        if actual != expected:
            raise OnlinePrivacyCheckpointError('The source snapshot and journal do not match')
        digest = fingerprint_entries(expected.values())
        if not hmac.compare_digest(digest, fingerprint_entries(actual.values())):
            raise OnlinePrivacyCheckpointError('The source snapshot canonical contents do not match')
        return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'event_count': len(expected),
                'journal_sha256': digest, 'restore_authorized': False}
    except OnlinePrivacyCheckpointError:
        raise
    except Exception:
        raise OnlinePrivacyCheckpointError('The source snapshot checkpoint could not be verified') from None


def _marker(checkpoint):
    if (not isinstance(checkpoint, dict) or set(checkpoint) != {
            'status', 'event_count', 'journal_sha256', 'restore_authorized',
        } or checkpoint.get('status') != 'CURRENT_OUTBOX_MATCHES_JOURNAL'
            or checkpoint.get('restore_authorized') is not False
            or type(checkpoint.get('event_count')) is not int or checkpoint['event_count'] < 0
            or not isinstance(checkpoint.get('journal_sha256'), str)
            or not _HASH.fullmatch(checkpoint['journal_sha256'])):
        raise OnlinePrivacyCheckpointError('The captured privacy checkpoint is invalid')
    return {'journal_event_count': checkpoint['event_count'],
            'journal_sha256': checkpoint['journal_sha256'], 'restore_authorized': False}


async def verify_online_checkpoint(session_factory, snapshot_id: str, scan_latest, checkpoint: dict) -> dict:
    """Import S2 before any query, then use the unchanged full checkpoint check.

    The exporting holder must remain alive; this function never reconnects or
    falls back to the current database view when importing the snapshot fails.
    Later history is allowed only under verify_backup_checkpoint's existing
    pending, membership, publication, revision and canonical-content checks.
    """
    if not isinstance(snapshot_id, str) or not _SNAPSHOT.fullmatch(snapshot_id):
        raise OnlinePrivacyCheckpointError('The exported snapshot identifier is invalid')
    marker = _marker(checkpoint)
    try:
        from sqlalchemy import text
        from src.services.privacy_journal_verify import verify_backup_checkpoint

        async with session_factory() as db:
            if db.in_transaction() or db.get_bind().dialect.name != 'postgresql':
                raise OnlinePrivacyCheckpointError('A fresh PostgreSQL snapshot session is required')
            async with db.begin():
                # Override even an AUTOCOMMIT engine before obtaining a DB
                # transaction; importing after an ordinary SELECT is forbidden.
                await db.connection(execution_options={'isolation_level': 'REPEATABLE READ'})
                await db.execute(text('SET TRANSACTION READ ONLY'))
                # SET TRANSACTION SNAPSHOT requires a literal, not a bind
                # parameter. Only the exact exported-token grammar is allowed.
                await db.execute(text("SET TRANSACTION SNAPSHOT '" + snapshot_id + "'"))
                modes = (await db.execute(text(
                    "SELECT current_setting('transaction_isolation'), current_setting('transaction_read_only')"
                ))).one()
                if tuple(modes) != ('repeatable read', 'on'):
                    raise OnlinePrivacyCheckpointError('The imported snapshot transaction is not read-only repeatable read')
                result = await verify_backup_checkpoint(db, scan_latest, marker)
                if result != {'status': 'BACKUP_CHECKPOINT_MATCHES',
                              'event_count': checkpoint['event_count'], 'restore_authorized': False}:
                    raise OnlinePrivacyCheckpointError('The imported snapshot checkpoint did not match')
                return result
    except OnlinePrivacyCheckpointError:
        raise
    except Exception:
        raise OnlinePrivacyCheckpointError('The imported snapshot checkpoint could not be verified') from None
