"""
Application configuration — centralized settings with environment overrides.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Environment ────────────────────────────────────────────────────────────
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
DEBUG: bool = ENVIRONMENT == "development"
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))

# ─── CORS ───────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://localhost:8000"
    ).split(",")
    if origin.strip()
]

# ─── File Handling ──────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES: int = int(os.getenv("MAX_FILE_SIZE_MB", "10")) * 1024 * 1024
MAX_FILE_SIZE_MB: int = MAX_FILE_SIZE_BYTES // (1024 * 1024)
MAX_FILES_PER_REQUEST: int = int(os.getenv("MAX_FILES_PER_REQUEST", "20"))

TEMP_DIR: Path = Path(os.getenv("TEMP_DIR", "/tmp/convertx"))
UPLOAD_DIR: Path = TEMP_DIR / "uploads"
OUTPUT_DIR: Path = TEMP_DIR / "outputs"

FILE_TTL_SECONDS: int = int(os.getenv("FILE_TTL_SECONDS", "600"))
CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "300"))

# ─── External Tools ─────────────────────────────────────────────────────────
LIBREOFFICE_PATH: str = os.getenv("LIBREOFFICE_PATH", "libreoffice")
TESSERACT_PATH: str = os.getenv("TESSERACT_PATH", "tesseract")

# ─── Allowed MIME Types ─────────────────────────────────────────────────────
ALLOWED_MIME_TYPES: dict[str, list[str]] = {
    "application/pdf": [".pdf"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/webp": [".webp"],
    "text/html": [".html", ".htm"],
}

EXTENSION_TO_MIME: dict[str, str] = {}
for _mime, _extensions in ALLOWED_MIME_TYPES.items():
    for _ext in _extensions:
        EXTENSION_TO_MIME[_ext] = _mime

# Map tools to their allowed input MIME types
TOOL_INPUT_TYPES: dict[str, list[str]] = {
    # PDF Core
    "merge-pdf": ["application/pdf"],
    "split-pdf": ["application/pdf"],
    "rotate-pdf": ["application/pdf"],
    "compress-pdf": ["application/pdf"],
    "watermark-pdf": ["application/pdf"],
    "add-page-numbers": ["application/pdf"],
    "organize-pages": ["application/pdf"],
    "repair-pdf": ["application/pdf"],
    "pdf-to-image": ["application/pdf"],
    
    # PDF Extraction
    "pdf-to-word": ["application/pdf"],
    "pdf-to-excel": ["application/pdf"],
    "pdf-to-powerpoint": ["application/pdf"],
    
    # Office to PDF
    "word-to-pdf": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
    "excel-to-pdf": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    "powerpoint-to-pdf": ["application/vnd.openxmlformats-officedocument.presentationml.presentation"],
    
    # Advanced PDF
    "edit-pdf": ["application/pdf"],
    "ocr-pdf": ["application/pdf"],
    
    # Image Tools
    "image-to-pdf": ["image/jpeg", "image/png", "image/webp"],
    "image-to-excel": ["image/jpeg", "image/png", "image/webp"],
    
    # HTML
    "html-to-pdf": ["text/html"],
}

# ─── Magic Bytes ────────────────────────────────────────────────────────────
MAGIC_BYTE_SIGNATURES: dict[str, bytes] = {
    "application/pdf": b"%PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK\x03\x04",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": b"PK\x03\x04",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/webp": b"RIFF",
    "text/html": b"<!DO",  # Checks for <!DOCTYPE or <html
}

# ─── Directory Init ─────────────────────────────────────────────────────────
TEMP_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
