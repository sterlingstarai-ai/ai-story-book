"""Compare a sandboxed backup outbox with its captured checkpoint marker.

Output is consumed only through a private process pipe, never logged. This
proves neither the marker's independence nor that the journal is latest.
"""
from collections import defaultdict
from contextlib import closing
import hmac
import json
import os
from pathlib import Path
import re
import sys

import psycopg2

API = Path('/offline/apps/api')
sys.path.insert(0, str(API))
from src.services.privacy_journal import (  # noqa: E402
    JournalEntry, consent_state_from_payload, credential_state_from_payload, deletion_receipt_from_payload,
)
from quarantined_restore_runtime import ROOT, _assert_local_sandbox  # noqa: E402

MAX_EVENTS = 100000
_PRE_RECEIPT_REVISIONS = frozenset({'5de7a40b6c12', '9c1e3a7f620d', '7e28d9a6b451'})
_RECEIPT_REVISIONS = frozenset({'8a34e19c6b72', 'b3f149ac52d7', 'd52b81c9a734',
                                '4c2d8f71b906', 'e7b93d2a601f'})
_REQUIRED_OUTBOX_COLUMNS = frozenset({'event_id', 'action', 'user_key', 'revision', 'credential_state',
                                      'resource_id', 'consent_state', 'created_at', 'published_at'})


def _outbox_query(revision, columns):
    """Use NULL for a receipt only when the exact revision predates the column."""
    if not isinstance(columns, set):
        raise ValueError('Backup outbox schema is incomplete')
    if revision in _PRE_RECEIPT_REVISIONS and columns == _REQUIRED_OUTBOX_COLUMNS:
        receipt = 'NULL::json AS deletion_receipt'
    elif revision in _RECEIPT_REVISIONS and columns == _REQUIRED_OUTBOX_COLUMNS | {'deletion_receipt'}:
        receipt = 'deletion_receipt'
    else:
        raise ValueError('Backup revision or receipt schema is unsupported')
    return ('SELECT event_id, action, user_key, revision, credential_state, resource_id, '
            f'consent_state, {receipt}, published_at FROM public.privacy_journal_outbox')


def inspect_checkpoint(token):
    _assert_local_sandbox()
    # Importing the shared fingerprint helper also initializes SQLAlchemy's
    # engine objects. Pin their configuration to the isolated target rather
    # than reading any caller-supplied database setting; no engine is used.
    os.environ['DATABASE_URL'] = 'postgresql://sandbox@127.0.0.1:54321/restored'
    os.environ['DATABASE_SSL_MODE'] = 'disable'
    os.environ['DATABASE_SSL_ROOT_CERT'] = ''
    from src.services.privacy_journal_verify import fingerprint_entries
    if not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token):
        raise ValueError('Invalid sandbox identity')
    backup = ROOT / ('ingest-' + token)
    path = backup / 'verified.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError('Backup checkpoint is unavailable')
    marker = json.loads(path.read_bytes())
    manifest_path = backup / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Backup manifest is unavailable')
    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, dict) or not isinstance(manifest.get('alembic_revision'), str):
        raise ValueError('Backup revision is unavailable')
    count, expected = marker.get('journal_event_count'), marker.get('journal_sha256')
    if (marker.get('restore_authorized') is not False or type(count) is not int or not 0 <= count <= MAX_EVENTS
            or not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
        raise ValueError('Backup checkpoint is incomplete')
    events = []
    revisions = defaultdict(list)
    with closing(psycopg2.connect(host='127.0.0.1', port=54321, dbname='restored',
                                  user='sandbox', connect_timeout=5)) as db:
        with db.cursor() as setup:
            setup.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            setup.execute('SELECT version_num FROM public.alembic_version')
            versions = setup.fetchall()
            if len(versions) != 1 or versions[0][0] != manifest['alembic_revision']:
                raise ValueError('Restored database revision does not match backup')
            setup.execute("SELECT column_name FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='privacy_journal_outbox'")
            columns = {row[0] for row in setup.fetchall()}
            query = _outbox_query(versions[0][0], columns)
        with db.cursor(name='asb_backup_outbox_binding') as cursor:
            cursor.itersize = 500
            cursor.execute(query)
            for event_id, action, subject, revision, credential, resource, consent, receipt, published in cursor:
                if published is None or len(events) >= MAX_EVENTS:
                    raise ValueError('Backup journal outbox is incomplete')
                events.append(JournalEntry(event_id, action, subject, revision,
                    credential_state_from_payload(credential), resource,
                    consent_state_from_payload(consent), deletion_receipt_from_payload(receipt)))
                revisions[subject].append(revision)
    if (len(events) != count or len({event.event_id for event in events}) != len(events)
            or any(sorted(values) != list(range(1, len(values) + 1)) for values in revisions.values())
            or not hmac.compare_digest(fingerprint_entries(events), expected)):
        raise ValueError('Backup journal checkpoint does not match')
    return {'status': 'BACKUP_OUTBOX_CHECKPOINT_MATCHES', 'event_ids': sorted(event.event_id for event in events),
            'journal_sha256': expected, 'restore_authorized': False}


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError('Sandbox token is required')
        print(json.dumps(inspect_checkpoint(sys.argv[1]), sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({'status': 'BACKUP_OUTBOX_CHECKPOINT_NOT_VERIFIED', 'restore_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
