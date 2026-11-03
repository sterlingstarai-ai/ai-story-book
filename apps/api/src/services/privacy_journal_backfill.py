"""Copy an immutable encrypted journal to a second store under a writer fence.

Callers must independently stop or fence every source writer and verify the
source's authoritative identity. This helper never deletes either copy and
never authorizes a restore or enables mirroring in a running application.
"""
import hmac

from src.services.privacy_journal import JournalError

_PREFIX = 'privacy-journal/v1/'


def backfill_fenced_journal(source, witness):
    """Idempotently create matching witness objects; reject any discrepancy."""
    if source is witness:
        raise JournalError('A separate witness store is required')
    try:
        source_names = source.list_names(_PREFIX)
        witness_names = witness.list_names(_PREFIX)
        if (not isinstance(source_names, list) or not isinstance(witness_names, list)
                or any(not isinstance(name, str) or not name.startswith(_PREFIX) for name in source_names + witness_names)
                or len(source_names) != len(set(source_names))
                or len(witness_names) != len(set(witness_names))
                or not set(witness_names).issubset(set(source_names))):
            raise JournalError('Journal backfill listings are inconsistent')
        for name in sorted(source_names):
            value = source.read(name)
            if not isinstance(value, bytes) or not value:
                raise JournalError('Journal source record is invalid')
            try:
                witness.create(name, value)
            except Exception:
                # An existing immutable matching record is safe on retry. A
                # timeout, missing object or conflicting content is not.
                existing = witness.read(name)
                if not isinstance(existing, bytes) or not hmac.compare_digest(existing, value):
                    raise JournalError('Journal witness record differs')
        source_after, witness_after = source.list_names(_PREFIX), witness.list_names(_PREFIX)
        if (not isinstance(source_after, list) or not isinstance(witness_after, list)
                or len(source_after) != len(set(source_after)) or len(witness_after) != len(set(witness_after))
                or set(source_after) != set(source_names) or set(witness_after) != set(source_names)):
            raise JournalError('Journal changed during backfill')
        for name in source_names:
            left, right = source.read(name), witness.read(name)
            if not isinstance(left, bytes) or not isinstance(right, bytes) or not hmac.compare_digest(left, right):
                raise JournalError('Journal witness verification failed')
        return {'status': 'BACKFILL_MATCHES', 'object_count': len(source_names),
                'restore_authorized': False}
    except JournalError:
        raise
    except Exception:
        raise JournalError('Journal backfill could not be completed') from None
