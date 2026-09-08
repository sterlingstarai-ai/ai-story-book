"""Version-checked narration publication with durable orphan cleanup."""
from dataclasses import dataclass
import uuid

from sqlalchemy import or_, select, update

from src.core.consent import require_parental_consent
from src.models.db import Book, Page
from src.services.audio_text import audio_texts
from src.services.purge_queue import cancel_purge_task, enqueue_purge_keys
from src.services.storage import storage_service


@dataclass(frozen=True)
class NarrationSource:
    book_id: str
    page_id: int
    page_number: int
    user_key: str
    book_language: str
    target_age: str
    text: str
    text_ko: str | None
    text_en: str | None

    @classmethod
    def from_page(cls, book, page):
        return cls(book.id, page.id, page.page_number, book.user_key,
                   book.language, book.target_age, page.text,
                   getattr(page, "text_ko", None), getattr(page, "text_en", None))

    @property
    def texts(self):
        return audio_texts(self.text, self.text_ko, self.text_en, self.book_language)

    def matches(self, page):
        return (page is not None and page.text == self.text
                and page.text_ko == self.text_ko and page.text_en == self.text_en)


def narration_url(page, language, book_language):
    url = getattr(page, f"audio_url_{language}", None) if language in {"ko", "en"} else None
    if language == book_language:
        url = url or getattr(page, "audio_url", None)
    return url


async def store_narration(db, book_id, page_number, language, audio_bytes, *, user_key=None):
    # A unique key prevents one failed concurrent attempt from purging another
    # successful attempt's file. The caller cancels the guard with its Page update.
    key = f"books/{book_id}/audio/page_{page_number}_{language}_{uuid.uuid4().hex}.mp3"
    guard = enqueue_purge_keys(db, user_key=user_key, reason="incomplete_narration", keys=[key])[0]
    await db.commit()
    url = await storage_service.upload_bytes(audio_bytes, key, content_type="audio/mpeg")
    return url, guard


async def publish_narration(db, source: NarrationSource, language, url, guard):
    """Only one matching, still-empty page slot may adopt the new file.

    SQL predicates protect PostgreSQL and SQLite alike; an ORM identity-map read
    followed by assignment would allow two concurrent generators to orphan the
    first file. Losing attempts keep their previously committed cleanup guard.
    """
    await require_parental_consent(db, source.user_key)
    column = getattr(Page, f"audio_url_{language}") if language in {"ko", "en"} else Page.audio_url
    predicates = [Page.id == source.page_id, Page.book_id == source.book_id,
                  Page.text == source.text, Page.text_ko == source.text_ko,
                  Page.text_en == source.text_en, or_(column.is_(None), column == ""),
                  select(Book.id).where(Book.id == source.book_id,
                                        Book.user_key == source.user_key,
                                        Book.language == source.book_language).exists()]
    values = {column.key: url}
    if language == source.book_language:
        predicates.append(or_(Page.audio_url.is_(None), Page.audio_url == ""))
        values["audio_url"] = url
    result = await db.execute(update(Page).where(*predicates).values(**values)
                              .execution_options(synchronize_session=False))
    if result.rowcount == 1:
        cancel_purge_task(guard)
        await db.commit()
        return url

    # A concurrent request may already have published valid audio. Reuse it,
    # without cancelling this losing upload's independent erasure guard.
    await db.commit()
    current = (await db.execute(select(Page).where(Page.id == source.page_id,
        Page.book_id == source.book_id).execution_options(populate_existing=True))).scalar_one_or_none()
    if source.matches(current):
        existing = narration_url(current, language, source.book_language)
        if existing:
            return existing
    raise ValueError("Narration page changed or is no longer available")
