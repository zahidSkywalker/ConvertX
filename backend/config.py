"""
Application configuration — environment variables, constants, allowed file types.

Every value has a safe default so the app runs locally with zero config.
Override via environment variables or .env file in production.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present (local development only, ignored in production containers)
load_dotenv()


# ─── Environment ───────────────────────────────────────────────────────────────
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
DEBUG: bool = ENVIRONMENT == "development"


# ─── Server ────────────────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))


# ─── CORS ──────────────────────────────────────────────────────────────────────
# Comma-separated origins. On Render/Vercel, set this to your frontend domain.
ALLOWED_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://localhost:8000"
    ).split(",")
    if origin.strip()
]


# ─── File Handling ─────────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES: int = int(os.getenv("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024
MAX_FILE_SIZE_MB: int = MAX_FILE_SIZE_BYTES // (1024 * 1024)

MAX_FILES_PER_REQUEST: int = int(os.getenv("MAX_FILES_PER_REQUEST", "20"))

# Temp directories — all uploaded and converted files live here
TEMP_DIR: Path = Path(os.getenv("TEMP_DIR", "/tmp/convertx"))
UPLOAD_DIR: Path = TEMP_DIR / "uploads"
OUTPUT_DIR: Path = TEMP_DIR / "outputs"

# How long (seconds) before temp files are auto-deleted
FILE_TTL_SECONDS: int = int(os.getenv("FILE_TTL_SECONDS", "600"))  # 10 minutes

# How often (seconds) the background cleanup task scans for expired files
CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "300"))  # 5 minutes


# ─── External Tools ────────────────────────────────────────────────────────────
# Paths to system-installed tools. Override only if they're in a non-standard location.
LIBREOFFICE_PATH: str = os.getenv("LIBREOFFICE_PATH", "libreoffice")
TESSERACT_PATH: str = os.getenv("TESSERACT_PATH", "tesseract")


# ─── Allowed MIME Types & Extensions ───────────────────────────────────────────
ALLOWED_MIME_TYPES: dict[str, list[str]] = {
    "application/pdf": [
        ".pdf",
    ],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
        ".docx",
    ],
    "image/jpeg": [
        ".jpg",
        ".jpeg",
    ],
    "image/png": [
        ".png",
    ],
    "image/webp": [
        ".webp",
    ],
}

# Reverse lookup: extension → MIME type (built once at import time)
EXTENSION_TO_MIME: dict[str, str] = {}
for _mime, _extensions in ALLOWED_MIME_TYPES.items():
    for _ext in _extensions:
        EXTENSION_TO_MIME[_ext] = _mime

# Which MIME types each conversion tool accepts
TOOL_INPUT_TYPES: dict[str, list[str]] = {
    "pdf-to-word": ["application/pdf"],
    "word-to-pdf": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ],
    "image-to-pdf": ["image/jpeg", "image/png", "image/webp"],
    "image-to-excel": ["image/jpeg", "image/png", "image/webp"],
}


# ─── Magic Bytes — first bytes of each file type for server-side verification ──
MAGIC_BYTE_SIGNATURES: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/webp": b"RIFF",
}


# ─── Create directories on import ─────────────────────────────────────────────
# Uses exist_ok=True so this is safe across multiple worker processes.
TEMP_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
