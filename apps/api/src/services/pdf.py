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
    "localhost",
    "127.0.0.1",
    "picsum.photos",  # Mock images
    "s3.amazonaws.com",
    "r2.cloudflarestorage.com",
}

# Maximum image size (10MB)
MAX_IMAGE_SIZE = 10 * 1024 * 1024


class PDFService:
    """PDF 생성 서비스"""

    def __init__(self):
        self.page_size = landscape(A4)  # 가로 방향
        self.margin = 20 * mm
        self._register_fonts()

    def _register_fonts(self):
        """한글 폰트 등록"""
        # 시스템 폰트 경로들
        font_paths = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # Linux
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
            "/app/assets/fonts/NanumGothic.ttf",  # Docker
        ]

        for font_path in font_paths:
            if Path(font_path).exists():
                try:
                    pdfmetrics.registerFont(TTFont("Korean", font_path))
                    self.font_name = "Korean"
                    return
                except Exception:
                    continue

        # 폰트를 찾지 못하면 기본 폰트 사용
        self.font_name = "Helvetica"

    async def generate_pdf(self, book: BookResult) -> bytes:
        """책을 PDF로 생성"""
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
            except Exception:
                # 이미지 로드 실패 시 배경색으로 대체
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
            except Exception:
                pass

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

        end_text = "~ 끝 ~"
        text_width = c.stringWidth(end_text, self.font_name, 36)
        c.drawString((width - text_width) / 2, height / 2 + 50, end_text)

        # 제목 (작은 글씨)
        c.setFont(self.font_name, 18)
        title_width = c.stringWidth(book.title, self.font_name, 18)
        c.drawString((width - title_width) / 2, height / 2 - 20, book.title)

        # 저작권
        c.setFont(self.font_name, 12)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        copyright_text = "AI Story Book으로 생성됨"
        copy_width = c.stringWidth(copyright_text, self.font_name, 12)
        c.drawString((width - copy_width) / 2, self.margin, copyright_text)

    def _wrap_text(self, text: str, max_width: float, font_size: int) -> list[str]:
        """텍스트를 지정된 너비에 맞게 줄바꿈"""
        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}".strip()
            # 간단한 너비 계산 (한글은 대략 font_size, 영문은 font_size * 0.5)
            estimated_width = sum(
                font_size if ord(c) > 127 else font_size * 0.5 for c in test_line
            )

            if estimated_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

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
            # Also allow S3 endpoint from settings
            s3_host = urlparse(settings.s3_endpoint).hostname or ""
            allowed = ALLOWED_IMAGE_DOMAINS | {s3_host}

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
