"""Entrypoint for the managed pilot's shared daily provider request guard."""

from datetime import datetime
import os
from pathlib import Path
import runpy
import sys
from zoneinfo import ZoneInfo

from live_acceptance_guard import install, request_limits

_KOREA = ZoneInfo("Asia/Seoul")


def install_daily_guard(environ=None, now=None):
    environ = os.environ if environ is None else environ
    now = datetime.now if now is None else now
    journal = Path(environ["LIVE_ACCEPTANCE_JOURNAL"])
    admissions = int(environ["DAILY_GENERATION_BUDGET"])
    if admissions <= 0 or environ.get("ILLUSTRATION_QUALITY_ENABLED") != "true":
        raise RuntimeError("PILOT_PROVIDER_BUDGET_NOT_CONFIGURED")
    # The application independently caps each admitted book. Its largest
    # supported book sets the outer ceiling for this shared daily ledger.
    ceilings = {role: per_book * admissions
                for role, per_book in request_limits(12, True).items()}

    def daily_journal():
        return journal.with_suffix(f".{now(_KOREA):%Y%m%d}.jsonl")

    install(journal_for_request=daily_journal, request_ceilings=ceilings)


if __name__ == "__main__":
    install_daily_guard()
    module = sys.argv.pop(1)
    sys.argv[0] = module
    runpy.run_module(module, run_name="__main__", alter_sys=True)
