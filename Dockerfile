# ─── Backend Dockerfile for Render / Railway ──────────────────────────────
# Installs Python dependencies, LibreOffice, Tesseract, and WeasyPrint.

FROM python:3.11-slim AS builder

# Install system dependencies required by Python packages (e.g., WeasyPrint)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev libjpeg62-turbo-dev libopenjp2-7-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Final Stage ──────────────────────────────────────────────────────────
FROM python:3.11-slim

# Install runtime dependencies: LibreOffice, Tesseract, WeasyPrint OS libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    tesseract-ocr \
    tesseract-ocr-eng \
    libpango-1.0-0 \
    libharfbuzz0b \
    libjpeg62-turbo \
    libopenjp2-7 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=installer /install /usr/local

WORKDIR /app

# Copy backend code
COPY backend/ ./backend/

# Expose port (Render/Railway inject $PORT)
EXPOSE 8000

# Run uvicorn
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
