"""Ownership-safe report persistence and operator workflow, without AI calls."""

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError, ValidationError
from src.core.utils import utcnow
from src.models.content_report import CreateContentReportRequest
from src.models.db import Book, ContentReport, Page

async def report_content(db: AsyncSession, book: Book, page_number: int) -> dict:
    if page_number == 0:
        return {"title": book.title, "title_ko": book.title_ko,
                "title_en": book.title_en, "image_url": book.cover_image_url}
    page = (await db.execute(select(Page).where(
        Page.book_id == book.id, Page.page_number == page_number,
    ))).scalar_one_or_none()
    if page is None:
        raise NotFoundError("Page", str(page_number))
    return {"text": page.text, "text_ko": page.text_ko, "text_en": page.text_en,
            "image_url": page.image_url}


def content_fingerprint(content: dict) -> str:
    return hashlib.sha256(json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


async def create_content_report(
    db: AsyncSession, book: Book, request: CreateContentReportRequest,
) -> ContentReport:
    fingerprint = content_fingerprint(await report_content(db, book, request.page_number))
    # The router locks the owning book for serialization on Postgres. The unique
    # constraint also protects duplicate reports from non-HTTP insertion paths.
    existing = (await db.execute(select(ContentReport).where(
        ContentReport.book_id == book.id,
        ContentReport.page_number == request.page_number,
        ContentReport.reason == request.reason,
        ContentReport.content_fingerprint == fingerprint,
    ))).scalar_one_or_none()
    if existing is not None:
        return existing
    report = ContentReport(
        id=f"report_{uuid.uuid4().hex}", book_id=book.id,
        page_number=request.page_number, reason=request.reason,
        content_fingerprint=fingerprint, status="pending",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


async def update_report_status(
    db: AsyncSession, report_id: str, status: str, resolution: str | None,
) -> ContentReport:
    if status not in {"in_review", "resolved", "dismissed"}:
        raise ValidationError("Invalid report status")
    if status == "in_review" and resolution is not None:
        raise ValidationError("An open report cannot have a resolution")
    if status == "resolved" and resolution not in {"content_corrected", "content_removed"}:
        raise ValidationError("A resolved report requires a correction or removal")
    if status == "dismissed" and resolution not in {"no_violation", "duplicate"}:
        raise ValidationError("A dismissed report requires a review reason")
    report = (await db.execute(select(ContentReport).where(
        ContentReport.id == report_id,
    ).with_for_update())).scalar_one_or_none()
    if report is None:
        raise NotFoundError("ContentReport", report_id)
    report.status = status
    report.resolution = resolution
    report.updated_at = utcnow()
    await db.commit()
    await db.refresh(report)
    return report
