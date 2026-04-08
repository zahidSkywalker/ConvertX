"""
PDF conversion routes — PDF to Word and Word to PDF.

Each route follows the same pipeline:
  1. Check tool availability (fail fast with 503 if tool is missing).
  2. Validate and save the uploaded file via file_utils (413/400 on invalid input).
  3. Call the converter module (422 on conversion failure).
  4. Register the output file for download.
  5. Delete the upload (no longer needed).
  6. Return the typed success response.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.config import (
    TOOL_INPUT_TYPES,
    OUTPUT_DIR,
)
from backend.utils.file_utils import (
    save_upload_file,
    register_output_file,
    format_file_size,
)
from backend.utils.response_models import ConversionResponse
from backend.converters import ConversionError
from backend.converters.pdf_to_word import convert_pdf_to_word, _HAS_PDF2DOCX
from backend.converters.word_to_pdf import convert_word_to_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["pdf"])


# ═══════════════════════════════════════════════════════════════════════════════
# PDF → Word
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/pdf-to-word",
    response_model=ConversionResponse,
    summary="Convert PDF to Word document",
    description=(
        "Upload a PDF file and receive a .docx Word document. "
        "Text, tables, and images are preserved where possible. "
        "Encrypted or scanned-only PDFs are not supported."
    ),
    responses={
        400: {"description": "Invalid file type or empty file"},
        413: {"description": "File exceeds size limit"},
        422: {"description": "Conversion failed (encrypted, corrupted, etc.)"},
        503: {"description": "Conversion tool not available on this server"},
    },
)
async def pdf_to_word(
    file: UploadFile = File(..., description="PDF file to convert (.pdf)"),
):
    """
    Convert a PDF file to a Word (.docx) document.

    Accepts a single PDF file up to 10MB. Returns a download URL
    for the converted .docx file, valid for 10 minutes.
    """
    # ── Tool availability check ──
    if not _HAS_PDF2DOCX:
        raise HTTPException(
            status_code=503,
            detail="PDF to Word conversion is currently unavailable. "
                    "The conversion library is not installed on this server.",
        )

    # ── Validate and save upload ──
    upload_path = None
    output_path = None

    try:
        upload_path, _ = await save_upload_file(
            file,
            allowed_types=TOOL_INPUT_TYPES["pdf-to-word"],
        )

        # ── Determine output path ──
        output_name = upload_path.stem + ".docx"
        output_path = OUTPUT_DIR / output_name

        # ── Convert ──
        logger.info("PDF→DOCX: converting '%s'", file.filename)
        convert_pdf_to_word(upload_path, output_path)

        # ── Register for download ──
        download_name = register_output_file(output_name, output_path)

        # ── Clean up upload ──
        _safe_delete(upload_path)

        # ── Return response ──
        return ConversionResponse(
            download_url=f"/api/download/{download_name}",
            filename=output_name,
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )

    except ConversionError as e:
        _safe_delete(upload_path)
        _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)

    except HTTPException:
        _safe_delete(upload_path)
        _safe_delete(output_path)
        raise

    except Exception as e:
        logger.error("Unexpected error in PDF→Word route: %s", e, exc_info=True)
        _safe_delete(upload_path)
        _safe_delete(output_path)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during conversion. Please try again.",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Word → PDF
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/word-to-pdf",
    response_model=ConversionResponse,
    summary="Convert Word document to PDF",
    description=(
        "Upload a .docx Word document and receive a PDF file. "
        "Formatting, tables, images, and page layout are preserved "
        "using LibreOffice headless conversion."
    ),
    responses={
        400: {"description": "Invalid file type or empty file"},
        413: {"description": "File exceeds size limit"},
        422: {"description": "Conversion failed (corrupted, unsupported content, etc.)"},
        503: {"description": "LibreOffice not installed on this server"},
    },
)
async def word_to_pdf(
    file: UploadFile = File(..., description="Word document to convert (.docx)"),
):
    """
    Convert a Word (.docx) document to PDF.

    Accepts a single .docx file up to 10MB. Returns a download URL
    for the converted PDF, valid for 10 minutes.

    Note: This endpoint uses LibreOffice and may take 10-60 seconds
    depending on document complexity.
    """
    # ── Tool availability check ──
    from backend.main import LIBREOFFICE_AVAILABLE
    if not LIBREOFFICE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Word to PDF conversion is currently unavailable. "
                    "LibreOffice is not installed on this server.",
        )

    # ── Validate and save upload ──
    upload_path = None
    output_path = None

    try:
        upload_path, _ = await save_upload_file(
            file,
            allowed_types=TOOL_INPUT_TYPES["word-to-pdf"],
        )

        # ── Convert ──
        # word_to_pdf returns the actual output path (LibreOffice chooses the filename)
        logger.info("DOCX→PDF: converting '%s'", file.filename)
        output_path = convert_word_to_pdf(upload_path, OUTPUT_DIR)

        # ── Register for download ──
        output_name = output_path.name
        download_name = register_output_file(output_name, output_path)

        # ── Clean up upload ──
        _safe_delete(upload_path)

        # ── Return response ──
        return ConversionResponse(
            download_url=f"/api/download/{download_name}",
            filename=output_name,
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )

    except ConversionError as e:
        _safe_delete(upload_path)
        _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)

    except HTTPException:
        _safe_delete(upload_path)
        _safe_delete(output_path)
        raise

    except Exception as e:
        logger.error("Unexpected error in Word→PDF route: %s", e, exc_info=True)
        _safe_delete(upload_path)
        _safe_delete(output_path)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during conversion. Please try again.",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Shared Utility
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_delete(path: Path | None) -> None:
    """Delete a file if it exists. Logs warnings on failure but never raises."""
    if path is None:
        return
    try:
        if path.exists():
            path.unlink()
            logger.debug("Cleaned up: %s", path.name)
    except Exception as e:
        logger.warning("Failed to delete '%s': %s", path.name, e)
