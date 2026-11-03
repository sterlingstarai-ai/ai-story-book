"""In-memory rehearsal of safe provider replacement; never contacts a service.

This is a model for tests, not a deployment or credential management tool.
It accepts only the two literal synthetic labels below, never real credentials.
Any interruption keeps admission closed until recovery explicitly disables the
candidate; the retired provider is never restarted or used as a fallback.
"""
from dataclasses import dataclass

RETIRED = 'synthetic-retired'
CANDIDATE = 'synthetic-candidate'


@dataclass
class SyntheticState:
    active: str | None = RETIRED
    running: bool = True
    admission_open: bool = False
    marker: bool = False
    candidate_verified: bool = False


class SimulatedInterruption(RuntimeError):
    pass


def _assert_state(state):
    if not isinstance(state, SyntheticState) or state.active not in (None, RETIRED, CANDIDATE):
        raise ValueError('Only fixed synthetic provider labels are accepted')
    if any(type(value) is not bool for value in (state.running, state.admission_open,
                                                  state.marker, state.candidate_verified)):
        raise ValueError('Invalid synthetic state')


def recover(state):
    """Fail closed after a simulated crash; never resume the retired label."""
    _assert_state(state)
    if state.marker:
        state.admission_open = False
        state.running = False
        state.active = None
        state.candidate_verified = False
        state.marker = False
    return state


def rehearse(state, *, interrupt_after=None, candidate_probe_ok=True, restart_ok=True):
    """Exercise success or a synthetic failure; no file, network, or env access."""
    _assert_state(state)
    if (state.marker or state.active != RETIRED or state.admission_open
            or not state.running or type(candidate_probe_ok) is not bool
            or type(restart_ok) is not bool):
        raise ValueError('Synthetic rehearsal preconditions not met')
    phases = ('fenced', 'stopped', 'installed', 'started', 'verified')
    if interrupt_after not in (None, *phases):
        raise ValueError('Unknown synthetic interruption')

    def interrupt(phase):
        if interrupt_after == phase:
            raise SimulatedInterruption(phase)

    state.marker = True
    state.admission_open = False
    interrupt('fenced')
    state.running = False
    interrupt('stopped')
    state.active = CANDIDATE
    interrupt('installed')
    if not restart_ok:
        return recover(state)
    state.running = True
    interrupt('started')
    if not candidate_probe_ok:
        return recover(state)
    state.candidate_verified = True
    interrupt('verified')
    state.admission_open = True
    state.marker = False
    return state
