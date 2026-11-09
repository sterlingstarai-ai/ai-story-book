"""Durable claim ledger for a future, explicitly installed provider probe.

Claims are consumed before any network request, including on crash or timeout.
This module does not schedule or make provider requests. Its limits bound
request count, not currency, and its ledger must be on persistent storage.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import stat
import time

_CLAIM_INTERVAL = 18 * 3600
_WINDOW = 31 * 86400
_MAX_CLAIMS = 41


class ProbeBudgetError(RuntimeError):
    pass


class ProbeFollowupUnavailable(ProbeBudgetError):
    """A full refresh can claim now, but a partial refresh risks later expiry."""


def claim(path: Path, *, now: int | None = None, require_next_interval: bool = False) -> bool:
    """Consume one of at most 41 claims in 31 days and one per 18 hours.

    The operator must provision the ledger separately; a lost ledger never
    resets the budget automatically. The containing directory and ledger
    must be private and owned by the caller.

    A partial refresh can require another claim to be available after the
    minimum interval, assuming this is the last claim until then.
    Raise ProbeFollowupUnavailable without consuming a claim if it cannot.
    """
    now = int(time.time()) if now is None else now
    if type(now) is not int or now < 1:
        raise ProbeBudgetError('invalid clock')
    try:
        directory = path.parent.stat(follow_symlinks=False)
        info = path.stat(follow_symlinks=False)
        if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
                or directory.st_mode & 0o077 or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ProbeBudgetError('ledger permissions invalid')
        with sqlite3.connect(f'{path.absolute().as_uri()}?mode=rw', uri=True, timeout=5, isolation_level=None) as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version != 1:
                raise ProbeBudgetError('ledger version invalid')
            last, recent, invalid = db.execute('''
                SELECT MAX(claimed_at), COUNT(CASE WHEN claimed_at > ? THEN 1 END),
                    COUNT(CASE WHEN typeof(claimed_at) != 'integer'
                        OR claimed_at < 1 OR claimed_at > ? THEN 1 END)
                FROM claims
            ''', (now - _WINDOW, now)).fetchone()
            if invalid:
                raise ProbeBudgetError('ledger clock or data invalid')
            if (last is not None and now - last < _CLAIM_INTERVAL) or recent >= _MAX_CLAIMS:
                db.rollback()
                return False
            if require_next_interval:
                (remaining,) = db.execute('SELECT COUNT(*) FROM claims WHERE claimed_at > ?',
                                          (now + _CLAIM_INTERVAL - _WINDOW,)).fetchone()
                if remaining + 1 >= _MAX_CLAIMS:
                    db.rollback()
                    raise ProbeFollowupUnavailable('next claim would exceed the rolling cap')
            db.execute('INSERT INTO claims (claimed_at) VALUES (?)', (now,))
            db.commit()
            return True
    except ProbeBudgetError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise ProbeBudgetError('ledger unavailable') from exc
