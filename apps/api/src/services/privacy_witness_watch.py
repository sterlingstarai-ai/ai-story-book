"""Fail-closed observation of a caller-supplied independent witness anchor.

This only checks a fenced source snapshot against the supplied anchor. It does
not prove the anchor is current, independently administered, or recoverable.
It never authorizes restore and emits no raw provider errors or personal data.
"""
import hmac

from src.services.privacy_checkpoint_head import _reference, verify_anchored_checkpoint
from src.services.privacy_restore_source_guard import hold_consistent_source


async def assess_witness(db, journal, head_store, checkpoint_store, *, namespace,
                         head_key, checkpoint_key, trusted_head, now, max_age):
    try:
        if (not isinstance(head_key, bytes) or not isinstance(checkpoint_key, bytes)
                or len(head_key) != 32 or len(checkpoint_key) != 32
                or hmac.compare_digest(head_key, checkpoint_key)
                or head_store is checkpoint_store or not _reference(trusted_head)):
            raise ValueError('Separate witness materials required')
        async with hold_consistent_source(db, journal) as (source, scan):
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
