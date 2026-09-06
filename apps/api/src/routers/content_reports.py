from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_profile_id, get_user_key, validate_profile_ownership
from src.core.exceptions import NotFoundError
from src.models.content_report import CreateContentReportRequest, ContentReportResponse
from src.models.db import Book
from src.services.content_reports import create_content_report

router = APIRouter()


@router.post("/{book_id}/reports", response_model=ContentReportResponse)
async def report_book_content(
    book_id: str,
    request: CreateContentReportRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: str | None = Depends(get_profile_id),
):
    """Flag an owned cover or page for operator review, entirely in-app."""
    scoped_profile = await validate_profile_ownership(db, user_key, profile_id)
    query = select(Book).where(Book.id == book_id, Book.user_key == user_key)
    if scoped_profile:
        query = query.where(Book.profile_id == scoped_profile)
    book = (await db.execute(query.with_for_update())).scalar_one_or_none()
    if book is None:
        raise NotFoundError("Book", book_id)
    report = await create_content_report(db, book, request)
    return ContentReportResponse(
        report_id=report.id, status=report.status, created_at=report.created_at,
    )
