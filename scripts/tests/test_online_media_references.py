import ast
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import online_media_references as media


VALUES = {'S3_BUCKET': 'fixture-bucket', 'S3_ENDPOINT': 'http://127.0.0.1:9000',
          'S3_PUBLIC_URL': 'https://media.example.test/fixture-bucket',
          'S3_LEGACY_PUBLIC_URLS': 'https://old.example.test/files', 'S3_ADDRESSING_STYLE': 'auto'}


class Rows(list):
    def fetchall(self):
        return self


class Snapshot:
    def __init__(self, values=None, *, schema=None, purges=()):
        self.schema = schema if schema is not None else [
            (table, column, 'jsonb' if (table, column) in media.JSON_COLUMNS else 'text')
            for table, column in sorted(media.URL_COLUMNS | media.JSON_COLUMNS | media._OWNERSHIP_COLUMNS)]
        self.values = values or {}
        self.purges = purges
        self.queries = []

    def execute(self, statement):
        self.queries.append(statement)
        if isinstance(statement, str):
            return Rows(self.schema)
        name = statement.as_string()
        if name.count(' UNION ALL ') != 17 or name.count('to_jsonb(') != 17:
            raise AssertionError('Unexpected query')
        return Rows([(table, column, value, 'owner-one' if (table, column) == ('jobs', 'image_keys') else None)
                     for (table, column), values in self.values.items() for value in values]
                    + [('storage_purge_tasks', 'completed_purge', value, owner) for owner, value in self.purges])


class SnapshotMediaCoverageTests(unittest.TestCase):
    def test_prefetch_queries_are_exactly_the_same_queries_used_by_validation(self):
        snapshot = Snapshot({('pages', 'image_url'): ['https://media.example.test/fixture-bucket/a.png']})
        schema_query, refs_query = media.snapshot_media_queries()
        self.assertEqual(snapshot.queries, [])
        result = media.verify_snapshot_media_coverage(snapshot, VALUES, {'a.png': {}})
        self.assertEqual(schema_query, snapshot.queries[0])
        self.assertEqual(refs_query.as_string(), snapshot.queries[1].as_string())
        responses = {schema_query: Rows(snapshot.schema),
                     refs_query.as_string(): Rows([('pages', 'image_url',
                         'https://media.example.test/fixture-bucket/a.png', None)])}
        class Prefetched:
            def execute(self, statement):
                key = statement if isinstance(statement, str) else statement.as_string()
                if key not in responses:
                    raise AssertionError('An unprefetched query must not be accepted')
                return responses.pop(key)
        self.assertEqual(media.verify_snapshot_media_coverage(Prefetched(), VALUES, {'a.png': {}}), result)
        self.assertFalse(responses)

    def test_current_model_has_exactly_the_reviewed_url_and_media_json_columns(self):
        tree = ast.parse((Path(__file__).resolve().parents[2] / 'apps/api/src/models/db.py').read_text())
        observed = set()
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            fields = {child.targets[0].id: child.value for child in node.body
                      if isinstance(child, ast.Assign) and isinstance(child.targets[0], ast.Name)}
            table = fields.get('__tablename__')
            if not isinstance(table, ast.Constant):
                continue
            for column in fields:
                if re.search(r'_url(?:_[a-z]{2})?$', column) or column in {'image_keys', 'learning_assets'}:
                    observed.add((table.value, column))
        self.assertEqual(observed, media.URL_COLUMNS | media.JSON_COLUMNS)

    def test_snapshot_connection_is_the_only_database_used_and_extra_objects_are_allowed(self):
        snapshot = Snapshot({('books', 'cover_image_url'): ['https://media.example.test/fixture-bucket/a%20b.png'],
                             ('jobs', 'image_keys'): [['jobs/one/image.png']]})
        result = media.verify_snapshot_media_coverage(snapshot, VALUES, {
            'a b.png': {}, 'jobs/one/image.png': {}, 'unreferenced.png': {}})
        self.assertEqual(result, {'reference_count': 2, 'covered_count': 2, 'history_exempt_count': 0,
                                  'media_columns_checked': 17})
        self.assertEqual(len(snapshot.queries), 2)

    def test_missing_reference_fails_without_printing_the_key(self):
        snapshot = Snapshot({('pages', 'audio_url'): ['https://media.example.test/fixture-bucket/private.wav']})
        with self.assertRaisesRegex(media.MediaCoverageError, 'missing from the frozen inventory') as failure:
            media.verify_snapshot_media_coverage(snapshot, VALUES, {})
        self.assertNotIn('private.wav', str(failure.exception))

    def test_legacy_path_virtual_host_s3_and_signed_urls_map_to_one_key(self):
        urls = ['https://old.example.test/files/a.png',
                'http://127.0.0.1:9000/fixture-bucket/a.png?X-Amz-Signature=not-a-real-secret',
                'http://fixture-bucket.127.0.0.1:9000/a.png', 's3://fixture-bucket/a.png']
        snapshot = Snapshot({('pages', 'image_url'): urls})
        self.assertEqual(media.collect_snapshot_media_references(snapshot, VALUES), {'a.png'})

    def test_external_placeholders_and_other_bucket_http_urls_are_not_claimed(self):
        snapshot = Snapshot({('pages', 'image_url'): [None, '', 'https://placehold.co/800x600',
                                                     'http://127.0.0.1:9000/other-bucket/a.png']})
        self.assertEqual(media.collect_snapshot_media_references(snapshot, VALUES), set())

    def test_new_media_columns_fail_closed_even_when_all_rows_are_empty(self):
        for name, kind in [('thumbnail_url', 'text'), ('video_uri', 'text'),
                           ('audio_keys', 'jsonb'), ('media_path', 'text')]:
            with self.subTest(name=name):
                snapshot = Snapshot()
                snapshot.schema.append(('pages', name, kind))
                with self.assertRaisesRegex(media.MediaCoverageError, 'unsupported media reference column'):
                    media.collect_snapshot_media_references(snapshot, VALUES)

    def test_missing_or_retyped_existing_column_fails_closed(self):
        for change in ('missing', 'type'):
            snapshot = Snapshot()
            snapshot.schema = [row for row in snapshot.schema if row[:2] != ('pages', 'image_url')]
            if change == 'type':
                snapshot.schema.append(('pages', 'image_url', 'jsonb'))
            with self.subTest(change=change), self.assertRaisesRegex(media.MediaCoverageError, 'incomplete'):
                media.collect_snapshot_media_references(snapshot, VALUES)

    def test_user_keys_are_not_media_and_schema_duplicates_are_rejected(self):
        snapshot = Snapshot()
        snapshot.schema.append(('jobs', 'idempotency_key', 'text'))
        self.assertEqual(media.collect_snapshot_media_references(snapshot, VALUES), set())
        snapshot.schema.append(snapshot.schema[0])
        with self.assertRaisesRegex(media.MediaCoverageError, 'ambiguous'):
            media.collect_snapshot_media_references(snapshot, VALUES)

    def test_nested_learning_urls_are_covered_and_future_raw_keys_are_rejected(self):
        snapshot = Snapshot({('books', 'learning_assets'): [{'pages': [{'audio_url':
            'https://media.example.test/fixture-bucket/learning.wav'}]}]})
        self.assertEqual(media.collect_snapshot_media_references(snapshot, VALUES), {'learning.wav'})
        snapshot.values = {('books', 'learning_assets'): [{'pages': [{'image_keys': ['omitted.png']}]}]}
        with self.assertRaisesRegex(media.MediaCoverageError, 'Unsupported nested'):
            media.collect_snapshot_media_references(snapshot, VALUES)

    def test_json_text_and_null_are_supported_but_malformed_json_is_not(self):
        snapshot = Snapshot({('jobs', 'image_keys'): ['["a.png"]', 'null']})
        self.assertEqual(media.collect_snapshot_media_references(snapshot, VALUES), {'a.png'})
        for value in ['[broken', {'key': 'a.png'}, [''], [None]]:
            snapshot.values = {('jobs', 'image_keys'): [value]}
            with self.subTest(value=value), self.assertRaises(media.MediaCoverageError):
                media.collect_snapshot_media_references(snapshot, VALUES)

    def test_bad_keys_and_unsupported_references_fail_without_leaking_values(self):
        for value in ['s3://foreign-bucket/a.png', 'file:///private/a.png',
                      'https://me:secret@media.example.test/fixture-bucket/a.png',
                      'https://media.example.test/fixture-bucket/../a.png',
                      'https://media.example.test/fixture-bucket/a%00.png']:
            snapshot = Snapshot({('pages', 'image_url'): [value]})
            with self.subTest(value=value), self.assertRaises(media.MediaCoverageError) as failure:
                media.collect_snapshot_media_references(snapshot, VALUES)
            self.assertNotIn(value, str(failure.exception))

    def test_inventory_and_storage_configuration_are_validated(self):
        for value in [None, [], {'../bad': {}}]:
            with self.subTest(value=value), self.assertRaises(media.MediaCoverageError):
                media.verify_snapshot_media_coverage(Snapshot(), VALUES, value)
        for values in [{}, {'S3_BUCKET': 'fixture-bucket'}, VALUES | {'S3_PUBLIC_URL': 'file:///x'}]:
            with self.subTest(values=values), self.assertRaises(media.MediaCoverageError):
                media.collect_snapshot_media_references(Snapshot(), values)

    def test_qc_replacement_allows_only_same_owner_completed_history_deletion(self):
        values = {('jobs', 'image_keys'): [['jobs/one/old.png', 'jobs/one/new.png']],
                  ('pages', 'image_url'): ['https://media.example.test/fixture-bucket/jobs/one/new.png']}
        for kind, target in [('keys', 'jobs/one/old.png'), ('prefix', 'jobs/one/')]:
            snapshot = Snapshot(values, purges=[('owner-one', {'kind': kind, 'target': target, 'status': 'done'})])
            result = media.verify_snapshot_media_coverage(snapshot, VALUES, {'jobs/one/new.png': {}})
            self.assertEqual(result['history_exempt_count'], 1)
            self.assertEqual(result['covered_count'], 1)
            self.assertEqual(len(snapshot.queries), 2)
            snapshot.purges = [('owner-two', {'kind': kind, 'target': target, 'status': 'done'})]
            with self.assertRaisesRegex(media.MediaCoverageError, 'unexplained missing'):
                media.verify_snapshot_media_coverage(snapshot, VALUES, {'jobs/one/new.png': {}})

    def test_completed_history_purge_never_excuses_a_missing_live_url(self):
        snapshot = Snapshot({('jobs', 'image_keys'): [['old.png']],
                             ('pages', 'image_url'): ['https://media.example.test/fixture-bucket/old.png']},
                            purges=[('owner-one', {'kind': 'keys', 'target': 'old.png', 'status': 'done'})])
        with self.assertRaisesRegex(media.MediaCoverageError, 'missing from the frozen inventory'):
            media.verify_snapshot_media_coverage(snapshot, VALUES, {})

    def test_ambiguous_unknown_or_incomplete_purges_cannot_excuse_missing_history(self):
        for payload in [{'kind': 'prefix', 'target': '', 'status': 'done'},
                        {'kind': 'prefix', 'target': 'jobs/one', 'status': 'done'},
                        {'kind': 'keys', 'target': '["old.png"]', 'status': 'done'},
                        {'kind': 'unknown', 'target': 'old.png', 'status': 'done'},
                        {'kind': 'keys', 'target': 'old.png', 'status': 'pending'}]:
            snapshot = Snapshot({('jobs', 'image_keys'): [['old.png']]}, purges=[('owner-one', payload)])
            with self.subTest(payload=payload), self.assertRaises(media.MediaCoverageError):
                media.verify_snapshot_media_coverage(snapshot, VALUES, {})


if __name__ == '__main__':
    unittest.main()
