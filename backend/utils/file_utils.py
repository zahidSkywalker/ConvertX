"""
File utilities — secure upload handling, magic-byte validation,
temp file lifecycle, and download registry.
"""

import logging
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import UploadFile, HTTPException

from backend.config import (
    UPLOAD_DIR,
    OUTPUT_DIR,
    MAX_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_MB,
    ALLOWED_MIME_TYPES,
    EXTENSION_TO_MIME,
    MAGIC_BYTE_SIGNATURES,
    FILE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)


@dataclass
class FileEntry:
    original_filename: str
    file_path: Path
    created_at: float = field(default_factory=time.time)
    download_count: int = 0

_file_registry: dict[str, FileEntry] = {}


def register_output_file(original_filename: str, file_path: Path) -> str:
    uuid_name = f"{uuid.uuid4().hex}{file_path.suffix}"
    uuid_path = file_path.parent / uuid_name
    file_path.rename(uuid_path)
    _file_registry[uuid_name] = FileEntry(original_filename=original_filename, file_path=uuid_path)
    logger.info("Registered output: '%s' → '%s' (%.1f KB)", original_filename, uuid_name, uuid_path.stat().st_size / 1024)
    return uuid_name

def get_file_entry(uuid_filename: str) -> Optional[FileEntry]:
    return _file_registry.get(uuid_filename)

def unregister_file(uuid_filename: str) -> None:
    _file_registry.pop(uuid_filename, None)

def get_registry_size() -> int:
    return len(_file_registry)


def _validate_extension(file: UploadFile, allowed_types: Optional[list[str]] = None) -> str:
    if allowed_types is None:
        allowed_types = list(ALLOWED_MIME_TYPES.keys())
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()
    if not ext:
        raise HTTPException(status_code=400, detail="File has no extension.")
    if ext not in EXTENSION_TO_MIME:
        raise HTTPException(status_code=400, detail=f"Extension '{ext}' not supported. Allowed: {', '.join(sorted(EXTENSION_TO_MIME.keys()))}")
    mime = EXTENSION_TO_MIME[ext]
    if mime not in allowed_types:
        raise HTTPException(status_code=400, detail=f"File type '{mime}' not allowed for this tool.")
    return mime

def _validate_content_length(file: UploadFile) -> None:
    cl = file.headers.get("content-length")
    if cl:
        try:
            if int(cl) > MAX_FILE_SIZE_BYTES:
                raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_SIZE_MB}MB limit.")
        except ValueError:
            pass

def _validate_magic_bytes(file_path: Path, expected_mime: str) -> None:
    expected_bytes = MAGIC_BYTE_SIGNATURES.get(expected_mime)
    if not expected_bytes:
        return
    try:
        with open(file_path, "rb") as f:
            header = f.read(12)
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Cannot read uploaded file.")
    if not header:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    
    if expected_mime == "text/html":
        if not (header.lower().startswith(b"<!do") or header.lower().startswith(b"<html")):
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="File content does not match HTML format.")
    elif not header.startswith(expected_bytes):
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"File content does not match '{expected_mime}' format.")
    
    if expected_mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        if not _is_valid_docx(file_path):
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="File is a ZIP but not a valid .docx.")
    elif expected_mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        if not _is_valid_xlsx(file_path):
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="File is a ZIP but not a valid .xlsx.")
    elif expected_mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        if not _is_valid_pptx(file_path):
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="File is a ZIP but not a valid .pptx.")
    elif expected_mime == "image/webp":
        if len(header) < 12 or header[8:12] != b"WEBP":
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="RIFF header found but not valid WebP.")

def _is_valid_docx(fp: Path) -> bool:
    try:
        with zipfile.ZipFile(fp, "r") as zf:
            return any(n == "word/document.xml" for n in zf.namelist())
    except zipfile.BadZipFile:
        return False

def _is_valid_xlsx(fp: Path) -> bool:
    try:
        with zipfile.ZipFile(fp, "r") as zf:
            return any(n == "xl/workbook.xml" for n in zf.namelist())
    except zipfile.BadZipFile:
        return False

def _is_valid_pptx(fp: Path) -> bool:
    try:
        with zipfile.ZipFile(fp, "r") as zf:
            return any(n == "ppt/presentation.xml" for n in zf.namelist())
    except zipfile.BadZipFile:
        return False


async def save_upload_file(file: UploadFile, allowed_types: Optional[list[str]] = None) -> tuple[Path, str]:
    mime = _validate_extension(file, allowed_types)
    _validate_content_length(file)
    
    original_ext = Path(file.filename or "upload").suffix.lower()
    safe_filename = f"{uuid.uuid4().hex}{original_ext}"
    save_path = UPLOAD_DIR / safe_filename
    bytes_read = 0
    
    try:
        with open(save_path, "wb") as dest:
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > MAX_FILE_SIZE_BYTES:
                    dest.close()
                    save_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"File exceeds {MAX_FILE_SIZE_MB}MB limit ({bytes_read // (1024*1024)}MB).")
                dest.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        save_path.unlink(missing_ok=True)
        logger.error("Error saving upload: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save file.")
    
    _validate_magic_bytes(save_path, mime)
    logger.info("Saved upload: '%s' → %s (%d bytes)", file.filename, safe_filename, bytes_read)
    return save_path, mime


async def save_upload_files(files: list[UploadFile], allowed_types: Optional[list[str]] = None, max_count: Optional[int] = None) -> list[tuple[Path, str]]:
    from backend.config import MAX_FILES_PER_REQUEST
    limit = max_count or MAX_FILES_PER_REQUEST
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")
    if len(files) > limit:
        raise HTTPException(status_code=400, detail=f"Too many files. Max {limit}, got {len(files)}.")
    
    results = []
    for file in files:
        result = await save_upload_file(file, allowed_types)
        results.append(result)
    return results


def cleanup_expired_files() -> int:
    deleted = 0
    now = time.time()
    for directory in (UPLOAD_DIR, OUTPUT_DIR):
        if not directory.exists():
            continue
        for fp in directory.iterdir():
            if fp.is_file():
                try:
                    if now - fp.stat().st_mtime > FILE_TTL_SECONDS:
                        fp.unlink()
                        _file_registry.pop(fp.name, None)
                        deleted += 1
                except Exception:
                    pass
    orphaned = [n for n, e in _file_registry.items() if not e.file_path.exists()]
    for n in orphaned:
        _file_registry.pop(n, None)
    return deleted

def cleanup_all_files() -> None:
    total = 0
    for directory in (UPLOAD_DIR, OUTPUT_DIR):
        if directory.exists():
            for fp in directory.iterdir():
                if fp.is_file():
                    try:
                        fp.unlink()
                        total += 1
                    except Exception:
                        pass
    _file_registry.clear()
    if total:
        logger.info("Shutdown cleanup: %d files deleted", total)

def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    if size_bytes < 1024 * 1024: return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024: return f"{size_bytes / (1024*1024):.1f} MB"
    return f"{size_bytes / (1024*1024*1024):.1f} GB"


def _safe_delete(path: Path | None) -> None:
    """Delete a file silently. Used for temp cleanup in route error handlers."""
    if path and path.exists():
        try: path.unlink()
        except Exception: pass
