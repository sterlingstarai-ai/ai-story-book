"""Compare the live database outbox to a journal without approving restore.

An exact current match is useful before a quiesced backup. It does not prove
that this DB is authoritative, that every mutation was recorded, that the
external store cannot roll back, or that a later restore can be opened.
"""

from collections import defaultdict
import hashlib
import json
import re

from sqlalchemy import literal, select, text

from src.models.db import PrivacyJournalOutbox
from src.services.privacy_journal import (
    JournalEntry, JournalScan, consent_state_from_payload, consent_state_to_payload,
    credential_state_from_payload, credential_state_to_payload,
    deletion_receipt_from_payload, deletion_receipt_to_payload,
)


class JournalVerificationError(RuntimeError):
    pass


def fingerprint_entries(entries) -> str:
    """Hash full canonical event contents, including sensitive state, without exposing it."""
    try:
        values = list(entries)
        if (any(not isinstance(entry, JournalEntry) for entry in values)
                or len({entry.event_id for entry in values}) != len(values)):
            raise JournalVerificationError('Journal entries are invalid or duplicated')
        ordered = sorted(values, key=lambda item: item.event_id)
        canonical = [{'event_id': entry.event_id, 'action': entry.action, 'subject': entry.subject,
                      'revision': entry.revision, 'credential_state': credential_state_to_payload(entry.credential_state),
                      'resource_id': entry.resource_id, 'consent_state': consent_state_to_payload(entry.consent_state)}
                     for entry in ordered]
        for entry, item in zip(ordered, canonical):
            receipt = deletion_receipt_to_payload(entry.deletion_receipt)
            if receipt is not None:
                if entry.action != 'book_delete':
                    raise JournalVerificationError('Journal receipt action is invalid')
                item['deletion_receipt'] = receipt
        return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    except JournalVerificationError:
        raise
    except Exception:
        raise JournalVerificationError('Journal fingerprint could not be computed') from None


async def verify_backup_checkpoint(db, scan: JournalScan, marker: dict) -> dict:
    """Compare a restored backup's outbox with its separately verified marker.

    This checks only the events included in that backup. A matching checkpoint
    cannot prove that the supplied journal includes later deletions, nor that
    the marker came from an authentic, current provider object.
    """
    if (not isinstance(marker, dict) or marker.get('restore_authorized') is not False
            or type(marker.get('journal_event_count')) is not int or marker['journal_event_count'] < 0
            or not isinstance(marker.get('journal_sha256'), str)
            or not re.fullmatch('[0-9a-f]{64}', marker['journal_sha256'])
            or not isinstance(scan, JournalScan) or scan.restore_authorized is not False
            or type(scan.pending_count) is not int or scan.pending_count != 0):
        raise JournalVerificationError('Backup checkpoint is invalid or incomplete')
    try:
        if (any(not isinstance(entry, JournalEntry) for entry in scan.committed)
                or len({entry.event_id for entry in scan.committed}) != len(scan.committed)):
            raise JournalVerificationError('Journal entries are invalid or duplicated')
        rows = list((await db.scalars(select(PrivacyJournalOutbox.event_id))).all())
        if len(rows) != len(set(rows)) or len(rows) != marker['journal_event_count']:
            raise JournalVerificationError('Backup checkpoint count does not match')
        ids = set(rows)
        subset = tuple(entry for entry in scan.committed if entry.event_id in ids)
        if len(subset) != len(rows):
            raise JournalVerificationError('Backup checkpoint events are missing or duplicated')
        result = await verify_current_outbox(db, JournalScan(subset, 0))
        if result['journal_sha256'] != marker['journal_sha256']:
            raise JournalVerificationError('Backup checkpoint fingerprint does not match')
        return {'status': 'BACKUP_CHECKPOINT_MATCHES', 'event_count': len(rows),
                'restore_authorized': False}
    except JournalVerificationError:
        raise
    except Exception:
        raise JournalVerificationError('Backup checkpoint could not be verified') from None


async def verify_current_outbox(db, scan: JournalScan, *, legacy_source=False) -> dict:
    if (not isinstance(scan, JournalScan) or scan.restore_authorized is not False
            or type(scan.pending_count) is not int or scan.pending_count != 0):
        raise JournalVerificationError('Journal has unresolved records')
    try:
        if legacy_source:
            revision = (await db.execute(text('SELECT version_num FROM public.alembic_version'))).scalars().all()
            if revision != ['5de7a40b6c12']:
                raise JournalVerificationError('Unexpected legacy outbox revision')
            columns = (await db.execute(text("""SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'privacy_journal_outbox'"""))).scalars().all()
            if set(columns) != {'event_id', 'action', 'user_key', 'revision', 'credential_state',
                                'resource_id', 'consent_state', 'created_at', 'published_at'}:
                raise JournalVerificationError('Unexpected legacy outbox columns')
            outbox = PrivacyJournalOutbox
            rows = (await db.execute(select(
                outbox.event_id, outbox.action, outbox.user_key, outbox.revision,
                outbox.credential_state, outbox.resource_id, outbox.consent_state, outbox.published_at,
                literal(None).label('deletion_receipt'),
            ))).all()
        else:
            rows = (await db.scalars(select(PrivacyJournalOutbox))).all()
        expected = {}
        revisions = defaultdict(list)
        for row in rows:
            if row.published_at is None or row.event_id in expected:
                raise JournalVerificationError('Journal publication is incomplete')
            expected[row.event_id] = JournalEntry(row.event_id, row.action, row.user_key, row.revision,
                credential_state_from_payload(row.credential_state), row.resource_id,
                consent_state_from_payload(row.consent_state), deletion_receipt_from_payload(row.deletion_receipt))
            revisions[row.user_key].append(row.revision)
        if any(sorted(values) != list(range(1, len(values) + 1)) for values in revisions.values()):
            raise JournalVerificationError('Journal revision history is incomplete')
        actual = {}
        for entry in scan.committed:
            if not isinstance(entry, JournalEntry) or entry.event_id in actual:
                raise JournalVerificationError('Journal records are invalid')
            actual[entry.event_id] = entry
        if actual != expected:
            raise JournalVerificationError('Journal and database disagree')
        fingerprint = fingerprint_entries(actual.values())
        return {'status': 'CURRENT_OUTBOX_MATCHES_JOURNAL', 'event_count': len(rows),
                'journal_sha256': fingerprint, 'restore_authorized': False}
    except JournalVerificationError:
        raise
    except Exception:
        raise JournalVerificationError('Journal verification could not be completed') from None
