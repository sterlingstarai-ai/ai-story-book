"""One-time pre-migration backup for the exact legacy pilot schema.

The caller must stop API and drain/stop worker. This cannot be used once the
privacy migration exists, never approves restore, and never changes the DB.
"""

from backup_external import BackupError, create_backup, run_pg

_LEGACY_REVISION = b'2a8d9e4f610b'


def assert_legacy_quiescent(environment, query):
    revision = run_pg(query + ['SELECT version_num FROM public.alembic_version ORDER BY version_num'], environment).strip()
    outbox = run_pg(query + ["SELECT to_regclass('public.privacy_journal_outbox') IS NULL"], environment).strip()
    active = run_pg(query + ["SELECT count(*) FROM public.jobs WHERE status IN ('queued','running')"], environment).strip()
    purges = run_pg(query + ["SELECT count(*) FROM public.storage_purge_tasks WHERE status NOT IN ('done','cancelled')"], environment).strip()
    if revision != _LEGACY_REVISION or outbox != b't' or active != b'0' or purges != b'0':
        raise BackupError('Legacy bootstrap preconditions are not met')


def create_pre_migration_backup(values, destination, ca_file, *, fence=None):
    return create_backup(values, destination, ca_file, quiescence_check=assert_legacy_quiescent, fence=fence)
