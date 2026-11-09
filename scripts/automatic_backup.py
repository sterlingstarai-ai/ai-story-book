"""One guarded backup cycle; not a scheduler or a restore approval.

The caller must supply real service-drain and journal-verification callbacks,
durable private storage, least-privilege credentials, boot recovery and alerts.
"""

from pathlib import Path
import re
from time import monotonic_ns

from publish_backup_gcs import publish_verified_backup


class AutomaticBackupError(RuntimeError):
    pass


def run_guarded_backup(*, guard, verify_idle, verify_journal, output_dir, store, run_id, take_backup=None,
                       preflight_idle=None, publication_boundary=None, media_upload_workers=1, timings_ms=None):
    """Fail closed on changing or incomplete privacy records and restart services."""
    if (take_backup is None) == (publication_boundary is None):
        raise AutomaticBackupError('Exactly one capture path is required')

    def timed(name, operation):
        if timings_ms is None:
            return operation()
        start = monotonic_ns()
        try:
            return operation()
        finally:
            elapsed = (monotonic_ns() - start) // 1_000_000
            timings_ms[name] = timings_ms.get(name, 0) + elapsed

    # This check is only an optimization: admission and workers can change
    # immediately afterward. The guard must still stop admission and call
    # verify_idle again before stopping the worker or reading the backup.
    if preflight_idle is not None:
        timed('preflight_idle', preflight_idle)
    def create_and_publish():
        if publication_boundary is None:
            return capture_and_publish(take_backup, None)
        with publication_boundary() as (capture, verify):
            return capture_and_publish(capture, verify)

    def capture_and_publish(capture, verify_boundary):
        before = timed('privacy_checkpoint', verify_journal)
        if (not isinstance(before, dict) or before.get('status') != 'CURRENT_OUTBOX_MATCHES_JOURNAL'
                or before.get('restore_authorized') is not False
                or type(before.get('event_count')) is not int or before['event_count'] < 0
                or not isinstance(before.get('journal_sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', before['journal_sha256'])):
            raise AutomaticBackupError('Privacy journal has not been reconciled')
        result = timed('capture', capture)
        if not isinstance(result, dict) or result.get('status') != 'BACKUP_CREATED_NOT_RESTORE_VERIFIED':
            raise AutomaticBackupError('Backup creation did not complete')
        backup_name = result.get('backup_set')
        if not isinstance(backup_name, str) or not backup_name.startswith('external-') or Path(backup_name).name != backup_name:
            raise AutomaticBackupError('Backup location is invalid')
        if verify_boundary is None and timed('privacy_checkpoint', verify_journal) != before:
            raise AutomaticBackupError('Privacy records changed during backup')
        def verify_before_marker():
            if timed('privacy_checkpoint', verify_journal) != before:
                raise AutomaticBackupError('Privacy records changed during publication')
            if verify_boundary is not None:
                timed('final_storage_fence', lambda: verify_boundary(result))

        published = timed('publication', lambda: publish_verified_backup(
            Path(output_dir) / backup_name, run_id, store, journal_checkpoint=before,
            verify_before_marker=verify_before_marker, media_upload_workers=media_upload_workers))
        return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED',
                'object_count': published['object_count'], 'restore_authorized': False}

    return timed('guarded_cycle', lambda: guard.run(
        verify_idle=lambda: timed('guarded_idle', verify_idle), backup=create_and_publish))
