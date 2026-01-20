from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.models.dto import LibraryResponse, BookSummary, TargetAge
from src.models.db import Book

router = APIRouter()


@router.get("", response_model=LibraryResponse)
async def get_library(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """
    내 서재 (생성한 책 목록)

    - 최신순 정렬
    - 페이지네이션 지원
    """
    # Get total count efficiently using COUNT
    count_result = await db.execute(
        select(func.count()).select_from(Book).where(Book.user_key == user_key)
    )
    total = count_result.scalar() or 0

    # Get paginated results
    result = await db.execute(
        select(Book)
        .where(Book.user_key == user_key)
        .order_by(Book.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
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
        total=total
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
    result = await db.execute(
        select(Book).where(Book.id == book_id)
    )
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.user_key != user_key:
        raise HTTPException(status_code=403, detail="Access denied")

    # Delete pages first
    from src.models.db import Page
    await db.execute(
        Page.__table__.delete().where(Page.book_id == book_id)
    )

    await db.delete(book)
    await db.commit()

    return {"message": "Book deleted successfully"}
