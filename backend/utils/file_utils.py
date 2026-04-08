"""
File utilities — secure upload handling, magic-byte validation,
temp file lifecycle, and download registry.

Security measures:
  1. File extension validated against whitelist BEFORE saving.
  2. Content-Length header checked BEFORE saving.
  3. Actual byte count tracked WHILE streaming to disk.
  4. Magic bytes verified AFTER saving (file deleted on mismatch).
  5. DOCX files get an extra zip-structure check (PK signature is ambiguous).
  6. WEBP files get a secondary RIFF+WEBP check (RIFF signature is ambiguous).
  7. Download filenames are UUID-based — no path traversal possible.
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


# ═══════════════════════════════════════════════════════════════════════════════
# File Registry — tracks converted output files for secure download
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FileEntry:
    """Metadata about a converted file awaiting download."""
    original_filename: str
    file_path: Path
    created_at: float = field(default_factory=time.time)
    download_count: int = 0


# UUID filename → FileEntry mapping (in-memory, safe for single-instance deploys)
_file_registry: dict[str, FileEntry] = {}


def register_output_file(original_filename: str, file_path: Path) -> str:
    """
    Register a converted file for download.

    The file on disk is renamed to a UUID-based name to prevent path traversal
    and filename injection attacks. The original (user-friendly) name is stored
    in the registry and sent via Content-Disposition header on download.

    Args:
        original_filename: The human-readable filename for the download (e.g. "converted.pdf").
        file_path: The actual path where the converter saved the output file.

    Returns:
        The UUID-based filename to use in the download URL (e.g. "a1b2c3d4.pdf").
    """
    uuid_name = f"{uuid.uuid4().hex}{file_path.suffix}"
    uuid_path = file_path.parent / uuid_name
    file_path.rename(uuid_path)

    _file_registry[uuid_name] = FileEntry(
        original_filename=original_filename,
        file_path=uuid_path,
    )
    logger.info(
        "Registered output: '%s' → '%s' (%.1f KB)",
        original_filename,
        uuid_name,
        uuid_path.stat().st_size / 1024,
    )
    return uuid_name


def get_file_entry(uuid_filename: str) -> Optional[FileEntry]:
    """Look up a file entry by its UUID filename. Returns None if not found."""
    return _file_registry.get(uuid_filename)


def unregister_file(uuid_filename: str) -> None:
    """Remove a file entry from the registry (does NOT delete the file on disk)."""
    _file_registry.pop(uuid_filename, None)


def get_registry_size() -> int:
    """Return the number of files currently in the download registry."""
    return len(_file_registry)


# ═══════════════════════════════════════════════════════════════════════════════
# Validation — pre-save and post-save checks
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_extension(file: UploadFile, allowed_types: Optional[list[str]] = None) -> str:
    """
    Check that the file's extension is in our whitelist and matches an allowed type.

    Args:
        file: The uploaded file object.
        allowed_types: If provided, only these MIME types are accepted (tool-specific).

    Returns:
        The validated MIME type string.

    Raises:
        HTTPException 400: If extension is missing, unsupported, or not allowed for this tool.
    """
    if allowed_types is None:
        allowed_types = list(ALLOWED_MIME_TYPES.keys())

    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    if not ext:
        raise HTTPException(
            status_code=400,
            detail="File has no extension. Please upload a file with a valid extension.",
        )

    if ext not in EXTENSION_TO_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"File extension '{ext}' is not supported. "
                   f"Allowed: {', '.join(sorted(EXTENSION_TO_MIME.keys()))}",
        )

    mime = EXTENSION_TO_MIME[ext]

    if mime not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{mime}' is not allowed for this conversion tool.",
        )

    return mime


def _validate_content_length(file: UploadFile) -> None:
    """
    Check the Content-Length header as an early rejection signal.
    This is a fast check but NOT authoritative — the actual byte count
    is verified during the streaming save in save_upload_file().
    """
    content_length = file.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {MAX_FILE_SIZE_MB}MB size limit "
                           f"(Content-Length: {int(content_length) // (1024 * 1024)}MB).",
                )
        except ValueError:
            # Malformed Content-Length — skip this check, rely on streaming count
            pass


def _validate_magic_bytes(file_path: Path, expected_mime: str) -> None:
    """
    Read the first bytes of a saved file and verify they match the expected type.
    This catches cases where a user renames an executable to .pdf, for example.

    For ambiguous signatures (PK = zip-based formats, RIFF = container format),
    secondary structural checks are performed.
    """
    expected_bytes = MAGIC_BYTE_SIGNATURES.get(expected_mime)
    if not expected_bytes:
        # No magic byte check defined for this type — skip
        return

    try:
        with open(file_path, "rb") as f:
            header = f.read(12)
    except Exception as e:
        file_path.unlink(missing_ok=True)
        logger.error("Cannot read file for magic byte check: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Cannot read the uploaded file. It may be corrupted.",
        )

    if not header:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Primary check: header starts with expected bytes ──
    if not header.startswith(expected_bytes):
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"File content does not match the '{expected_mime}' format. "
                   f"The file may be corrupted or falsely renamed.",
        )

    # ── Secondary checks for ambiguous signatures ──
    if expected_mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        # PK\x03\x04 is the zip signature shared by .docx, .xlsx, .pptx, .jar, etc.
        # Verify this is specifically a DOCX by checking for word/document.xml inside.
        if not _is_valid_docx(file_path):
            file_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="File is a ZIP archive but not a valid Word document (.docx). "
                       "It may be an .xlsx, .pptx, or other zip-based format.",
            )

    elif expected_mime == "image/webp":
        # RIFF is shared by WAV, AVI, WebP, and other formats.
        # WebP files have "WEBP" at bytes 8–11.
        if len(header) < 12 or header[8:12] != b"WEBP":
            file_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="File has a RIFF header but is not a valid WebP image.",
            )


def _is_valid_docx(file_path: Path) -> bool:
    """Verify a ZIP file is a DOCX by checking for the required internal path."""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            namelist = zf.namelist()
            # A valid DOCX must contain word/document.xml
            return any(name == "word/document.xml" for name in namelist)
    except zipfile.BadZipFile:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Upload Handling — save with full validation
# ═══════════════════════════════════════════════════════════════════════════════

async def save_upload_file(
    file: UploadFile,
    allowed_types: Optional[list[str]] = None,
) -> tuple[Path, str]:
    """
    Save an uploaded file to the temp upload directory with full validation.

    Validation pipeline:
      1. Extension whitelist check
      2. Content-Length header check (fast reject)
      3. Streaming save with real-time byte count (authoritative size check)
      4. Magic byte verification on the saved file

    Args:
        file: The UploadFile from FastAPI's multipart parser.
        allowed_types: Optional list of MIME types to restrict to (tool-specific).

    Returns:
        A tuple of (saved_file_path, validated_mime_type).

    Raises:
        HTTPException: On any validation failure (400, 413) or I/O error (500).
    """
    # Step 1: Extension check
    mime = _validate_extension(file, allowed_types)

    # Step 2: Content-Length check (early rejection, not authoritative)
    _validate_content_length(file)

    # Step 3: Stream to disk with real-time byte counting
    original_ext = Path(file.filename or "upload").suffix.lower()
    safe_filename = f"{uuid.uuid4().hex}{original_ext}"
    save_path = UPLOAD_DIR / safe_filename

    bytes_read = 0
    try:
        with open(save_path, "wb") as dest:
            while True:
                chunk = await file.read(8192)  # 8 KB chunks — good balance for mobile
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > MAX_FILE_SIZE_BYTES:
                    dest.close()
                    save_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {MAX_FILE_SIZE_MB}MB size limit "
                               f"(actual: {bytes_read // (1024 * 1024)}MB).",
                    )
                dest.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        save_path.unlink(missing_ok=True)
        logger.error("Error saving uploaded file '%s': %s", safe_filename, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to save the uploaded file. Please try again.",
        )

    # Step 4: Magic byte verification
    _validate_magic_bytes(save_path, mime)

    logger.info(
        "Saved upload: '%s' → %s (%d bytes, %s)",
        file.filename,
        safe_filename,
        bytes_read,
        mime,
    )
    return save_path, mime


async def save_upload_files(
    files: list[UploadFile],
    allowed_types: Optional[list[str]] = None,
    max_count: Optional[int] = None,
) -> list[tuple[Path, str]]:
    """
    Save multiple uploaded files with per-file validation.

    Args:
        files: List of UploadFile objects.
        allowed_types: Optional MIME type restriction.
        max_count: Maximum number of files allowed. Defaults to config value.

    Returns:
        List of (saved_path, mime_type) tuples.

    Raises:
        HTTPException 400: If no files provided or count exceeds max.
        HTTPException (from save_upload_file): On per-file validation failure.
    """
    from backend.config import MAX_FILES_PER_REQUEST

    limit = max_count or MAX_FILES_PER_REQUEST

    if not files:
        raise HTTPException(
            status_code=400,
            detail="No files provided. Please select at least one file.",
        )

    if len(files) > limit:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum {limit} files per request, got {len(files)}.",
        )

    results = []
    for i, file in enumerate(files):
        result = await save_upload_file(file, allowed_types)
        results.append(result)
        logger.info("Saved file %d/%d: %s", i + 1, len(files), file.filename)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Cleanup — automatic temp file removal
# ═══════════════════════════════════════════════════════════════════════════════

def cleanup_expired_files() -> int:
    """
    Scan temp directories and delete files older than FILE_TTL_SECONDS.
    Also purges orphaned registry entries (file deleted but still tracked).

    Returns:
        Number of files deleted.
    """
    deleted = 0
    now = time.time()

    for directory in (UPLOAD_DIR, OUTPUT_DIR):
        if not directory.exists():
            continue
        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue
            try:
                file_age = now - file_path.stat().st_mtime
                if file_age > FILE_TTL_SECONDS:
                    file_path.unlink()
                    # Also remove from registry if it's an output file
                    _file_registry.pop(file_path.name, None)
                    deleted += 1
                    logger.debug(
                        "Cleaned expired file: %s (age: %.0fs)",
                        file_path.name,
                        file_age,
                    )
            except Exception as e:
                logger.warning("Failed to delete '%s': %s", file_path.name, e)

    # Purge registry entries whose files no longer exist on disk
    orphaned = [
        name
        for name, entry in _file_registry.items()
        if not entry.file_path.exists()
    ]
    for name in orphaned:
        _file_registry.pop(name, None)
        logger.debug("Purged orphaned registry entry: %s", name)

    if deleted or orphaned:
        logger.info(
            "Cleanup complete: %d files deleted, %d registry entries purged",
            deleted,
            len(orphaned),
        )

    return deleted


def cleanup_all_files() -> None:
    """
    Delete ALL files in temp directories and clear the registry.
    Called once on application shutdown to leave no residue.
    """
    total = 0
    for directory in (UPLOAD_DIR, OUTPUT_DIR):
        if not directory.exists():
            continue
        for file_path in directory.iterdir():
            if file_path.is_file():
                try:
                    file_path.unlink()
                    total += 1
                except Exception as e:
                    logger.warning("Shutdown cleanup failed for '%s': %s", file_path.name, e)

    _file_registry.clear()
    if total:
        logger.info("Shutdown cleanup: deleted %d temp files", total)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def format_file_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string (e.g. '2.4 MB')."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
