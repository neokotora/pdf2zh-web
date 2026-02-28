# ---- Stage 1: Build dependencies ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt && \
    pip install --no-cache-dir --prefix=/install --force-reinstall \
        "opencv-python-headless>=4.0"

# ---- Stage 2: Runtime ----
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/neokotora/pdf2zh-web"
LABEL org.opencontainers.image.description="PDFMathTranslate Web UI"
LABEL org.opencontainers.image.licenses="AGPL-3.0"

# Install runtime system deps (if any native libs needed)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libxcb1 \
        libxext6 \
        libsm6 \
        libxrender1 \
        libgl1 \
        libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application code
COPY . /app/pdf2zh_next/

# Create data directory
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["uvicorn", "pdf2zh_next.api.app:app", "--host", "0.0.0.0", "--port", "7860", "--timeout-keep-alive", "65", "--limit-concurrency", "20"]
