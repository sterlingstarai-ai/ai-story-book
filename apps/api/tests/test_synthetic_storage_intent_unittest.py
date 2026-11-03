"""Safety boundary of the synthetic-only durable storage experiment."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import synthetic_storage_intent as intent  # noqa: E402


class SyntheticIntentTests(unittest.TestCase):
    def test_real_environment_is_rejected_before_database_connection(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(intent.psycopg, 'connect') as connect:
            with self.assertRaises(RuntimeError):
                intent.run_durable_mutation('operation', Mock())
            connect.assert_not_called()

    def test_duplicate_id_never_calls_storage(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.execute.return_value.fetchone.return_value = None
        mutation = Mock()
        with patch.object(intent, '_connection_params', return_value={}), \
                patch.object(intent.psycopg, 'connect', return_value=connection):
            self.assertEqual(intent.run_durable_mutation('same', mutation), 'reconciliation_required')
        mutation.assert_not_called()

    def test_ambiguous_intent_commit_never_calls_storage(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.execute.side_effect = [None, None, RuntimeError('lost acknowledgement')]
        mutation = Mock()
        with patch.object(intent, '_connection_params', return_value={}), \
                patch.object(intent.psycopg, 'connect', return_value=connection):
            with self.assertRaisesRegex(RuntimeError, 'lost acknowledgement'):
                intent.run_durable_mutation('ambiguous', mutation)
        mutation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
