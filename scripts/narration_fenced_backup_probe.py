"""Capture and restore-test a backup while one database fence remains active.

This is a preflight building block, not a deployment. The caller is responsible
for draining all writers and protecting storage and privacy-journal access.
The returned evidence never authorizes migration or recovery.
"""
from contextlib import contextmanager
import hashlib
from pathlib import Path

from backup_external import assert_quiescent, database_environment
from media_cutover_preflight import verify_empty_media_detach, verify_staged_media_cutover
from narration_detach_attestation import issue_restore_challenge, verify_restore_attestation
from narration_release_backup import QUERY, SOURCE_REVISION, capture_quiesced_backup
from narration_restore_probe import probe_database_archive
from narration_transaction_fence import NarrationTransactionFence
from publish_backup_gcs import _valid_checkpoint, verify_remote_backup


class FencedBackupProbeError(RuntimeError):
    pass


@contextmanager
def fenced_backup_probe(*, values, ca_file, output_dir, store, verify_journal, image_id=None,
                        media_cutover=None, media_detach_target=None, offhost_restore=None):
    """Yield limited evidence with the same DB fence still active.

    Consumers must establish independent external writer, privacy replay,
    media restore, and boot controls before considering any migration.
    """
    environment = database_environment(values, ca_file)
    if media_cutover is not None and media_detach_target is not None:
        raise FencedBackupProbeError('Specify one media transition')
    if offhost_restore is not None and (media_detach_target is None or image_id is not None):
        raise FencedBackupProbeError('An off-host attestation is scoped to storage detach')
    with NarrationTransactionFence(environment) as fence:
        def verify_media():
            if media_cutover is not None:
                verify_staged_media_cutover(fence, values, *media_cutover)
            if media_detach_target is not None:
                verify_empty_media_detach(fence, values, media_detach_target, expected_revision=SOURCE_REVISION)

        verify_media()
        checkpoint = verify_journal()
        if not _valid_checkpoint(checkpoint):
            raise FencedBackupProbeError('Current privacy journal is unverified')
        checkpoint = dict(checkpoint)
        backup = capture_quiesced_backup(values=values, ca_file=ca_file, output_dir=output_dir,
                                          store=store, verify_journal=verify_journal, fence=fence,
                                          verify_empty_media=verify_media if media_detach_target is not None else None)
        folder = Path(output_dir) / backup['backup_set']
        # The exact manifest checked remotely must be the one used by the
        # isolated local restore, not a later substituted local backup.
        remote_manifest = store.read_small('backups/v1/' + backup['run_id'] + '/manifest.json',
                                           16 * 1024 * 1024)
        if remote_manifest != (folder / 'manifest.json').read_bytes():
            raise FencedBackupProbeError('Local and remote backup manifests differ')
        manifest_digest = hashlib.sha256(remote_manifest).hexdigest()
        if offhost_restore is None:
            result = probe_database_archive(folder, image_id=image_id, expected_revision=SOURCE_REVISION)
            if (result.get('status') != 'OFFLINE_DATABASE_RESTORED'
                    or result.get('revision') != SOURCE_REVISION
                    or result.get('restore_authorized') is not False
                    or result.get('migration_authorized') is not False):
                raise FencedBackupProbeError('Isolated database restore is unverified')
        else:
            public_key, attest = offhost_restore
            challenge = issue_restore_challenge(run_id=backup['run_id'], manifest_sha256=manifest_digest,
                revision=SOURCE_REVISION, journal_checkpoint=checkpoint)
            # Give the transport a copy. It cannot change the expected nonce,
            # archive or journal after the challenge is issued.
            signature = attest(dict(challenge))
            verify_restore_attestation(challenge, signature, public_key=public_key)
        fence.verify()
        assert_quiescent(environment, QUERY)
        if verify_journal() != checkpoint:
            raise FencedBackupProbeError('Privacy journal changed during restore probe')
        remote = verify_remote_backup(backup['run_id'], store, expected_revision=SOURCE_REVISION,
                                      expected_journal_checkpoint=checkpoint)
        if (remote.get('status') != 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED'
                or remote.get('restore_authorized') is not False
                or remote_manifest != store.read_small('backups/v1/' + backup['run_id'] + '/manifest.json',
                                                       16 * 1024 * 1024)):
            raise FencedBackupProbeError('Remote backup changed during restore probe')
        fence.verify()
        verify_media()
        yield fence, {'status': ('FENCED_BACKUP_OFFHOST_RESTORE_VERIFIED' if offhost_restore is not None
                                 else 'FENCED_BACKUP_DATABASE_PROBED'), 'run_id': backup['run_id'],
                      'revision': SOURCE_REVISION, 'manifest_sha256': manifest_digest,
                      'journal_checkpoint': checkpoint, 'media_restore_verified': offhost_restore is not None,
                      'restore_authorized': False, 'migration_authorized': False}


def capture_and_probe(**kwargs):
    """Perform the preflight and release the fence; never authorizes migration."""
    with fenced_backup_probe(**kwargs) as (_, evidence):
        return evidence
