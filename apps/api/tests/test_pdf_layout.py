"""Actual PDF drawing must preserve long stories and stay inside page bounds."""

import asyncio
import re
from datetime import datetime

import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from src.models.dto import BookResult, PageResult
from src.services.pdf import PDFService, resolve_pdf_font


def book(text, *, title="비 오는 날의 작은 도서관", language="ko"):
    return BookResult(
        book_id="layout-test", title=title, language=language, target_age="5-7",
        style="watercolor", cover_image_url="local-cover.png",
        pages=[PageResult(page_number=1, text=text, image_url="local-page.png", image_prompt="scene")],
        created_at=datetime(2026, 9, 6),
    )


@pytest.fixture
def recorded_pdf(monkeypatch):
    records = []
    original = canvas.Canvas

    class RecordingCanvas(original):
        def drawString(self, x, y, text, *args, **kwargs):
            records.append((self.getPageNumber(), x, y, text, self._fontname, self._fontsize))
            return super().drawString(x, y, text, *args, **kwargs)

    async def no_image(self, url):
        return None

    monkeypatch.setattr(canvas, "Canvas", RecordingCanvas)
    monkeypatch.setattr(PDFService, "_fetch_image", no_image)
    return PDFService(), records


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "가나다라마바사아자차카타파하" * 57 + "끝!",
    ("따뜻한 도서관에서 친구들은 젖은 책을 함께 말렸어요. " * 40)[:798] + "끝!",
    "W" * 798 + "!!",
])
async def test_maximum_length_story_is_not_truncated_or_clipped(recorded_pdf, text):
    service, records = recorded_pdf
    assert len(text) == 800
    result = await service.generate_pdf(book(text))
    assert result.startswith(b"%PDF")
    last_sheet = max(record[0] for record in records)
    body = [record for record in records if 1 < record[0] < last_sheet and record[5] >= 18]
    assert re.sub(r"\s+", "", "".join(record[3] for record in body)) == re.sub(r"\s+", "", text)
    assert len({record[0] for record in body}) > 1, "800 characters need explicit readable continuation sheets"
    width, height = service.page_size
    for _, x, y, line, font, size in body:
        ascent, descent = pdfmetrics.getAscentDescent(font, size)
        assert x + pdfmetrics.stringWidth(line, font, size) <= width - service.margin + 0.01
        assert y + descent >= service.margin - 0.01
        assert y + ascent <= height - service.margin


@pytest.mark.asyncio
async def test_eighty_character_cover_title_wraps_inside_opaque_title_panel(recorded_pdf):
    service, records = recorded_pdf
    title = "도서관의 친구들과 함께하는 따뜻하고 즐거운 작은 모험 " * 3
    title = (title + "마지막 이야기")[:80]
    assert len(title) == 80
    await service.generate_pdf(book("친구들이 모였어요.", title=title))
    cover = [record for record in records if record[0] == 1 and record[5] >= 20]
    assert len(cover) > 1
    assert re.sub(r"\s+", "", "".join(record[3] for record in cover)) == re.sub(r"\s+", "", title)
    width, height = service.page_size
    for _, x, y, line, font, size in cover:
        assert x >= width * 0.52
        assert x + pdfmetrics.stringWidth(line, font, size) < width
        assert 0 < y < height


def test_korean_wrap_keeps_words_and_punctuation_together_using_font_metrics():
    service = PDFService()
    service.font_name = resolve_pdf_font("ko")
    text = '밤새 비가 주룩주룩 내렸어요. "어? 물이 새고 있잖아!"'
    max_width = max(pdfmetrics.stringWidth(word, service.font_name, 24) for word in text.split()) + 5
    lines = service._wrap_text(text, max_width, 24)
    assert " ".join(lines).split() == text.split()
    assert all(pdfmetrics.stringWidth(line, service.font_name, 24) <= max_width for line in lines)
    assert not any(line.startswith(("!", ".", ",")) for line in lines)


def test_unspaced_cjk_wrap_preserves_punctuation_and_all_characters():
    service = PDFService()
    service.font_name = resolve_pdf_font("ja")
    text = "森の友だちは「本を守ろう！」と言いました。みんなで図書館に集まります。"
    width = pdfmetrics.stringWidth("森の友だちは", service.font_name, 24)
    lines = service._wrap_text(text, width, 24)
    assert "".join(lines) == text
    assert all(pdfmetrics.stringWidth(line, service.font_name, 24) <= width for line in lines)
    assert all(line[0] not in "！。」" for line in lines)
    assert all(line[-1] != "「" for line in lines)


@pytest.mark.asyncio
async def test_concurrent_books_do_not_share_mutable_language_font(monkeypatch):
    waiting = asyncio.Event()
    calls = 0

    async def pause_image(self, url):
        nonlocal calls
        calls += 1
        if calls == 2:
            waiting.set()
        await asyncio.wait_for(waiting.wait(), timeout=2)
        return None

    monkeypatch.setattr(PDFService, "_fetch_image", pause_image)
    service = PDFService()
    korean, english = await asyncio.gather(
        service.generate_pdf(book("우리의 작은 도서관 이야기.")),
        service.generate_pdf(book("A story about our library.", title="Our Library", language="en")),
    )
    assert b"NotoSansKR" in korean and b"ZapfDingbats" not in korean
    assert b"NotoSansKR" not in english
