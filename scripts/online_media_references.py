"""Read media references from the caller's PostgreSQL snapshot, without I/O.

This checks coverage, not an object's generation or provider-side write fence.
The caller owns the transaction and the frozen inventory; no new connection,
commit, storage request, or project settings import is performed here.
"""

import json
import re
from urllib.parse import unquote, urlsplit

from psycopg import sql


class MediaCoverageError(RuntimeError):
    pass


URL_COLUMNS = frozenset({
    ('jobs', 'character_reference_url'),
    ('books', 'cover_image_url'), ('books', 'pdf_url'), ('books', 'audio_url'),
    ('narration_variants', 'audio_url'),
    ('pages', 'image_url'), ('pages', 'audio_url'),
    ('pages', 'audio_url_ko'), ('pages', 'audio_url_en'),
    ('characters', 'source_image_url'), ('characters', 'avatar_url'),
    ('child_profiles', 'avatar_url'), ('voice_profiles', 'sample_audio_url'),
    ('branch_story_nodes', 'image_url'), ('pronunciation_logs', 'audio_url'),
})
JSON_COLUMNS = frozenset({('jobs', 'image_keys'), ('books', 'learning_assets')})
_OWNERSHIP_COLUMNS = frozenset({('jobs', 'user_key'), ('storage_purge_tasks', 'user_key'),
                              ('storage_purge_tasks', 'kind'), ('storage_purge_tasks', 'target'),
                              ('storage_purge_tasks', 'status')})
_URL_TYPE = frozenset({'text', 'character varying'})
_JSON_TYPE = frozenset({'json', 'jsonb'})
_MAX_JSON_NODES = 100_000
_MAX_KEY_LENGTH = 1024
_MEDIA_NAME = re.compile(r'(^|_)(image|audio|video|media|asset|file|attachment|thumbnail)(_|$)')
_REF_NAME = re.compile(r'_(?:url(?:_[a-z]{2})?|uri|path|keys?|assets)$')
_SCHEMA_QUERY = """SELECT table_name, column_name, data_type
        FROM information_schema.columns WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position"""


def _valid_key(value):
    if (not isinstance(value, str) or not value or len(value.encode('utf-8')) > _MAX_KEY_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or any(part in {'', '.', '..'} for part in value.split('/'))):
        raise MediaCoverageError('A snapshot media key is invalid')
    return value


def _url(value):
    try:
        parsed = urlsplit(value)
        parsed.port
        if (parsed.username is not None or parsed.password is not None
                or not parsed.hostname or any(character.isspace() for character in value)):
            raise ValueError
        return parsed
    except (TypeError, ValueError, UnicodeError):
        raise MediaCoverageError('A snapshot media URL is invalid') from None


def _bases(values):
    bucket = values.get('S3_BUCKET')
    if not isinstance(bucket, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{1,221}[A-Za-z0-9]', bucket):
        raise MediaCoverageError('Snapshot storage identity is missing')
    result = []
    public = [values.get('S3_PUBLIC_URL', ''),
              *(values.get('S3_LEGACY_PUBLIC_URLS') or '').split(',')]
    for value in public:
        if value and value.strip():
            result.append(value.strip().rstrip('/') + '/')
    for name in ('S3_ENDPOINT', 'S3_DOWNLOAD_ENDPOINT'):
        endpoint = values.get(name) or ''
        if endpoint:
            result.append(endpoint.rstrip('/') + '/' + bucket + '/')
            if values.get('S3_ADDRESSING_STYLE', 'path') in {'virtual', 'auto'}:
                parsed = _url(endpoint)
                result.append(parsed._replace(netloc=bucket + '.' + parsed.netloc,
                                              path=parsed.path.rstrip('/') + '/').geturl())
    if not result:
        raise MediaCoverageError('Snapshot storage URL mappings are missing')
    parsed_bases = []
    for value in dict.fromkeys(result):
        parsed = _url(value)
        if parsed.scheme not in {'http', 'https'} or parsed.query or parsed.fragment:
            raise MediaCoverageError('Snapshot storage URL mapping is invalid')
        parsed_bases.append(parsed)
    return bucket, tuple(parsed_bases)


def _key_from_url(value, bucket, bases):
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise MediaCoverageError('A snapshot media URL has an unexpected type')
    parsed = _url(value)
    if parsed.scheme == 's3':
        if parsed.netloc != bucket or parsed.query or parsed.fragment:
            raise MediaCoverageError('A snapshot media reference uses unsupported storage')
        return _valid_key(unquote(parsed.path.lstrip('/')))
    if parsed.scheme not in {'http', 'https'}:
        raise MediaCoverageError('A snapshot media reference uses an unsupported scheme')
    for base in bases:
        if ((parsed.scheme, parsed.netloc) == (base.scheme, base.netloc)
                and parsed.path.startswith(base.path)):
            return _valid_key(unquote(parsed.path[len(base.path):]))
    # Existing books may contain external placeholder/provider URLs. They are
    # not objects in this backup bucket; do not reinterpret them as S3 keys.
    return None


def _schema(connection):
    rows = connection.execute(_SCHEMA_QUERY).fetchall()
    observed = {}
    for table, column, kind in rows:
        pair = (table, column)
        if pair in observed:
            raise MediaCoverageError('Snapshot media schema is ambiguous')
        observed[pair] = kind
        candidate = (bool(re.search(r'_(url(?:_[a-z]{2})?|uri)$', column))
                     or bool(_MEDIA_NAME.search(column) and _REF_NAME.search(column)))
        if candidate and pair not in URL_COLUMNS | JSON_COLUMNS:
            raise MediaCoverageError('An unsupported media reference column requires review')
    if (not (URL_COLUMNS | JSON_COLUMNS) <= observed.keys()
            or any(observed[pair] not in _URL_TYPE for pair in URL_COLUMNS)
            or any(observed[pair] not in _JSON_TYPE for pair in JSON_COLUMNS)
            or not _OWNERSHIP_COLUMNS <= observed.keys()
            or any(observed[pair] not in _URL_TYPE for pair in _OWNERSHIP_COLUMNS)):
        raise MediaCoverageError('Snapshot media schema coverage is incomplete')


def _json_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, RecursionError):
            raise MediaCoverageError('Snapshot media JSON is invalid') from None
    return value


def _learning_urls(value):
    """Inspect the existing nested JSON without importing application settings."""
    stack = [value]
    count = 0
    while stack:
        count += 1
        if count > _MAX_JSON_NODES:
            raise MediaCoverageError('Snapshot media JSON exceeds inspection bounds')
        item = stack.pop()
        if isinstance(item, dict):
            for name, child in item.items():
                if not isinstance(name, str):
                    raise MediaCoverageError('Snapshot media JSON is invalid')
                # LearningAssets has no raw object-key fields today. A future
                # key/path representation must add a reviewed parser first.
                if _MEDIA_NAME.search(name) and re.search(r'_(keys?|path|assets)$', name):
                    raise MediaCoverageError('Unsupported nested media reference requires review')
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and item.startswith(('https://', 'http://', 's3://')):
            yield item
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise MediaCoverageError('Snapshot media JSON is invalid')


def _reference_query():
    selects = []
    for table, column in sorted(URL_COLUMNS | JSON_COLUMNS):
        owner = sql.Identifier('user_key') if (table, column) == ('jobs', 'image_keys') else sql.SQL('NULL::text')
        selects.append(sql.SQL('SELECT {} AS source_table, {} AS source_column, to_jsonb({}) AS value, {} AS owner '
                               'FROM {} WHERE {} IS NOT NULL').format(
            sql.Literal(table), sql.Literal(column), sql.Identifier(column),
            owner, sql.Identifier('public', table), sql.Identifier(column)))
    selects.append(sql.SQL("SELECT 'storage_purge_tasks', 'completed_purge', "
                           "jsonb_build_object('kind',kind,'target',target,'status',status), user_key "
                           "FROM public.storage_purge_tasks WHERE status IS DISTINCT FROM 'cancelled'"))
    return sql.SQL(' UNION ALL ').join(selects)


def snapshot_media_queries():
    """Expose the exact two reads for same-snapshot pipeline prefetching.

    This constructs SQL only. Callers must retain the actual snapshot and
    route these unchanged query results back through the existing validators.
    """
    return _SCHEMA_QUERY, _reference_query()


def _snapshot_references(connection, values):
    bucket, bases = _bases(values)
    _schema(connection)
    keys = set()
    history = set()
    purges = []
    # All 17 fields use one round trip to the same snapshot. Do not make the
    # short cut pay one network round trip for every media column.
    for table, column, value, owner in connection.execute(_reference_query()):
        if (table, column) == ('storage_purge_tasks', 'completed_purge'):
            if (not isinstance(value, dict) or value.get('status') != 'done'
                    or value.get('kind') not in {'keys', 'prefix'} or not isinstance(value.get('target'), str)):
                raise MediaCoverageError('Snapshot purge completion is invalid or incomplete')
            target = value['target']
            if value['kind'] == 'prefix':
                if not target.endswith('/'):
                    raise MediaCoverageError('Snapshot purge prefix is ambiguous')
                _valid_key(target[:-1])
            else:
                _valid_key(target)
                if target.startswith(('[', '{')):
                    raise MediaCoverageError('Snapshot purge key payload is ambiguous')
            purges.append((owner, value['kind'], target))
            continue
        if (table, column) == ('jobs', 'image_keys'):
            value = _json_value(value)
            if value is None:
                continue
            if not isinstance(value, list):
                raise MediaCoverageError('Snapshot image keys are not a list')
            if not isinstance(owner, str) or not owner:
                raise MediaCoverageError('Snapshot media history ownership is missing')
            for key in value:
                history.add((owner, _valid_key(key)))
        elif (table, column) in JSON_COLUMNS:
            for url in _learning_urls(_json_value(value)):
                key = _key_from_url(url, bucket, bases)
                if key is not None:
                    keys.add(key)
        else:
            key = _key_from_url(value, bucket, bases)
            if key is not None:
                keys.add(key)
    return frozenset(keys), frozenset(history), tuple(purges)


def collect_snapshot_media_references(connection, values):
    """Return own-bucket references, including accumulated job history."""
    keys, history, _purges = _snapshot_references(connection, values)
    return keys | {key for _owner, key in history}


def verify_snapshot_media_coverage(connection, values, frozen_inventory):
    """Fail closed when a referenced object is absent; never reveal keys."""
    if not isinstance(frozen_inventory, dict):
        raise MediaCoverageError('Frozen snapshot media inventory is invalid')
    for key in frozen_inventory:
        _valid_key(key)
    keys, history, purges = _snapshot_references(connection, values)
    if not keys <= frozen_inventory.keys():
        raise MediaCoverageError('Snapshot media references are missing from the frozen inventory')
    exempt = set()
    for owner, key in history:
        if key in frozen_inventory:
            continue
        if not any(purge_owner == owner and (
                (kind == 'keys' and target == key) or (kind == 'prefix' and key.startswith(target)))
                for purge_owner, kind, target in purges):
            raise MediaCoverageError('Snapshot media history has unexplained missing objects')
        exempt.add((owner, key))
    all_keys = keys | {key for _owner, key in history}
    return {'reference_count': len(all_keys), 'covered_count': len(all_keys & frozen_inventory.keys()),
            'history_exempt_count': len(exempt),
            'media_columns_checked': len(URL_COLUMNS | JSON_COLUMNS)}
