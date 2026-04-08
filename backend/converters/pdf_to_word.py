"""
PDF to Word converter — wraps the pdf2docx library.

pdf2docx parses PDF layout elements (paragraphs, tables, images, headers/footers)
and reconstructs them as a .docx file with reasonable formatting preservation.

Limitations:
  - Scanned/image-only PDFs produce an empty or near-empty DOCX.
  - Encrypted/DRM-protected PDFs will fail.
  - Very complex layouts (nested tables, multi-column flowing text) may not
    reconstruct perfectly.
  - PDFs with non-embedded fonts will use fallback fonts in the DOCX.
"""

import logging
import time
from pathlib import Path

from backend.converters import ConversionError

logger = logging.getLogger(__name__)

# ─── Import guard — allows app to start even if pdf2docx is missing ────────
try:
    from pdf2docx import Converter
    _HAS_PDF2DOCX = True
except ImportError:
    _HAS_PDF2DOCX = False
    Converter = None


def convert_pdf_to_word(input_path: Path, output_path: Path) -> Path:
    """
    Convert a PDF file to a Word (.docx) file.

    The output DOCX preserves text content, basic formatting (bold, italic,
    font size), table structures, and image placements where possible.

    Args:
        input_path: Path to the source PDF file.
        output_path: Path where the output .docx file will be written.
                     The parent directory must exist.

    Returns:
        Path to the created .docx file.

    Raises:
        ConversionError: If pdf2docx is not installed, the PDF is invalid,
                         encrypted, or conversion fails for any reason.
    """
    if not _HAS_PDF2DOCX:
        raise ConversionError(
            message="PDF to Word conversion is not available on this server.",
            detail="The pdf2docx library is not installed.",
        )

    # ── Validate inputs ──
    if not input_path.exists():
        raise ConversionError(
            message="The uploaded PDF file was not found.",
            detail=f"Expected file at: {input_path}",
        )

    if input_path.stat().st_size == 0:
        raise ConversionError(
            message="The uploaded PDF file is empty (0 bytes).",
        )

    if input_path.suffix.lower() != ".pdf":
        raise ConversionError(
            message="Invalid file type. Expected a PDF file.",
            detail=f"Got extension: {input_path.suffix}",
        )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting PDF→DOCX: %s (%.1f KB)",
        input_path.name,
        input_path.stat().st_size / 1024,
    )

    start_time = time.time()

    try:
        # pdf2docx Converter context manager handles resource cleanup
        with Converter(str(input_path)) as cv:
            cv.convert(str(output_path))

    except ValueError as e:
        # pdf2docx raises ValueError for encrypted files, invalid PDFs, etc.
        error_msg = str(e).lower()
        if "encrypted" in error_msg or "password" in error_msg:
            raise ConversionError(
                message="This PDF is encrypted or password-protected. "
                        "Please remove the password and try again.",
                detail=str(e),
            )
        if "not a pdf" in error_msg or "invalid" in error_msg:
            raise ConversionError(
                message="The uploaded file is not a valid PDF.",
                detail=str(e),
            )
        raise ConversionError(
            message="Failed to read the PDF file. It may be corrupted.",
            detail=str(e),
        )

    except RuntimeError as e:
        # pdf2docx raises RuntimeError for parsing failures
        error_msg = str(e).lower()
        if "page" in error_msg and "empty" in error_msg:
            raise ConversionError(
                message="This PDF appears to contain only images (scanned document). "
                        "OCR is not available for PDF→Word conversion. "
                        "Try using Image→Excel for OCR-based extraction.",
                detail=str(e),
            )
        raise ConversionError(
            message="Failed to convert the PDF. The document structure may be too complex.",
            detail=str(e),
        )

    except Exception as e:
        logger.error("Unexpected error in pdf2docx: %s", e, exc_info=True)
        raise ConversionError(
            message="An unexpected error occurred during PDF to Word conversion.",
            detail=f"{type(e).__name__}: {e}",
        )

    # ── Verify output ──
    if not output_path.exists():
        raise ConversionError(
            message="Conversion completed but the output file was not created. "
                    "The PDF may be empty or corrupted.",
        )

    if output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        raise ConversionError(
            message="The converted Word file is empty. The source PDF may contain "
                    "only images (scanned document) with no extractable text.",
        )

    elapsed = time.time() - start_time
    logger.info(
        "PDF→DOCX complete: %s → %s (%.1f KB, %.1fs)",
        input_path.name,
        output_path.name,
        output_path.stat().st_size / 1024,
        elapsed,
    )

    return output_path
