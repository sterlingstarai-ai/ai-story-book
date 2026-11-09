"""Replay one explicitly fictional book inside the disposable runtime only."""

from contextvars import ContextVar
import hashlib
import io
import json
from pathlib import Path
import wave


REVIEW_ARCHIVE_ENV = "STORYBOOK_LOCAL_REVIEW_ARCHIVE"
REVIEW_REALTIME_KEY = "fixture-only-realtime-key"


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("Invalid review archive file")
    return path.read_bytes()


def _validate_realtime_wav(data: bytes) -> None:
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 24000):
                raise ValueError("Invalid Realtime review audio format")
            if not frames or len(audio.readframes(frames)) != frames * 2:
                raise ValueError("Invalid Realtime review audio length")
    except (EOFError, wave.Error) as error:
        raise ValueError("Invalid Realtime review audio") from error


def stage_review_archive(source: Path, target: Path, realtime_audio: Path | None = None) -> None:
    """Copy the validated story and media only. No old URLs or account IDs."""
    book, evidence = [json.loads(_read(source / name, 1024 * 1024)) for name in (
        "book.json", "result.json",
    )]
    title = book["title"]
    pages = book["pages"]
    if (evidence["status"] != "passed" or evidence["book_id"] != book["book_id"]
            or evidence["real_child_data"] is not False or evidence["data_scope"]["photos_used"] is not False
            or evidence["data_scope"]["appearance"] != "fictional_fixture"
            or (book["language"], book["target_age"], book["style"]) != ("ko", "7-9", "watercolor")
            or not isinstance(title, str) or not 1 <= len(title) <= 80
            or [page["page_number"] for page in pages] != list(range(1, 13))):
        raise ValueError("Review archive must contain a verified fictional Korean 7–9 book")
    if realtime_audio is None:
        audio_dir, extension = source / "review-audio", "mp3"
        audio = json.loads(_read(audio_dir / "result.json", 1024 * 1024))
        if (audio["status"] != "passed" or audio["fictional"] is not True
                or (audio["provider"], audio["style"], audio["voice"]) != ("google_gemini", "animated", "Kore")):
            raise ValueError("Invalid Gemini review narration evidence")
        clips = audio["clips"]
    else:
        audio_dir, extension = realtime_audio, "wav"
        audio = json.loads(_read(audio_dir / "verification.json", 1024 * 1024))
        if (audio["status"] != "FULL_BOOK_GENERATED_WITH_TARGETED_RECOVERY" or audio["synthesis_passed"] != 12
                or audio["failures"] or (audio["title"], audio["age"]) != (title, "7-9")
                or (audio["provider"], audio["style"], audio["voice"]) != ("OpenAI Realtime", "animated", "coral")):
            raise ValueError("Invalid Realtime review narration evidence")
        clips = audio["per_page"]
    if [clip["page"] for clip in clips] != list(range(1, 13)):
        raise ValueError("Review narration must include all twelve pages in order")
    texts = [page["text"] for page in pages]
    if (any(not isinstance(text, str) or not 1 <= len(text) <= 600 for text in texts)
            or len(set(texts)) != 12):
        raise ValueError("Review archive page texts are invalid")

    target.mkdir(mode=0o700)
    for page, (text, clip) in enumerate(zip(texts, clips, strict=True), 1):
        name = f"page-{page:02d}.{extension}"
        sound = _read(audio_dir / name, 8 * 1024 * 1024)
        if (hashlib.sha256(text.encode()).hexdigest() != clip["input_sha256"]
                or hashlib.sha256(sound).hexdigest() != clip["sha256"]):
            raise ValueError("Review narration does not match the archived page")
        if extension == "wav":
            _validate_realtime_wav(sound)
        (target / name).write_bytes(sound)
    for page in range(13):
        name = f"page-{page:02d}.png"
        data = _read(source / name, 12 * 1024 * 1024)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Review archive illustration is invalid")
        (target / name).write_bytes(data)
    (target / "story.json").write_text(json.dumps({"title": title, "texts": texts}, ensure_ascii=False))


def install_archive_replay(archive: Path, provider: str) -> None:
    from src.services import image, orchestrator, tts

    if provider == "openai_realtime":
        adapter, recorded_voice, extension = tts.RealtimeTTSProvider, "coral", "wav"
    else:
        adapter, recorded_voice, extension = tts.GeminiCloudTTSProvider, "Kore", "mp3"
    story = json.loads((archive / "story.json").read_text())
    title, texts = story["title"], story["texts"]
    clip_pages = {text: page for page, text in enumerate(texts, 1)}
    active = ContextVar("fictional_review_archive_active", default=False)
    start_book = orchestrator.start_book_generation
    generate_story = orchestrator.generate_story
    generate_mock_image = image._generate_mock

    async def start(job_id, spec, user_key, series_id=None, series_index=None):
        replay = (series_id is None
                  and (spec.topic, spec.language, spec.target_age, spec.page_count, spec.style)
                  == (title, "ko", "7-9", 12, "watercolor")
                  and not (spec.character_ids or spec.character_id or spec.character or spec.reference_image_base64))
        token = active.set(replay)
        try:
            return await start_book(job_id, spec, user_key, series_id, series_index)
        finally:
            active.reset(token)

    async def story_draft(spec):
        draft = await generate_story(spec)
        if not active.get():
            return draft
        return draft.model_copy(update={
            "title": title,
            "cover": draft.cover.model_copy(update={"cover_text": title}),
            "pages": [page.model_copy(update={"text": texts[page.page - 1]}) for page in draft.pages],
        })

    async def illustration(prompt):
        if not active.get():
            return await generate_mock_image(prompt)
        return await image._persist_image_bytes(
            (archive / f"page-{prompt.page:02d}.png").read_bytes(), "image/png", "mock",
        )

    async def narration(_provider, text, voice="default", *, language="ko", speaking_rate=1.0, style="legacy"):
        if (language != "ko" or speaking_rate != 1.0 or voice not in {"default", recorded_voice}
                or style != "animated" or text not in clip_pages):
            raise ValueError("This narration is unavailable in the local review archive")
        audio = (archive / f"page-{clip_pages[text]:02d}.{extension}").read_bytes()
        if extension == "mp3":
            tts._validate_gemini_mp3(audio, text)
        return audio

    orchestrator.start_book_generation = start
    orchestrator.generate_story = story_draft
    image._generate_mock = illustration
    adapter.synthesize = narration
