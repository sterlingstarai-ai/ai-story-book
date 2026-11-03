from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import provider_rotation_quarantine as guard


class MutationGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.marker = self.path / 'recovery.json'
        self.mutation = self.path / 'docker-mutation.json'

    def run_main(self):
        with mock.patch.object(guard, '_PRODUCTION_MARKER', self.marker), \
             mock.patch('sys.argv', ['quarantine', '--recover']), redirect_stdout(io.StringIO()):
            return guard.main()

    def test_no_intent_and_no_recovery_succeeds(self):
        self.assertEqual(self.run_main(), 0)

    def test_mutation_alone_never_claims_no_recovery(self):
        self.mutation.write_text('{}')
        self.assertEqual(self.run_main(), 1)

    def test_mutation_with_recovery_quarantines_but_still_fails(self):
        self.mutation.write_text('{}')
        self.marker.write_text('{}')
        with mock.patch.object(guard, 'quarantine', return_value={'status': 'ROTATION_QUARANTINED'}) as recovery:
            self.assertEqual(self.run_main(), 1)
            recovery.assert_called_once()
        self.assertTrue(self.mutation.exists())
        self.assertTrue(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
