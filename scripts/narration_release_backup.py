"""Backup building block for a drained narration release; not a deploy command.

Caller must hold the production backup lock, persist the narration recovery
marker, prevent all application and external writes, and stop the API/worker.
This function does not establish those conditions or verify an isolated restore.
Its successful result must never be treated as permission to migrate.
"""
from contextlib import nullcontext
from pathlib import Path
import re
import uuid

from backup_external import (
    assert_quiescent, create_backup, database_environment, inventory,
    inventory_fingerprint, run_pg, storage_client,
)
from postgres_backup_fence import PostgresBackupFence
from publish_backup_gcs import _valid_checkpoint, publish_verified_backup, verify_remote_backup

SOURCE_REVISION = '5de7a40b6c12'
QUERY = ['psql', '-X', '--no-password', '--tuples-only', '--no-align', '--set', 'ON_ERROR_STOP=1', '-c']


class NarrationBackupError(RuntimeError):
    pass


def capture_quiesced_backup(*, values, ca_file, output_dir, store, verify_journal, fence=None,
                            verify_empty_media=None):
    """Create and independently recheck remote bytes, retaining the DB fence.

    `verify_journal` must independently compare current outbox to the protected
    journal; it is not sufficient to read the checkpoint from this backup.
    No restore or release is authorized by this method's return value.
    """
    environment = database_environment(values, ca_file)
    assert_quiescent(environment, QUERY)
    before = verify_journal()
    if not _valid_checkpoint(before):
        raise NarrationBackupError('Current privacy journal cannot be verified')
    before = dict(before)
    output_dir = Path(output_dir)
    run_id = uuid.uuid4().hex
    if fence is not None and getattr(fence, 'environment', None) != environment:
        raise NarrationBackupError('Backup and migration database identities differ')
    manager = PostgresBackupFence(environment) if fence is None else nullcontext(fence)
    with manager as fence:
        fence.verify()
        revision = run_pg(QUERY + ['SELECT version_num FROM public.alembic_version ORDER BY version_num'], environment).strip()
        if revision != SOURCE_REVISION.encode():
            raise NarrationBackupError('Unexpected source database revision')
        result = create_backup(values, output_dir, ca_file, fence=fence)
        name = result.get('backup_set') if isinstance(result, dict) else None
        if (not isinstance(name, str) or not re.fullmatch(r'external-[A-Za-z0-9_-]+', name)
                or result.get('status') != 'BACKUP_CREATED_NOT_RESTORE_VERIFIED'):
            raise NarrationBackupError('Backup creation did not complete')
        if verify_empty_media is not None and (
                type(result.get('object_count')) is not int or result['object_count'] != 0
                or result.get('media_inventory_sha256') != inventory_fingerprint({})):
            raise NarrationBackupError('Media appeared during the storage detach backup')
        fence.verify()
        if verify_journal() != before:
            raise NarrationBackupError('Privacy journal changed during backup')

        def verify_before_marker():
            fence.verify()
            assert_quiescent(environment, QUERY)
            if verify_journal() != before:
                raise NarrationBackupError('Privacy journal changed before backup completion')
            if verify_empty_media is not None:
                verify_empty_media()
                return
            client = storage_client(values)
            try:
                current_media = inventory_fingerprint(inventory(client, values['S3_BUCKET']))
            finally:
                client.close()
            if current_media != result.get('media_inventory_sha256'):
                raise NarrationBackupError('Media inventory changed before backup completion')

        published = publish_verified_backup(Path(output_dir) / name, run_id, store,
                                            journal_checkpoint=before, verify_before_marker=verify_before_marker)
        if (published.get('status') != 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED'
                or published.get('restore_authorized') is not False):
            raise NarrationBackupError('Backup publication is unverified')
        verified = verify_remote_backup(run_id, store, expected_revision=SOURCE_REVISION,
                                        expected_journal_checkpoint=before)
        if (verified.get('status') != 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED'
                or verified.get('restore_authorized') is not False):
            raise NarrationBackupError('Remote backup verification failed')
        fence.verify()
        assert_quiescent(environment, QUERY)
        if verify_journal() != before:
            raise NarrationBackupError('Privacy journal changed during publication')
    return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED', 'run_id': run_id,
            'backup_set': name, 'revision': SOURCE_REVISION,
            'restore_authorized': False, 'migration_authorized': False}
