"""One-time, conservative activation after all old writers are fenced offline.

Run only using the deployment's database configuration, following docs/DEPLOYMENT.md.
The acknowledgement is an operator assertion; this script cannot detect old writers.
"""
import argparse

from sqlalchemy import text

from src.core.database import engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-old-writers-stopped-and-fenced", action="store_true")
    args = parser.parse_args()
    if not args.all_old_writers_stopped_and_fenced:
        parser.error("all old writers must be stopped and fenced before activation")
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required")
    with engine.begin() as connection:
        day = connection.execute(text(
            "SELECT to_char(clock_timestamp() AT TIME ZONE 'Asia/Seoul', 'YYYYMMDD')"
        )).scalar_one()
        result = connection.execute(text("""
            INSERT INTO generation_budget_activation (id, blocked_through_day, current_day, requests)
            VALUES (1, :day, :day, 0) ON CONFLICT (id) DO NOTHING RETURNING blocked_through_day
        """), {"day": day}).scalar_one_or_none()
        if result is None:
            raise RuntimeError("Already activated; existing history was not changed")
    print(f"Activated; generation is blocked through Korea day {day}.")


if __name__ == "__main__":
    main()
