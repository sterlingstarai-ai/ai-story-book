"""Synthetic replacement cannot reactivate a retired provider on failures."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from synthetic_provider_replacement import (  # noqa: E402
    CANDIDATE, SimulatedInterruption, SyntheticState, recover, rehearse,
)


class SyntheticReplacementTest(unittest.TestCase):
    def test_success_opens_only_verified_candidate(self):
        state = rehearse(SyntheticState())
        self.assertEqual(state.active, CANDIDATE)
        self.assertTrue(state.running and state.admission_open and state.candidate_verified)
        self.assertFalse(state.marker)

    def test_interruption_never_reactivates_retired_provider(self):
        for phase in ('fenced', 'stopped', 'installed', 'started', 'verified'):
            with self.subTest(phase=phase):
                state = SyntheticState()
                with self.assertRaises(SimulatedInterruption):
                    rehearse(state, interrupt_after=phase)
                self.assertFalse(state.admission_open)
                recover(state)
                self.assertEqual((state.active, state.running, state.admission_open), (None, False, False))

    def test_failed_probe_or_restart_remains_disabled(self):
        for kwargs in ({'candidate_probe_ok': False}, {'restart_ok': False}):
            with self.subTest(kwargs=kwargs):
                state = rehearse(SyntheticState(), **kwargs)
                self.assertEqual((state.active, state.running, state.admission_open), (None, False, False))

    def test_real_or_unknown_credentials_cannot_enter_model(self):
        with self.assertRaises(ValueError):
            rehearse(SyntheticState(active='unexpected'))


if __name__ == '__main__':
    unittest.main()
