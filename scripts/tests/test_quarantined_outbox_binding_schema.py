"""Checkpoint binding must recognize only complete, known migration schemas."""
import unittest

from quarantined_outbox_binding import (
    _outbox_query,
    _PRE_RECEIPT_REVISIONS,
    _RECEIPT_REVISIONS,
    _REQUIRED_OUTBOX_COLUMNS,
)


class OutboxSchemaTests(unittest.TestCase):
    def test_pre_receipt_revisions_use_explicit_null(self):
        for revision in _PRE_RECEIPT_REVISIONS:
            with self.subTest(revision=revision):
                self.assertIn('NULL::json AS deletion_receipt',
                              _outbox_query(revision, set(_REQUIRED_OUTBOX_COLUMNS)))

    def test_receipt_revisions_require_actual_column(self):
        for revision in _RECEIPT_REVISIONS:
            with self.subTest(revision=revision):
                self.assertNotIn('NULL::json', _outbox_query(
                    revision, set(_REQUIRED_OUTBOX_COLUMNS) | {'deletion_receipt'}))

    def test_unknown_revision_and_incomplete_migration_fail_closed(self):
        base = set(_REQUIRED_OUTBOX_COLUMNS)
        cases = [
            ('5de7a40b6c12', base | {'deletion_receipt'}),
            ('e7b93d2a601f', base),
            ('unknown', base),
            ('unknown', base | {'deletion_receipt'}),
            ('5de7a40b6c12', base - {'action'}),
            ('e7b93d2a601f', base | {'deletion_receipt', 'extra'}),
        ]
        for revision, columns in cases:
            with self.subTest(revision=revision, columns=columns):
                with self.assertRaises(ValueError):
                    _outbox_query(revision, columns)


if __name__ == '__main__':
    unittest.main()
