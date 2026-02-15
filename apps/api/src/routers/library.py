from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Literal, Optional

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.models.dto import LibraryResponse, BookSummary, TargetAge, Style
from src.models.db import Book

router = APIRouter()


@router.get("", response_model=LibraryResponse)
async def get_library(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    style: Optional[Style] = Query(default=None, description="스타일 필터 (watercolor, cartoon 등)"),
    target_age: Optional[TargetAge] = Query(default=None, description="연령대 필터 (3-5, 5-7, 7-9, adult)"),
    sort: Literal["newest", "oldest", "title"] = Query(default="newest", description="정렬: newest, oldest, title"),
):
    """
    내 서재 (생성한 책 목록)

    - 정렬: newest(기본), oldest, title
    - 스타일/연령대 필터
    - 페이지네이션 지원
    """
    # Build base query with filters
    base_filter = Book.user_key == user_key
    filters = [base_filter]

    if style:
        filters.append(Book.style == style)
    if target_age:
        filters.append(Book.target_age == target_age)

    # Get total count efficiently using COUNT
    count_query = select(func.count()).select_from(Book)
    for f in filters:
        count_query = count_query.where(f)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Build query with sort
    query = select(Book)
    for f in filters:
        query = query.where(f)

    if sort == "oldest":
        query = query.order_by(Book.created_at.asc())
    elif sort == "title":
        query = query.order_by(Book.title.asc())
    else:  # newest (default)
        query = query.order_by(Book.created_at.desc())

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    books = result.scalars().all()

    return LibraryResponse(
        books=[
            BookSummary(
                book_id=b.id,
                title=b.title,
                cover_image_url=b.cover_image_url or "",
                target_age=TargetAge(b.target_age),
                style=b.style,
                created_at=b.created_at,
            )
            for b in books
        ],
        total=total,
    )


@router.delete("/{book_id}")
async def delete_book(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    책 삭제
    """
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    # Delete pages first
    from src.models.db import Page

    await db.execute(Page.__table__.delete().where(Page.book_id == book_id))

    await db.delete(book)
    await db.commit()

    return {"message": "Book deleted successfully"}
