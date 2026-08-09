# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim as production

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

# Copy application code
COPY --chown=appuser:appuser . .

# H1: PDF의 한/일/중 본문은 번들 TrueType 폰트로만 렌더된다. reportlab은 CFF/OTC
# (apt fonts-noto-cjk 가 설치하는 NotoSansCJK*.ttc)를 읽지 못하므로 시스템 폰트로는
# 대체할 수 없다. 자산이 빠진 채 배포되면 CJK PDF가 전부 ■ 로 나가므로 빌드에서 막는다.
RUN test -f assets/fonts/NotoSansKR-Regular.ttf \
 && test -f assets/fonts/NotoSansJP-Regular.ttf \
 && test -f assets/fonts/NotoSansSC-Regular.ttf \
 && test -f assets/fonts/OFL.txt

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Default command (API server)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
