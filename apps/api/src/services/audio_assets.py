"""Version-checked narration publication with durable orphan cleanup."""
from dataclasses import dataclass
from contextlib import asynccontextmanager
import hashlib
import secrets
import uuid

from sqlalchemy import delete, or_, select, update

from src.core.consent import require_parental_consent
from src.core.exceptions import APIError
from src.core.rate_limit import rate_limiter
from src.models.db import Book, NarrationVariant, Page, UserConsent
from src.services.audio_text import audio_texts
from src.services.purge_queue import cancel_purge_task, enqueue_purge_keys
from src.services.realtime_tts import RealtimeTranscriptMismatch
from src.services.storage import storage_service

_LOCK_TTL_SECONDS = 600
_UNLOCK = """if redis.call('get', KEYS[1]) == ARGV[1] then
return redis.call('del', KEYS[1]) else return 0 end"""


@asynccontextmanager
async def variant_singleflight(user_key, book_id, page_number, language, voice, style="legacy", provider="openai"):
    """Suppress duplicate live requests; fail closed if the shared lock is unavailable.

    An uncertain failure or cancellation keeps its bounded lock until expiry
    so a potentially still-running provider request is not duplicated.
    TTL is recovery, not proof against Redis loss or a long network partition.
    """
    identity = '\0'.join((user_key, book_id, str(page_number), language, voice, style, provider))
    key = 'narration:singleflight:' + hashlib.sha256(identity.encode()).hexdigest()
    token = secrets.token_hex(24)
    try:
        client = await rate_limiter.get_redis()
        acquired = await client.set(key, token, ex=_LOCK_TTL_SECONDS, nx=True)
    except Exception:
        raise APIError(503, 'SERVICE_UNAVAILABLE', '음성 생성 상태를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.') from None
    if not acquired:
        raise APIError(409, 'AUDIO_GENERATION_IN_PROGRESS', '이 목소리를 생성 중입니다. 잠시 후 다시 시도해 주세요.',
                       headers={'Retry-After': '10'})
    release_lock = True
    try:
        yield
    except BaseException as error:
        # The provider confirmed completion for a transcript mismatch. A local
        # budget rejection also leaves no outstanding synthesis request.
        release_lock = (
            isinstance(error, RealtimeTranscriptMismatch)
            or (isinstance(error, APIError) and error.error_code == 'SERVICE_BUDGET_EXCEEDED')
        )
        raise
    finally:
        if release_lock:
            try:
                await client.eval(_UNLOCK, 1, key, token)
            except Exception:
                # The bounded TTL recovers a lock Redis could not release.
                pass


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
    consent_id: int | None = None

    @classmethod
    def from_page(cls, book, page, *, consent_id=None):
        return cls(book.id, page.id, page.page_number, book.user_key,
                   book.language, book.target_age, page.text,
                   getattr(page, "text_ko", None), getattr(page, "text_en", None), consent_id)

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


async def variant_url(db, page_id, language, voice, style="legacy", provider="openai"):
    return await db.scalar(select(NarrationVariant.audio_url).where(
        NarrationVariant.page_id == page_id, NarrationVariant.language == language,
        NarrationVariant.voice == voice, NarrationVariant.style == style, NarrationVariant.provider == provider))


async def retire_page_variants(db, page_id, *, user_key):
    """Remove all voice variants atomically when their page text is changed.

    Caller must hold the page row lock until commit, as does publication.
    Book and account deletion already enqueue the containing book prefix.
    """
    from src.services.storage import key_from_public_url

    urls = (await db.scalars(select(NarrationVariant.audio_url).where(
        NarrationVariant.page_id == page_id))).all()
    enqueue_purge_keys(db, user_key=user_key, reason="replaced_page_audio",
                       keys=[key for key in (key_from_public_url(url) for url in urls) if key])
    await db.execute(delete(NarrationVariant).where(NarrationVariant.page_id == page_id))


async def _authorize_narration_owner(db, source: NarrationSource, job_id):
    from src.services.generation_consent import require_active_book_job
    from src.services.photo_lifecycle import lock_photo_account

    if job_id is None:
        await lock_photo_account(db, source.user_key)
        current = await require_parental_consent(db, source.user_key)
        if current is not None and current != source.consent_id:
            # Optional photo preferences also create decisions. An uninterrupted
            # chain of mandatory grants remains valid for an ordinary book.
            interrupted = source.consent_id is None or await db.scalar(select(UserConsent.id).where(
                UserConsent.user_key == source.user_key, UserConsent.id >= source.consent_id,
                UserConsent.granted.is_(False),
            ).limit(1)) is not None
            if interrupted:
                raise APIError(403, "PARENTAL_CONSENT_REQUIRED", "동의가 변경되었습니다. 낭독을 다시 요청해주세요.")
    else:
        await require_active_book_job(db, job_id, source.user_key)


async def authorize_narration(db, source: NarrationSource, *, job_id=None):
    await _authorize_narration_owner(db, source, job_id)
    current = await db.scalar(select(Page).where(
        Page.id == source.page_id, Page.book_id == source.book_id,
        select(Book.id).where(Book.id == source.book_id, Book.user_key == source.user_key,
                              Book.language == source.book_language).exists(),
    ).execution_options(populate_existing=True))
    if not source.matches(current):
        raise ValueError("Narration page changed or is no longer available")


async def publish_variant(db, source: NarrationSource, language, voice, url, guard, style="legacy", provider="openai"):
    """Publish one variant only if ownership, consent, and page text still match."""
    await _authorize_narration_owner(db, source, None)
    page = await db.scalar(select(Page).where(
        Page.id == source.page_id, Page.book_id == source.book_id,
        select(Book.id).where(Book.id == source.book_id, Book.user_key == source.user_key,
                              Book.language == source.book_language).exists(),
    ).with_for_update().execution_options(populate_existing=True))
    if not source.matches(page):
        raise ValueError("Narration page changed or is no longer available")
    existing = await variant_url(db, source.page_id, language, voice, style, provider)
    if existing:
        # The losing upload retains its durable cleanup guard.
        await db.commit()
        return existing
    db.add(NarrationVariant(id=uuid.uuid4().hex, page_id=source.page_id,
                            language=language, voice=voice, style=style, provider=provider, audio_url=url))
    cancel_purge_task(guard)
    await db.commit()
    return url


async def store_narration(db, book_id, page_number, language, audio_bytes, *, user_key=None):
    # A unique key prevents one failed concurrent attempt from purging another
    # successful attempt's file. The caller cancels the guard with its Page update.
    is_wav = audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE"
    extension, content_type = ("wav", "audio/wav") if is_wav else ("mp3", "audio/mpeg")
    key = f"books/{book_id}/audio/page_{page_number}_{language}_{uuid.uuid4().hex}.{extension}"
    guard = enqueue_purge_keys(db, user_key=user_key, reason="incomplete_narration", keys=[key])[0]
    await db.commit()
    url = await storage_service.upload_bytes(audio_bytes, key, content_type=content_type)
    return url, guard


async def publish_narration(db, source: NarrationSource, language, url, guard, *, job_id=None):
    """Only one matching, still-empty page slot may adopt the new file.

    SQL predicates protect PostgreSQL and SQLite alike; an ORM identity-map read
    followed by assignment would allow two concurrent generators to orphan the
    first file. Losing attempts keep their previously committed cleanup guard.
    """
    await _authorize_narration_owner(db, source, job_id)
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
            await db.commit()
            return existing
    raise ValueError("Narration page changed or is no longer available")
