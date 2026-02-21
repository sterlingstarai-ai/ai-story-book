from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from typing import Literal, Optional

from src.core.database import get_db
from src.core.dependencies import get_profile_id, get_user_key
from src.models.dto import LibraryResponse, BookSummary, TargetAge, Style
from src.models.db import Book, ChildProfile
from src.core.exceptions import NotFoundError, AuthorizationError, ValidationError
from src.services.storage import delete_book_files

router = APIRouter()


class UpdateBookRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


async def _validate_profile_ownership(
    db: AsyncSession,
    user_key: str,
    profile_id: Optional[str],
) -> Optional[str]:
    if not isinstance(profile_id, str):
        return None
    normalized = profile_id.strip()
    if not normalized:
        return None
    result = await db.execute(
        select(ChildProfile).where(
            ChildProfile.id == normalized,
            ChildProfile.user_key == user_key,
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise ValidationError("유효하지 않은 프로필입니다.")
    return normalized


@router.get("", response_model=LibraryResponse)
async def get_library(
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: Optional[str] = Query(default=None, description="Cursor book_id for pagination"),
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
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)

    # Build base query with filters
    base_filter = Book.user_key == user_key
    filters = [base_filter]
    if scoped_profile_id:
        filters.append(Book.profile_id == scoped_profile_id)

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

    cursor_book = None
    if cursor:
        cursor_result = await db.execute(
            select(Book).where(Book.id == cursor, Book.user_key == user_key)
        )
        cursor_book = cursor_result.scalar_one_or_none()

    if sort == "oldest":
        if cursor_book:
            query = query.where(
                or_(
                    Book.created_at > cursor_book.created_at,
                    and_(Book.created_at == cursor_book.created_at, Book.id > cursor_book.id),
                )
            )
        query = query.order_by(Book.created_at.asc())
    elif sort == "title":
        query = query.order_by(Book.title.asc())
    else:  # newest (default)
        if cursor_book:
            query = query.where(
                or_(
                    Book.created_at < cursor_book.created_at,
                    and_(Book.created_at == cursor_book.created_at, Book.id < cursor_book.id),
                )
            )
        query = query.order_by(Book.created_at.desc())

    if not cursor:
        query = query.offset(offset)
    query = query.limit(limit + 1)
    result = await db.execute(query)
    books = result.scalars().all()
    has_more = len(books) > limit
    books = books[:limit]
    next_cursor = books[-1].id if has_more and books else None

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
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.patch("/{book_id}", response_model=BookSummary)
async def update_book(
    book_id: str,
    request: UpdateBookRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    책 제목 수정
    """
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise NotFoundError("Book", book_id)
    if book.user_key != user_key:
        raise AuthorizationError()
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)
    if scoped_profile_id and book.profile_id != scoped_profile_id:
        raise AuthorizationError("선택한 프로필의 책이 아닙니다.")

    normalized_title = request.title.strip()
    if not normalized_title:
        raise ValidationError("책 제목은 비워둘 수 없습니다.")

    book.title = normalized_title
    await db.commit()
    await db.refresh(book)

    return BookSummary(
        book_id=book.id,
        title=book.title,
        cover_image_url=book.cover_image_url or "",
        target_age=TargetAge(book.target_age),
        style=book.style,
        created_at=book.created_at,
    )


@router.delete("/{book_id}")
async def delete_book(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
    profile_id: Optional[str] = Depends(get_profile_id),
):
    """
    책 삭제
    """
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()

    if not book:
        raise NotFoundError("Book", book_id)

    if book.user_key != user_key:
        raise AuthorizationError()
    scoped_profile_id = await _validate_profile_ownership(db, user_key, profile_id)
    if scoped_profile_id and book.profile_id != scoped_profile_id:
        raise AuthorizationError("선택한 프로필의 책이 아닙니다.")

    # cascade="all, delete-orphan" on Book.pages handles Page deletion
    await db.delete(book)
    await db.commit()

    # Clean up S3 files (non-blocking, failure doesn't affect response)
    await delete_book_files(book_id)

    return {"message": "Book deleted successfully"}
