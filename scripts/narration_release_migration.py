"""Exact-revision migration building block; not an independent deploy command.

The trusted caller must already have established persistent admission and
external-writer fencing, hold the shared backup lock, verify the exact fresh
backup by an isolated restore, and install/test boot quarantine. The callback
below must actively recheck those conditions; a boolean is not evidence of
them. This module cannot establish or attest the caller's security boundary.
"""
import os
from pathlib import Path
import stat
import subprocess
import sys

from sqlalchemy.engine import make_url

from backup_external import assert_quiescent, database_environment, run_pg
from narration_release_backup import QUERY, SOURCE_REVISION

API = Path(__file__).resolve().parents[1] / 'apps' / 'api'
TARGET_REVISION = 'f32a7b4d190c'


class NarrationMigrationError(RuntimeError):
    pass


def apply_migration(*, values, ca_file, assert_release_safety):
    """Apply only the pinned additive target, or fail without auto-rollback.

    A failure or interruption may have committed DDL. Caller must retain its
    recovery marker and quarantine services, then inspect the actual revision.
    """
    try:
        ca_file = Path(ca_file)
        info = ca_file.lstat()
        if (values.get('DATABASE_SSL_MODE') != 'verify-full' or not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise NarrationMigrationError('Verified database TLS is required')
        raw_url = values.get('DATABASE_MIGRATION_URL') or values.get('DATABASE_URL')
        if not raw_url:
            raise NarrationMigrationError('Direct database connection is required')
        if raw_url.startswith('postgres://'):
            raw_url = 'postgresql://' + raw_url[len('postgres://'):]
        parsed_url = make_url(raw_url)
        if parsed_url.get_backend_name() != 'postgresql':
            raise NarrationMigrationError('PostgreSQL connection is required')
        normalized_url = parsed_url.difference_update_query(['sslrootcert']).render_as_string(hide_password=False)
        environment = database_environment(values, ca_file)
        if assert_release_safety() is not True:
            raise NarrationMigrationError('Release safety cannot be verified')
        assert_quiescent(environment, QUERY)
        revision_query = QUERY + ['SELECT version_num FROM public.alembic_version ORDER BY version_num']
        if run_pg(revision_query, environment).strip() != SOURCE_REVISION.encode():
            raise NarrationMigrationError('Unexpected source database revision')
        if assert_release_safety() is not True:
            raise NarrationMigrationError('Release safety cannot be reverified')
        # No credentials appear on the process command line or in its output.
        child_env = dict(os.environ)
        child_env.update(DATABASE_URL=normalized_url, DATABASE_MIGRATION_URL=normalized_url,
                         DATABASE_SSL_MODE='verify-full', DATABASE_SSL_ROOT_CERT=str(ca_file),
                         TESTING='false', DEBUG='false', PYTHONPATH=str(API))
        # The Linux helper arms PR_SET_PDEATHSIG before exec so an abruptly
        # killed orchestrator cannot leave an Alembic child running silently.
        helper = Path(__file__).resolve().parent / 'linux_parent_death_exec.py'
        process = subprocess.run([sys.executable, str(helper), str(os.getpid()), '--',
                                  sys.executable, '-m', 'alembic', 'upgrade', TARGET_REVISION],
                                 cwd=API, env=child_env, capture_output=True, timeout=1800)
        actual_revision = run_pg(revision_query, environment).strip()
        if process.returncode != 0 or actual_revision != TARGET_REVISION.encode():
            raise NarrationMigrationError('Migration failed or final revision is unverified')
        if assert_release_safety() is not True:
            raise NarrationMigrationError('Release safety was lost during migration')
        return {'status': 'MIGRATION_APPLIED', 'revision': TARGET_REVISION,
                'restore_authorized': False}
    except NarrationMigrationError:
        raise
    except Exception:
        # Provider and subprocess exceptions can contain connection credentials.
        raise NarrationMigrationError('Migration failed or could not be verified') from None
