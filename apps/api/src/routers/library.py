from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from src.core.database import get_db
from src.models.dto import LibraryResponse, BookSummary, TargetAge
from src.models.db import Book

router = APIRouter()


def get_user_key(x_user_key: str = Header(..., description="User identification key")) -> str:
    """Extract user key from header"""
    if not x_user_key or len(x_user_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid X-User-Key header")
    return x_user_key


@router.get("", response_model=LibraryResponse)
async def get_library(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    limit: int = 20,
    offset: int = 0,
):
    """
    내 서재 (생성한 책 목록)

    - 최신순 정렬
    - 페이지네이션 지원
    """
    # Get total count
    count_result = await db.execute(
        select(Book).where(Book.user_key == user_key)
    )
    total = len(count_result.scalars().all())

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
