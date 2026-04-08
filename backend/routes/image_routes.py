"""
Image conversion routes — Image to PDF and Image to Excel.

Image to PDF accepts multiple files (up to 20), stitched into one PDF.
Image to Excel accepts a single image and extracts tabular data via OCR.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Form

from backend.config import (
    TOOL_INPUT_TYPES,
    OUTPUT_DIR,
    MAX_FILES_PER_REQUEST,
)
from backend.utils.file_utils import (
    save_upload_file,
    save_upload_files,
    register_output_file,
    format_file_size,
)
from backend.utils.response_models import (
    ImageToPdfResponse,
    ImageToExcelResponse,
)
from backend.converters import ConversionError
from backend.converters.image_to_pdf import convert_images_to_pdf
from backend.converters.image_to_excel import convert_image_to_excel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["image"])


# ═══════════════════════════════════════════════════════════════════════════════
# Image(s) → PDF
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/image-to-pdf",
    response_model=ImageToPdfResponse,
    summary="Convert images to a single PDF",
    description=(
        "Upload multiple images (JPEG, PNG, WebP) and receive a single PDF "
        "with one image per page. Pages are A4-sized with automatic orientation "
        f"per image. Maximum {MAX_FILES_PER_REQUEST} images per request."
    ),
    responses={
        400: {"description": "No files, too many files, or invalid file type"},
        413: {"description": "One or more files exceed size limit"},
        422: {"description": "Conversion failed (corrupted image, etc.)"},
    },
)
async def image_to_pdf(
    files: list[UploadFile] = File(
        ...,
        description="Image files to convert (.jpg, .png, .webp)",
    ),
):
    """
    Convert multiple images into a single multi-page PDF.

    Each image is placed on its own A4 page with automatic portrait/landscape
    orientation. Images are scaled to fit within margins while preserving
    aspect ratio.

    Accepts JPEG, PNG, and WebP files up to 10MB each, maximum 20 files.
    Returns a download URL for the PDF, valid for 10 minutes.
    """
    # ── Validate and save all uploads ──
    upload_paths: list[Path] = []
    output_path = None

    try:
        saved_files = await save_upload_files(
            files,
            allowed_types=TOOL_INPUT_TYPES["image-to-pdf"],
        )
        upload_paths = [path for path, _ in saved_files]

        if not upload_paths:
            raise HTTPException(
                status_code=400,
                detail="No valid image files were uploaded.",
            )

        # ── Determine output path ──
        output_name = "images_combined.pdf"
        output_path = OUTPUT_DIR / output_name

        # ── Convert ──
        logger.info(
            "Image→PDF: converting %d image(s)",
            len(upload_paths),
        )
        output_path, page_count = convert_images_to_pdf(
            upload_paths, output_path
        )

        # ── Register for download ──
        download_name = register_output_file(output_name, output_path)

        # ── Clean up uploads ──
        for path in upload_paths:
            _safe_delete(path)

        # ── Return response ──
        return ImageToPdfResponse(
            download_url=f"/api/download/{download_name}",
            filename=output_name,
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
            page_count=page_count,
        )

    except ConversionError as e:
        for path in upload_paths:
            _safe_delete(path)
        _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)

    except HTTPException:
        for path in upload_paths:
            _safe_delete(path)
        _safe_delete(output_path)
        raise

    except Exception as e:
        logger.error("Unexpected error in Image→PDF route: %s", e, exc_info=True)
        for path in upload_paths:
            _safe_delete(path)
        _safe_delete(output_path)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during conversion. Please try again.",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Image → Excel (OCR)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/image-to-excel",
    response_model=ImageToExcelResponse,
    summary="Extract table data from image using OCR",
    description=(
        "Upload an image containing a table (screenshot, scan, photo) and "
        "receive an Excel file with the extracted data. Works best with "
        "clear, high-contrast images of printed tables. Handwritten text "
        "and rotated images are not well supported."
    ),
    responses={
        400: {"description": "Invalid file type or empty file"},
        413: {"description": "File exceeds size limit"},
        422: {"description": "No text detected or table structure not found"},
        503: {"description": "Tesseract OCR not installed on this server"},
    },
)
async def image_to_excel(
    file: UploadFile = File(
        ...,
        description="Image containing a table (.jpg, .png, .webp)",
    ),
):
    """
    Extract tabular data from an image using OCR and output to Excel.

    The image is preprocessed (grayscale, contrast boost, resize) then
    analyzed by Tesseract OCR. Detected words are grouped into rows and
    columns based on their bounding box positions.

    Accepts JPEG, PNG, and WebP files up to 10MB.
    Returns a download URL for the .xlsx file, valid for 10 minutes.
    """
    # ── Tool availability check ──
    from backend.main import TESSERACT_AVAILABLE
    if not TESSERACT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Image to Excel conversion is currently unavailable. "
                    "Tesseract OCR is not installed on this server.",
        )

    # ── Validate and save upload ──
    upload_path = None
    output_path = None

    try:
        upload_path, _ = await save_upload_file(
            file,
            allowed_types=TOOL_INPUT_TYPES["image-to-excel"],
        )

        # ── Determine output path ──
        output_name = upload_path.stem + ".xlsx"
        output_path = OUTPUT_DIR / output_name

        # ── Convert ──
        logger.info("Image→Excel: extracting table from '%s'", file.filename)
        output_path, rows_extracted = convert_image_to_excel(
            upload_path, output_path
        )

        # ── Register for download ──
        download_name = register_output_file(output_name, output_path)

        # ── Clean up upload ──
        _safe_delete(upload_path)

        # ── Return response ──
        return ImageToExcelResponse(
            download_url=f"/api/download/{download_name}",
            filename=output_name,
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
            rows_extracted=rows_extracted,
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
        logger.error(
            "Unexpected error in Image→Excel route: %s", e, exc_info=True
        )
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
