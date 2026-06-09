"""책 공유 — 부모가 만든 공개 링크 생성/철회 + 공개 렌더.

설계 원칙(아동 개인정보):
- 부모(소유자)만 생성/철회. 링크는 만료·철회 가능.
- 공개 페이지는 검색 비노출(noindex), 댓글/상호작용 없음.
- 아이 실명/생년월일/원본 사진은 노출하지 않는다(표지·본문 일러스트·제목만).
"""

import uuid
from datetime import timedelta
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import AuthorizationError, NotFoundError
from src.core.utils import utcnow
from src.models.db import Book, BookShare, Page

# 인증된 부모용(/v1/books prefix로 등록)
router = APIRouter()
# 공개용(prefix 없이 등록 — /share/{token})
public_router = APIRouter()


class CreateShareRequest(BaseModel):
    # 0 = 서버 기본 만료(설정값) 사용
    expires_in_days: int = Field(default=0, ge=0, le=365)


def _share_url(token: str, request_base: str) -> str:
    base = (settings.share_base_url or request_base).rstrip("/")
    return f"{base}/share/{token}"


async def _require_owned_book(db: AsyncSession, book_id: str, user_key: str) -> Book:
    book = (
        await db.execute(select(Book).where(Book.id == book_id))
    ).scalar_one_or_none()
    if not book:
        raise NotFoundError("Book", book_id)
    if book.user_key != user_key:
        raise AuthorizationError()
    return book


@router.post("/{book_id}/share")
async def create_share(
    book_id: str,
    request: CreateShareRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """공유 링크 생성(소유자만). 만료일 미지정 시 서버 기본값."""
    await _require_owned_book(db, book_id, user_key)

    days = request.expires_in_days or settings.share_default_expiry_days
    now = utcnow()
    token = uuid.uuid4().hex
    share = BookShare(
        id=token,
        book_id=book_id,
        user_key=user_key,
        created_at=now,
        expires_at=(now + timedelta(days=days)) if days > 0 else None,
    )
    db.add(share)
    await db.commit()

    return {
        "token": token,
        "url": _share_url(token, str(http_request.base_url)),
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
    }


@router.post("/{book_id}/share/revoke")
async def revoke_share(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """이 책의 활성 공유 링크를 모두 철회(소유자만)."""
    await _require_owned_book(db, book_id, user_key)
    await db.execute(
        update(BookShare)
        .where(
            BookShare.book_id == book_id,
            BookShare.user_key == user_key,
            BookShare.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    await db.commit()
    return {"status": "revoked"}


async def _active_share(db: AsyncSession, token: str) -> Optional[BookShare]:
    share = (
        await db.execute(select(BookShare).where(BookShare.id == token))
    ).scalar_one_or_none()
    if not share or share.revoked_at is not None:
        return None
    if share.expires_at is not None and share.expires_at <= utcnow():
        return None
    return share


_NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


def _not_available_html() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='robots' content='noindex,nofollow'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>링크를 찾을 수 없어요</title></head>"
        "<body style='font-family:sans-serif;text-align:center;padding:48px;color:#444'>"
        "<h2>링크를 찾을 수 없거나 만료되었어요</h2>"
        "<p>공유가 철회되었거나 유효기간이 지났습니다.</p></body></html>",
        status_code=404,
        headers=_NOINDEX,
    )


@public_router.get("/share/{token}", response_class=HTMLResponse)
async def public_share(token: str, db: AsyncSession = Depends(get_db)):
    """공개 공유 페이지 — 검색 비노출, 아이 PII 비공개(표지·본문·제목만), 앱 CTA."""
    share = await _active_share(db, token)
    if share is None:
        return _not_available_html()

    book = (
        await db.execute(select(Book).where(Book.id == share.book_id))
    ).scalar_one_or_none()
    if book is None:
        return _not_available_html()

    pages = list(
        (
            await db.execute(
                select(Page)
                .where(Page.book_id == book.id)
                .order_by(Page.page_number)
            )
        ).scalars().all()
    )

    # PII 비노출: user_key·profile·생년월·원본사진(source_image_url)은 절대 포함하지 않는다.
    title = escape(book.title or "우리 아이 동화")
    cover = escape(book.cover_image_url or "")
    cover_tag = (
        f'<img class="cover" loading="lazy" src="{cover}" alt="">' if cover else ""
    )
    page_html = []
    for p in pages:
        img = escape(p.image_url or "")
        txt = escape(p.text or "")
        img_tag = f'<img loading="lazy" src="{img}" alt="">' if img else ""
        page_html.append(
            f"<figure class='pg'>{img_tag}<figcaption>{txt}</figcaption></figure>"
        )

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Aistorybook</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;
    margin:0;background:#faf7f2;color:#2b2b2b}}
  .wrap{{max-width:560px;margin:0 auto;padding:24px 16px 80px}}
  h1{{font-size:22px;text-align:center;margin:8px 0 16px}}
  .cover{{width:100%;border-radius:16px;display:block;box-shadow:0 6px 24px rgba(0,0,0,.12)}}
  .pg{{margin:20px 0;background:#fff;border-radius:14px;overflow:hidden;
    box-shadow:0 2px 10px rgba(0,0,0,.06)}}
  .pg img{{width:100%;display:block}}
  .pg figcaption{{padding:14px 16px;font-size:16px;line-height:1.6}}
  .cta{{position:fixed;left:0;right:0;bottom:0;background:#fff;border-top:1px solid #eee;
    padding:14px 16px;text-align:center}}
  .cta a{{display:inline-block;background:#3b5bdb;color:#fff;text-decoration:none;
    padding:12px 22px;border-radius:999px;font-weight:700}}
  .badge{{text-align:center;color:#888;font-size:13px;margin-top:24px}}
</style>
</head>
<body>
  <div class="wrap">
    <h1>{title}</h1>
    {cover_tag}
    {''.join(page_html)}
    <p class="badge">Aistorybook에서 만든 우리 아이 동화 📖</p>
  </div>
  <div class="cta"><a href="https://aistorybook.app">나도 우리 아이 동화 만들기</a></div>
</body>
</html>"""
    return HTMLResponse(html, headers=_NOINDEX)
