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


class ProbeBudgetError(RuntimeError):
    pass


def claim(path: Path, *, now: int | None = None) -> bool:
    """Consume one of at most 41 claims in 31 days and one per 18 hours.

    The operator must provision the ledger separately; a lost ledger never
    resets the budget automatically. The containing directory and ledger
    must be private and owned by the caller.
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
        with sqlite3.connect(f'file:{path}?mode=rw', uri=True, timeout=5, isolation_level=None) as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version != 1:
                raise ProbeBudgetError('ledger version invalid')
            rows = db.execute('SELECT claimed_at FROM claims ORDER BY claimed_at').fetchall()
            if any(type(row[0]) is not int or row[0] < 1 or row[0] > now for row in rows):
                raise ProbeBudgetError('ledger clock or data invalid')
            if rows and now - rows[-1][0] < 18 * 3600:
                db.rollback()
                return False
            if sum(now - row[0] < 31 * 86400 for row in rows) >= 41:
                db.rollback()
                return False
            db.execute('INSERT INTO claims (claimed_at) VALUES (?)', (now,))
            db.commit()
            return True
    except ProbeBudgetError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise ProbeBudgetError('ledger unavailable') from exc
