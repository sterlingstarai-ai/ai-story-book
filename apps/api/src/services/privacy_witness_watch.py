"""Fail-closed observation of a caller-supplied independent witness anchor.

This only checks a fenced source snapshot against the supplied anchor. It does
not prove the anchor is current, independently administered, or recoverable.
It never authorizes restore and emits no raw provider errors or personal data.
"""
import hmac

from src.services.privacy_checkpoint_head import _reference, verify_anchored_checkpoint
from src.services.privacy_journal import JournalError
from src.services.privacy_restore_source_guard import hold_consistent_source
from src.services.privacy_witness_receipt import sign_receipt


async def assess_witness(db, journal, head_store, checkpoint_store, *, namespace,
                         head_key, checkpoint_key, trusted_head, now, max_age,
                         legacy_source=False, freeze_tables=False):
    try:
        if (not isinstance(head_key, bytes) or not isinstance(checkpoint_key, bytes)
                or len(head_key) != 32 or len(checkpoint_key) != 32
                or hmac.compare_digest(head_key, checkpoint_key)
                or head_store is checkpoint_store or not _reference(trusted_head)):
            raise ValueError('Separate witness materials required')
        async with hold_consistent_source(db, journal, legacy_source=legacy_source,
                                          freeze_tables=freeze_tables) as (source, scan):
            observed_at = now() if callable(now) else now
            observed = verify_anchored_checkpoint(head_store, checkpoint_store, scan,
                namespace=namespace, head_key=head_key, checkpoint_key=checkpoint_key,
                candidate_head=trusted_head, trusted_head=trusted_head, now=observed_at, max_age=max_age)
            # A valid older prefix is not a healthy current snapshot. This
            # cannot detect newer events that have already disappeared from
            # all source copies together with the independently held anchor.
            if (observed['journal_count'] != observed['checkpoint_count']
                    or observed['journal_count'] != source['event_count']):
                raise ValueError('Anchor does not cover current source')
        return {'status': 'SNAPSHOT_MATCHES', 'restore_authorized': False}
    except Exception:
        return {'status': 'ALERT', 'restore_authorized': False}


async def observe_and_sign(db, journal, head_store, checkpoint_store, *, namespace,
                           head_key, checkpoint_key, trusted_head, now, max_age, signing_key,
                           legacy_source=False):
    """Issue a receipt only after the supplied anchor covers the fenced source."""
    if not _reference(trusted_head):
        raise JournalError('Witness reference is invalid')
    trusted_head = dict(trusted_head)
    observed_at = now() if callable(now) else now
    observation = await assess_witness(db, journal, head_store, checkpoint_store, namespace=namespace,
        head_key=head_key, checkpoint_key=checkpoint_key, trusted_head=trusted_head,
        now=observed_at, max_age=max_age, legacy_source=legacy_source, freeze_tables=True)
    return sign_receipt(signing_key, namespace=namespace, head=trusted_head,
                        observed_at=observed_at, observation=observation)
