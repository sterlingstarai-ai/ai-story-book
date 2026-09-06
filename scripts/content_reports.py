#!/usr/bin/env python3
"""Private operator queue. Run with the API Python environment; no public admin API."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    queue = commands.add_parser("list", help="List report metadata without child content")
    queue.add_argument("--status", choices=["pending", "in_review", "resolved", "dismissed", "all"], default="pending")
    queue.add_argument("--limit", type=int, choices=range(1, 101), default=30, metavar="1..100")
    export = commands.add_parser("export", help="Write one report's current content to a new private JSON file")
    export.add_argument("report_id")
    export.add_argument("--output", type=Path, required=True)
    update = commands.add_parser("update", help="Record a review result; does not edit the book")
    update.add_argument("report_id")
    update.add_argument("--status", choices=["in_review", "resolved", "dismissed"], required=True)
    update.add_argument("--resolution", choices=["content_corrected", "content_removed", "no_violation", "duplicate"])
    return root


def metadata(report) -> dict:
    return {"report_id": report.id, "book_id": report.book_id,
            "page_number": report.page_number, "reason": report.reason,
            "status": report.status, "resolution": report.resolution,
            "created_at": report.created_at.isoformat(),
            "updated_at": report.updated_at.isoformat()}


async def run(args) -> None:
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal, async_engine
    from src.models.db import Book, ContentReport
    from src.services.content_reports import (
        content_fingerprint, report_content, update_report_status,
    )
    from src.services.storage import media_url

    try:
        async with AsyncSessionLocal() as db:
            if args.command == "list":
                query = select(ContentReport).order_by(ContentReport.created_at, ContentReport.id)
                if args.status != "all":
                    query = query.where(ContentReport.status == args.status)
                rows = (await db.execute(query.limit(args.limit))).scalars().all()
                print(json.dumps([metadata(row) for row in rows], ensure_ascii=False, indent=2))
                return
            if args.command == "update":
                row = await update_report_status(db, args.report_id, args.status, args.resolution)
                print(json.dumps(metadata(row), ensure_ascii=False, indent=2))
                return
            row = (await db.execute(select(ContentReport).where(ContentReport.id == args.report_id))).scalar_one_or_none()
            if row is None:
                raise ValueError("Report not found")
            book = await db.get(Book, row.book_id)
            if book is None:
                raise ValueError("Reported book no longer exists")
            content = await report_content(db, book, row.page_number)
            payload = {**metadata(row), "current_content_changed": content_fingerprint(content) != row.content_fingerprint,
                       "content": {**content, "image_url": media_url(content.get("image_url"))}}
            # Exclusive creation and 0600 at open: never overwrite a prior export
            # or briefly expose a child's content through the process umask.
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(payload, target, ensure_ascii=False, indent=2)
                target.write("\n")
            print("Private report export created. Remove it after review.")
    finally:
        await async_engine.dispose()


def main() -> int:
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        # DB exceptions may contain credentials, statement parameters or content.
        print(f"Report operation failed ({type(exc).__name__}); check the command and private server configuration.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
