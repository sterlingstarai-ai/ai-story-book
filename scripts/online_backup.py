"""Snapshot-bound backup without API/worker shutdown or a bulk write fence.

The short cut may briefly serialize writers. The original offline backup and
latest-deletion/credential replay requirements remain separate and unchanged.
"""

import asyncio
from contextlib import closing
from importlib import import_module
from pathlib import Path
import time
from urllib.parse import urlsplit

from psycopg import sql

from backup_external import create_online_backup, inventory, storage_client
from postgres_backup_fence import OnlineSnapshotCut
from publish_backup_gcs import publish_verified_backup


class OnlineBackupError(RuntimeError):
    pass


_IDLE_QUERY = """SELECT CASE
        WHEN EXISTS (SELECT 1 FROM public.jobs
                     WHERE status IS NULL OR status NOT IN ('done','failed','cancelled')) THEN 'active_jobs'
        WHEN EXISTS (SELECT 1 FROM public.storage_purge_tasks
                     WHERE status IS NULL OR status NOT IN ('done','cancelled')) THEN 'pending_purges'
        WHEN EXISTS (SELECT 1 FROM public.privacy_journal_outbox WHERE published_at IS NULL) THEN 'pending_journal'
        WHEN EXISTS (SELECT 1 FROM public.media_write_intents) THEN 'pending_media'
        ELSE 'idle' END"""
_REVISION_QUERY = 'SELECT version_num FROM public.alembic_version ORDER BY version_num'


def _snapshot_idle(connection):
    state = connection.execute(_IDLE_QUERY).fetchone()
    if state != ('idle',):
        raise OnlineBackupError('A complete idle snapshot cut is not available')


class _FrozenRows:
    def __init__(self, rows):
        self._rows = tuple(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


def _query_key(connection, statement):
    if isinstance(statement, sql.Composable):
        return statement.as_string(connection)
    if isinstance(statement, str):
        return statement
    raise OnlineBackupError('Snapshot prefetch requires an exact known query')


class _SnapshotReadView:
    """Serve exact preloaded S results; never reconnect or issue a new query."""

    def __init__(self, connection, rows):
        self._connection = connection
        self._rows = rows

    @property
    def closed(self):
        return self._connection.closed

    @property
    def info(self):
        return self._connection.info

    def execute(self, statement, parameters=None):
        if self.closed or parameters is not None:
            raise OnlineBackupError('Snapshot prefetch cannot execute a live query')
        key = _query_key(self._connection, statement)
        if key not in self._rows:
            raise OnlineBackupError('Snapshot validation requested an unprefetched query')
        return _FrozenRows(self._rows[key])


def _prefetch_cut_queries(connection, queries, *, column_counts):
    keys = tuple(_query_key(connection, statement) for statement in queries)
    if (not keys or len(keys) != len(set(keys)) or len(column_counts) != len(keys)
            or any(type(count) is not int or not 1 <= count <= 32 for count in column_counts)):
        raise OnlineBackupError('Snapshot prefetch queries must be unique')
    statements = tuple(statement if isinstance(statement, sql.Composable) else sql.SQL(statement)
                       for statement in queries)
    # One SELECT avoids a cross-region proxy round trip per statement. The
    # reviewed queries remain exact subqueries, and positional JSON arrays
    # preserve nulls, integers and nested JSON for the unchanged validators.
    # published_at is the sole timestamp field; its existing check only
    # requires non-null completed publication, never a timestamp watermark.
    aggregates = []
    for statement, count in zip(statements, column_counts, strict=True):
        columns = tuple(sql.Identifier(f'c{index}') for index in range(count))
        aggregates.append(sql.SQL("(SELECT COALESCE(jsonb_agg(jsonb_build_array({})), '[]'::jsonb) "
                                  'FROM ({}) AS q({}))').format(
            sql.SQL(', ').join(columns), statement, sql.SQL(', ').join(columns)))
    cursor = connection.execute(sql.SQL('SELECT {}').format(sql.SQL(', ').join(aggregates)), prepare=False)
    result = cursor.fetchone()
    if (not isinstance(result, tuple) or len(result) != len(keys)
            or cursor.fetchone() is not None or cursor.nextset() is not None):
        raise OnlineBackupError('Snapshot prefetch returned invalid aggregate results')
    rows = {}
    for key, payload, count in zip(keys, result, column_counts, strict=True):
        if not isinstance(payload, list) or any(not isinstance(row, list) or len(row) != count for row in payload):
            raise OnlineBackupError('Snapshot prefetch returned invalid positional rows')
        rows[key] = tuple(tuple(row) for row in payload)
    return _SnapshotReadView(connection, rows)


def prepare_snapshot_validation():
    """Load the selected API's pure validators before holding write locks."""
    import_module('src.services.privacy_journal')
    import_module('src.services.privacy_journal_verify')


def capture_snapshot_boundary(connection, *, values, media_client, native_media, timings_ms=None):
    """Keep only admission checks and the exact T media list under write locks."""
    _snapshot_idle(connection)
    start = time.monotonic_ns()
    frozen = media_client.inventory() if native_media else inventory(media_client, values['S3_BUCKET'])
    if timings_ms is not None:
        timings_ms['snapshot_inventory'] = (time.monotonic_ns() - start) // 1_000_000
    return {'inventory': frozen}


def capture_snapshot_metadata(connection, *, values, scan, media_client, native_media, timings_ms=None,
                              frozen_inventory=None):
    """Read five exact SQL results from S in one round trip, then validate all."""
    from online_media_references import snapshot_media_queries, verify_snapshot_media_coverage
    from online_privacy_checkpoint import _OUTBOX, cut_checkpoint

    start = time.monotonic_ns()
    view = _prefetch_cut_queries(connection, (_IDLE_QUERY, _OUTBOX, _REVISION_QUERY, *snapshot_media_queries()),
                                column_counts=(1, 9, 1, 3, 4))
    if timings_ms is not None:
        timings_ms['snapshot_database_batch'] = (time.monotonic_ns() - start) // 1_000_000
    _snapshot_idle(view)
    checkpoint = cut_checkpoint(view, scan)
    revision = view.execute(_REVISION_QUERY).fetchall()
    if len(revision) != 1 or not isinstance(revision[0][0], str) or not revision[0][0]:
        raise OnlineBackupError('A single schema revision is required')
    start = time.monotonic_ns()
    frozen = frozen_inventory
    if frozen is None:
        frozen = media_client.inventory() if native_media else inventory(media_client, values['S3_BUCKET'])
    if timings_ms is not None and frozen_inventory is None:
        timings_ms['snapshot_inventory'] = (time.monotonic_ns() - start) // 1_000_000
    coverage = verify_snapshot_media_coverage(view, values, frozen)
    return {'checkpoint': checkpoint, 'revision': revision[0][0], 'inventory': frozen, 'coverage': coverage}


def run_online_backup(*, guard, values, environment, ca_file, output_dir, store, run_id,
                      journal, session_factory, verify_bindings, timings_ms=None,
                      snapshot_factory=None, on_snapshot_ready=None, allow_local_fixture=False):
    # These imports must happen after the runner selects the registered source
    # mirror of the actual API image. No alternate API implementation is loaded.
    from online_privacy_checkpoint import verify_online_checkpoint
    prepare_snapshot_validation()

    def timed(name, operation):
        start = time.monotonic_ns()
        try:
            return operation()
        finally:
            if timings_ms is not None:
                timings_ms[name] = timings_ms.get(name, 0) + (time.monotonic_ns() - start) // 1_000_000

    factory = snapshot_factory or (lambda: OnlineSnapshotCut(environment, cut_timeout_seconds=2.0))

    def cycle_with_media(media_client, native_media):
        # Network scans are deliberately outside the short write boundary.
        # If a concurrent commit invalidates this scan, retry a new cut rather
        # than waiting for publication while holding application write locks.
        last_error = None
        for attempt in range(3):
            candidate = factory()
            try:
                scan = timed('privacy_prescan', journal.scan)
                candidate.__enter__()

                def cut(connection):
                    return capture_snapshot_boundary(connection, values=values,
                        media_client=media_client, native_media=native_media, timings_ms=timings_ms)

                boundary = candidate.capture(cut)
                if not candidate.cut_released:
                    raise OnlineBackupError('The write boundary was not released')
                # S2 imported exactly S before the source fence closed. Read
                # large H0/reference payloads from this same read-only holder
                # after release, never from a new/current DB session. No dump,
                # upload, marker or success record occurs before full checks.
                frozen = candidate.read_snapshot(lambda connection: capture_snapshot_metadata(
                    connection, values=values, scan=scan, media_client=media_client,
                    native_media=native_media, timings_ms=timings_ms,
                    frozen_inventory=boundary['inventory']))
                snapshot = candidate
                break
            except BaseException as exc:
                candidate.__exit__(None, None, None)
                if not isinstance(exc, Exception):
                    raise
                last_error = exc
                if attempt < 2:
                    time.sleep(0.25 * (attempt + 1))
        else:
            raise OnlineBackupError('A bounded consistent snapshot cut could not be obtained') from last_error

        try:
            if timings_ms is not None:
                timings_ms['snapshot_cut'] = snapshot.cut_elapsed_ms
            if on_snapshot_ready is not None:
                on_snapshot_ready()
            snapshot.verify()
            result = timed('capture', lambda: create_online_backup(
                values, output_dir, ca_file, snapshot=snapshot,
                frozen_inventory=frozen['inventory'], frozen_revision=frozen['revision'],
                media_download_workers=2,
                media_client=media_client if native_media else None))
            if (not isinstance(result, dict) or result.get('status') != 'BACKUP_CREATED_NOT_RESTORE_VERIFIED'
                    or result.get('capture_mode') != 'online_snapshot'):
                raise OnlineBackupError('The online capture did not complete')
            backup_name = result.get('backup_set')
            if (not isinstance(backup_name, str) or not backup_name.startswith('external-')
                    or Path(backup_name).name != backup_name):
                raise OnlineBackupError('Backup location is invalid')

            def verify_before_marker():
                verify_bindings()
                guard.verify_online_identity()
                snapshot.verify()
                # This reads the same exported S2, never the changing live DB.
                latest = journal.scan()
                asyncio.run(verify_online_checkpoint(
                    session_factory, snapshot.snapshot_id, latest, frozen['checkpoint']))
                snapshot.verify()
                guard.verify_online_identity()

            timed('privacy_checkpoint', verify_before_marker)
            published = timed('publication', lambda: publish_verified_backup(
                Path(output_dir) / backup_name, run_id, store,
                journal_checkpoint=frozen['checkpoint'], verify_before_marker=verify_before_marker,
                media_upload_workers=2))
            return {'status': 'REMOTE_CHECKSUMS_VERIFIED_NOT_RESTORED',
                    'capture_mode': 'online_snapshot', 'services_stopped': False,
                    'object_count': published['object_count'], 'restore_authorized': False,
                    'snapshot_cut_ms': snapshot.cut_elapsed_ms,
                    'snapshot_media_reference_count': frozen['coverage']['reference_count']}
        finally:
            snapshot.__exit__(None, None, None)

    def cycle():
        verify_bindings()
        # Credential/HTTP client setup is outside the bounded write boundary.
        # Production GCS uses exact generation and metadata-generation reads;
        # it never falls back to an unversioned request after a mismatch.
        endpoint = urlsplit(values['S3_ENDPOINT'])
        native = endpoint.hostname == 'storage.googleapis.com'
        if native:
            from online_gcs_media import GCSOnlineMedia
            client = GCSOnlineMedia(values)
        else:
            if (allow_local_fixture is not True or endpoint.scheme != 'http'
                    or endpoint.hostname != '127.0.0.1' or endpoint.username or endpoint.password
                    or not endpoint.port or endpoint.query or endpoint.fragment):
                raise OnlineBackupError('Online production media requires exact object version conditions')
            client = storage_client(values, cut_timeout_seconds=2.0)
        with closing(client):
            return cycle_with_media(client, native)

    return timed('online_cycle', lambda: guard.run_online(backup=cycle))
