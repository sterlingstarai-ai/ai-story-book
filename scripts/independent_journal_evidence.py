"""Verify an independently supplied witness anchor without authorizing restore.

This is a verification adapter, not a source-of-truth or a completeness proof.
The caller must establish independently that the key, receipt, anchor and
stores are authentic, separately administered, and represent the latest head.
"""
from pathlib import Path
import sys

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from src.services.privacy_checkpoint_head import verify_anchored_checkpoint  # noqa: E402
from src.services.privacy_journal import JournalScan, PrivacyJournal  # noqa: E402
from src.services.privacy_witness_receipt import verify_receipt  # noqa: E402
from replay_privacy_journal import plan_quarantined_replay  # noqa: E402


class IndependentJournalEvidenceError(RuntimeError):
    pass


def _verified_witnessed_scan(*, journal, head_store, checkpoint_store, public_key, receipt,
                             namespace, trusted_head, candidate_head, head_key, checkpoint_key,
                             now, max_age, require_full_coverage=False):
    """Authenticate an observed anchor and matching committed journal prefix.

    A valid signed historical receipt does not demonstrate that no newer
    deletion, consent withdrawal or credential revocation exists. Successful
    return deliberately retains `latest_head_verified=False`.
    """
    if (not isinstance(journal, PrivacyJournal) or journal._store is head_store
            or journal._store is checkpoint_store or head_store is checkpoint_store):
        raise IndependentJournalEvidenceError('Distinct journal and witness stores are required')
    try:
        signed = verify_receipt(public_key, receipt, namespace=namespace,
                                trusted_head=trusted_head, now=now, max_age=max_age)
        if (signed.get('status') != 'SIGNED_OBSERVATION_VALID'
                or signed.get('restore_authorized') is not False):
            raise IndependentJournalEvidenceError('Witness receipt is unverified')
        scan = journal.scan()
        if (not isinstance(scan, JournalScan) or scan.restore_authorized is not False
                or type(scan.pending_count) is not int or scan.pending_count != 0):
            raise IndependentJournalEvidenceError('Journal scan is incomplete')
        plan = plan_quarantined_replay(scan)
        if (plan.get('status') != 'JOURNAL_STRUCTURE_VALIDATED'
                or plan.get('latest_head_verified') is not False
                or plan.get('privacy_replay_authorized') is not False):
            raise IndependentJournalEvidenceError('Journal structure is invalid')
        result = verify_anchored_checkpoint(head_store, checkpoint_store, scan,
            namespace=namespace, head_key=head_key, checkpoint_key=checkpoint_key,
            candidate_head=candidate_head, trusted_head=trusted_head, now=now, max_age=max_age)
        if (result.get('status') != 'ANCHORED_WITNESSED_PREFIX_MATCHES'
                or result.get('restore_authorized') is not False):
            raise IndependentJournalEvidenceError('Journal checkpoint is unverified')
        if (require_full_coverage is True and result.get('checkpoint_count') != result.get('journal_count')):
            raise IndependentJournalEvidenceError('Signed checkpoint does not cover all scanned events')
        return scan
    except IndependentJournalEvidenceError:
        raise
    except Exception:
        # Provider payloads, object names, subject IDs and key material remain
        # private even when a store or cryptographic check fails.
        raise IndependentJournalEvidenceError('Journal witness could not be verified') from None


def verify_witnessed_journal(**arguments):
    """Report authenticated prefix only; never certify current completeness."""
    _verified_witnessed_scan(**arguments)
    return {'status': 'WITNESSED_JOURNAL_PREFIX_VERIFIED', 'latest_head_verified': False,
            'privacy_replay_authorized': False, 'restore_authorized': False}
