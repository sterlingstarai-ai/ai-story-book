"""
PDF Generation Service
책을 PDF로 내보내기
"""

import io
from typing import Optional
from urllib.parse import urlparse
import ipaddress
import socket
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
import httpx
from pathlib import Path
import structlog

from ..models.dto import BookResult, PageResult
from ..core.config import settings

logger = structlog.get_logger()

# Allowed domains for image fetching (SSRF protection)
ALLOWED_IMAGE_DOMAINS = {
    "picsum.photos",  # Mock images
    "s3.amazonaws.com",
    "r2.cloudflarestorage.com",
}

# Maximum image size (10MB)
MAX_IMAGE_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# CJK 폰트 (H1)
# ---------------------------------------------------------------------------
# reportlab 의 TTFont 은 **TrueType(glyf) 아웃라인만** 지원한다. apt `fonts-noto-cjk`가
# 설치하는 NotoSansCJK*.ttc 와 macOS AppleSDGothicNeo.ttc 는 CFF/PostScript 아웃라인이라
# 등록 자체가 실패한다("postscript outlines are not supported") — 그래서 시스템 폰트에
# 의존하는 순간 조용히 Helvetica 로 떨어지고 한/일/중 본문이 ■ 로 렌더된다.
# 따라서 정적 TrueType(가변폰트를 wght=400 으로 인스턴싱)을 리포에 번들한다.
# 라이선스: assets/fonts/OFL.txt (SIL Open Font License 1.1)
FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"

# 언어별 폰트 — 한자 자형은 지역별로 다르므로(예: 直·骨) 언어에 맞는 폰트를 쓴다.
# NotoSansKR 은 가나·간체 일부를 커버하지 못하고, NotoSansSC 는 한글을 커버하지 못한다
# (실측 확인) — 하나로 합칠 수 없다.
LANGUAGE_FONTS: dict[str, tuple[str, str]] = {
    "ko": ("NotoSansKR", "NotoSansKR-Regular.ttf"),
    "ja": ("NotoSansJP", "NotoSansJP-Regular.ttf"),
    "zh": ("NotoSansSC", "NotoSansSC-Regular.ttf"),
}
CJK_LANGUAGES = frozenset(LANGUAGE_FONTS)

# 라틴 계열(en/es)은 내장 Helvetica 로 충분하다.
DEFAULT_FONT = "Helvetica"

_REGISTERED_FONTS: set[str] = set()

# PDF 자체 문구(chrome)는 책 언어를 따른다. 한국어로 고정하면 영어·스페인어 책에서도
# 한글이 그려지는데, 그 언어는 CJK 폰트를 싣지 않으므로 그대로 ■ 가 된다(H1의 사촌).
PDF_CHROME: dict[str, dict[str, str]] = {
    "ko": {"end": "~ 끝 ~", "copyright": "AI Story Book으로 생성됨"},
    "en": {"end": "~ The End ~", "copyright": "Created with AI Story Book"},
    "ja": {"end": "~ おわり ~", "copyright": "AI Story Book で作成"},
    "zh": {"end": "~ 完 ~", "copyright": "由 AI Story Book 生成"},
    "es": {"end": "~ Fin ~", "copyright": "Creado con AI Story Book"},
}


def pdf_chrome(language: Optional[str]) -> dict[str, str]:
    """책 언어에 맞는 PDF 자체 문구."""
    lang = (language or "").strip().lower()
    return PDF_CHROME.get(lang, PDF_CHROME["en"])


class PDFFontError(Exception):
    """CJK 폰트를 등록할 수 없어 PDF 본문이 깨질 상황.

    조용한 Helvetica 폴백 금지(H1): 폴백하면 사용자는 '성공한 PDF'를 받고 그 안의 글자가
    전부 ■ 다. 배포 구성 결함이므로 시끄럽게 실패한다.
    """


def resolve_pdf_font(language: Optional[str]) -> str:
    """책 언어에 맞는 등록된 폰트 이름을 반환한다.

    CJK 언어인데 번들 폰트를 등록할 수 없으면 PDFFontError 를 던진다(폴백하지 않는다).
    """
    lang = (language or "").strip().lower()
    entry = LANGUAGE_FONTS.get(lang)
    if entry is None:
        return DEFAULT_FONT

    font_name, filename = entry
    if font_name in _REGISTERED_FONTS:
        return font_name

    font_path = FONT_DIR / filename
    if not font_path.exists():
        raise PDFFontError(
            f"{lang} PDF에 필요한 번들 폰트가 없습니다: {font_path}"
        )
    try:
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    except Exception as e:  # 손상된 파일·미지원 아웃라인 등
        raise PDFFontError(
            f"{lang} PDF 폰트 등록 실패({font_path}): {e}"
        ) from e

    _REGISTERED_FONTS.add(font_name)
    logger.info("CJK font registered", language=lang, font=font_name)
    return font_name


class PDFService:
    """PDF 생성 서비스"""

    def __init__(self):
        self.page_size = landscape(A4)  # 가로 방향
        self.margin = 20 * mm
        # 폰트는 책 언어에 따라 generate_pdf 에서 결정한다(H1). 생성자에서 하나로 고정하면
        # 언어별 자형을 고를 수 없고, 등록 실패가 조용한 폴백으로 묻힌다.
        self.font_name = DEFAULT_FONT

    async def generate_pdf(self, book: BookResult) -> bytes:
        """책을 PDF로 생성"""
        language = getattr(book.language, "value", book.language)
        # CJK 폰트를 못 구하면 여기서 시끄럽게 실패한다 — 글자가 ■ 인 PDF를 배달하지 않는다.
        self.font_name = resolve_pdf_font(language)

        buffer = io.BytesIO()

        c = canvas.Canvas(buffer, pagesize=self.page_size)
        width, height = self.page_size

        # 표지 페이지
        await self._draw_cover_page(c, book, width, height)
        c.showPage()

        # 본문 페이지들
        for page in book.pages:
            await self._draw_content_page(c, page, width, height)
            c.showPage()

        # 마지막 페이지 (끝)
        self._draw_end_page(c, book, width, height)

        c.save()
        buffer.seek(0)
        return buffer.getvalue()

    async def _draw_cover_page(
        self, c: canvas.Canvas, book: BookResult, width: float, height: float
    ):
        """표지 페이지 그리기"""
        # 배경 이미지
        if book.cover_image_url:
            try:
                image_data = await self._fetch_image(book.cover_image_url)
                if image_data:
                    img = ImageReader(io.BytesIO(image_data))
                    c.drawImage(
                        img,
                        0,
                        0,
                        width=width,
                        height=height,
                        preserveAspectRatio=True,
                        anchor="c",
                    )
            except Exception as e:
                # 이미지 로드 실패 시 배경색으로 대체
                logger.warning("Cover image load failed, using fallback", error=str(e))
                c.setFillColorRGB(0.4, 0.4, 0.8)
                c.rect(0, 0, width, height, fill=1)

        # 반투명 오버레이
        c.setFillColorRGB(0, 0, 0, 0.4)
        c.rect(0, 0, width, height * 0.4, fill=1)

        # 제목
        c.setFillColorRGB(1, 1, 1)
        c.setFont(self.font_name, 48)

        # 제목 텍스트 중앙 정렬
        title = book.title
        title_width = c.stringWidth(title, self.font_name, 48)
        x = (width - title_width) / 2
        c.drawString(x, height * 0.2, title)

    async def _draw_content_page(
        self, c: canvas.Canvas, page: PageResult, width: float, height: float
    ):
        """본문 페이지 그리기"""
        # 레이아웃: 왼쪽 이미지, 오른쪽 텍스트
        image_width = width * 0.55
        text_width = width * 0.40

        # 이미지 영역
        if page.image_url:
            try:
                image_data = await self._fetch_image(page.image_url)
                if image_data:
                    img = ImageReader(io.BytesIO(image_data))
                    img_height = height - (self.margin * 2)
                    c.drawImage(
                        img,
                        self.margin,
                        self.margin,
                        width=image_width - self.margin,
                        height=img_height,
                        preserveAspectRatio=True,
                        anchor="nw",
                    )
            except Exception as e:
                logger.warning(
                    "Page image load failed",
                    page=page.page_number,
                    error=str(e),
                )

        # 텍스트 영역
        text_x = image_width + self.margin
        text_y = height - self.margin - 50

        # 페이지 번호
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.setFont(self.font_name, 14)
        c.drawString(text_x, height - self.margin, f"- {page.page_number} -")

        # 본문 텍스트
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.setFont(self.font_name, 24)

        # 텍스트 줄바꿈 처리
        lines = self._wrap_text(page.text, text_width - self.margin, 24)
        line_height = 36

        for i, line in enumerate(lines):
            y = text_y - (i * line_height)
            if y < self.margin:
                break
            c.drawString(text_x, y, line)

    def _draw_end_page(
        self, c: canvas.Canvas, book: BookResult, width: float, height: float
    ):
        """마지막 페이지 그리기"""
        # 배경
        c.setFillColorRGB(0.95, 0.95, 0.95)
        c.rect(0, 0, width, height, fill=1)

        # 끝 텍스트
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.setFont(self.font_name, 36)

        chrome = pdf_chrome(getattr(book.language, "value", book.language))
        end_text = chrome["end"]
        text_width = c.stringWidth(end_text, self.font_name, 36)
        c.drawString((width - text_width) / 2, height / 2 + 50, end_text)

        # 제목 (작은 글씨)
        c.setFont(self.font_name, 18)
        title_width = c.stringWidth(book.title, self.font_name, 18)
        c.drawString((width - title_width) / 2, height / 2 - 20, book.title)

        # 저작권
        c.setFont(self.font_name, 12)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        copyright_text = chrome["copyright"]
        copy_width = c.stringWidth(copyright_text, self.font_name, 12)
        c.drawString((width - copy_width) / 2, self.margin, copyright_text)

    def _wrap_text(self, text: str, max_width: float, font_size: int) -> list[str]:
        """텍스트를 지정된 너비에 맞게 줄바꿈 (한국어 문자 단위 지원)"""
        lines = []
        current_line = ""
        current_width = 0.0

        for char in text:
            # 한글/CJK 문자는 font_size, 영문/숫자는 font_size * 0.5
            char_width = font_size if ord(char) > 127 else font_size * 0.5

            if current_width + char_width > max_width and current_line:
                lines.append(current_line)
                current_line = ""
                current_width = 0.0

            current_line += char
            current_width += char_width

        if current_line:
            lines.append(current_line)

        return lines

    def _is_url_allowed(self, url: str) -> bool:
        """URL이 허용된 도메인인지 확인 (SSRF 방지)"""
        try:
            parsed = urlparse(url)

            # Only allow http and https
            if parsed.scheme not in ("http", "https"):
                return False

            hostname = parsed.hostname
            if not hostname:
                return False

            # Check against allowed domains
            # Also allow S3 endpoint + public URL host from settings.
            # H11: 저장되는 모든 책 이미지 URL은 s3_public_url/{key}로 만들어지므로
            # (storage.py), s3_endpoint 호스트만 허용하면 R2 공개도메인/CDN 구성에서
            # 삽화가 전부 차단돼 텍스트-only PDF가 된다. storage.py 가드와 동일하게 포함.
            s3_host = urlparse(settings.s3_endpoint).hostname or ""
            s3_public_host = urlparse(settings.s3_public_url).hostname or ""
            allowed = ALLOWED_IMAGE_DOMAINS | {s3_host, s3_public_host}
            allowed.discard("")
            if settings.debug or settings.testing:
                allowed |= {"localhost", "127.0.0.1"}

            # Check exact match or subdomain match
            for domain in allowed:
                if hostname == domain or hostname.endswith(f".{domain}"):
                    return True

            # Block private IP ranges
            try:
                ip = ipaddress.ip_address(socket.gethostbyname(hostname))
                if ip.is_private or ip.is_loopback or ip.is_reserved:
                    # Allow localhost in debug mode
                    if not (settings.debug and ip.is_loopback):
                        return False
            except (socket.gaierror, ValueError):
                # SECURITY: Fail-closed - block if we can't resolve
                # This prevents DNS rebinding and other SSRF attacks
                logger.warning(
                    "DNS resolution failed for URL validation", hostname=hostname
                )
                return False

            return False
        except Exception:
            return False

    async def _fetch_image(self, url: str) -> Optional[bytes]:
        """URL에서 이미지 다운로드 (SSRF 보호 포함)"""
        try:
            # Validate URL before fetching
            if not self._is_url_allowed(url):
                logger.warning("Image URL not allowed", url=url[:100])
                return None

            async with httpx.AsyncClient(timeout=30) as client:
                # First, do a HEAD request to check size
                head_response = await client.head(url)
                content_length = int(head_response.headers.get("content-length", 0))
                if content_length > MAX_IMAGE_SIZE:
                    logger.warning(
                        "Image too large", url=url[:100], size=content_length
                    )
                    return None

                # Fetch the image
                response = await client.get(url)
                if response.status_code == 200:
                    # Double-check size after download
                    if len(response.content) > MAX_IMAGE_SIZE:
                        logger.warning("Image exceeded size limit", url=url[:100])
                        return None
                    return response.content
        except Exception as e:
            logger.debug("Failed to fetch image", url=url[:100], error=str(e))
        return None


# 싱글톤 인스턴스
pdf_service = PDFService()
