"""H1 회귀 게이트 — PDF의 CJK 본문이 실제로 렌더되는지.

2026-08-09 중간 E2E: 유료(베이직+) 기능인 PDF에서 한국어 본문이 **전부 검은 사각형**
으로 나왔다. `pdf.py`의 폰트 탐색 경로 3종이 프로덕션 이미지에서 전부 미충족이라
조용히 `Helvetica`로 폴백했고, reportlab이 표현 불가 문자를 ZapfDingbats 'n'(=■)으로
치환했기 때문이다. 스토리 언어는 ko/en/ja/zh/es이므로 ko·ja·zh 전부를 커버해야 한다.

'PDF가 200으로 내려왔다'는 이 결함을 잡지 못한다 — **임베드된 폰트**를 봐야 한다.
"""

import re
from datetime import datetime

import pytest

from src.models.dto import BookResult, PageResult
from src.services.pdf import CJK_LANGUAGES, PDFFontError, PDFService


def _basefonts(pdf: bytes) -> set[str]:
    return {m.decode() for m in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+#,\-]+)", pdf)}


def _make_book(language: str, title: str, text: str) -> BookResult:
    return BookResult(
        book_id="book_font_test",
        title=title,
        language=language,
        target_age="5-7",
        style="watercolor",
        cover_image_url="https://example.com/cover.png",
        pages=[
            PageResult(
                page_number=i,
                text=text,
                image_url="https://example.com/p.png",
                image_prompt="prompt",
            )
            for i in range(1, 3)
        ],
        created_at=datetime(2026, 8, 9, 0, 0, 0),
    )


@pytest.fixture()
def offline_pdf(monkeypatch):
    """네트워크 경계만 차단(이미지 다운로드) — 폰트 임베드가 검증 대상이다."""

    async def _no_image(self, url):  # noqa: ANN001
        return None

    monkeypatch.setattr(PDFService, "_fetch_image", _no_image, raising=True)
    return PDFService()


CJK_CASES = [
    ("ko", "용감한 토끼의 숲속 모험", "토끼는 숲속을 걸으며 새로운 모험을 시작했어요.", "NotoSansKR"),
    ("ja", "勇敢なウサギの森の冒険", "ウサギは森を歩いて新しい冒険を始めました。", "NotoSansJP"),
    ("zh", "勇敢的兔子森林冒险", "兔子走进森林，开始了新的冒险。", "NotoSansSC"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("language,title,text,expected_font", CJK_CASES)
async def test_cjk_pdf_embeds_language_font(
    offline_pdf, language, title, text, expected_font
):
    pdf = await offline_pdf.generate_pdf(_make_book(language, title, text))
    fonts = _basefonts(pdf)

    assert any(expected_font in f for f in fonts), (
        f"{language} PDF에 {expected_font} 가 임베드되지 않았다 — CJK 본문이 깨진다. "
        f"BaseFont={sorted(fonts)}"
    )
    assert not any("ZapfDingbats" in f for f in fonts), (
        f"{language} PDF가 ZapfDingbats 치환을 포함한다(= 글자가 ■로 렌더). "
        f"BaseFont={sorted(fonts)}"
    )


@pytest.mark.asyncio
async def test_latin_pdf_still_renders(offline_pdf):
    """en/es는 CJK 폰트가 필요 없다 — 기존 동작 유지(불필요한 회귀 금지)."""
    pdf = await offline_pdf.generate_pdf(
        _make_book("en", "The Brave Rabbit", "The rabbit started a new adventure.")
    )
    assert pdf.startswith(b"%PDF"), "en PDF 생성 실패"
    assert not any("ZapfDingbats" in f for f in _basefonts(pdf)), "en에서 글리프 치환 발생"


@pytest.mark.asyncio
async def test_missing_cjk_font_fails_loudly(offline_pdf, monkeypatch):
    """폰트 파일이 없으면 **조용한 Helvetica 폴백 금지** — 명시 실패.

    조용한 폴백이 바로 H1이 배포까지 살아남은 이유다(로그는 debug 레벨이었다).
    """
    from src.services import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "FONT_DIR", pdf_module.FONT_DIR / "__missing__")
    monkeypatch.setattr(pdf_module, "_REGISTERED_FONTS", set(), raising=False)

    with pytest.raises(PDFFontError):
        await offline_pdf.generate_pdf(
            _make_book("ko", "폰트 없음", "한국어 본문입니다.")
        )


def test_cjk_language_set_covers_story_languages():
    """스토리 생성 언어(ko/en/ja/zh/es) 중 CJK 3종이 폰트 대상으로 선언돼 있다."""
    assert CJK_LANGUAGES == {"ko", "ja", "zh"}
