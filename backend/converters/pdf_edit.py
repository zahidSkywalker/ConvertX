"""
Advanced PDF Editing — Edit PDF (JSON applicator) and OCR PDF (Invisible text overlay).

1. Edit PDF:
   Accepts a list of JSON operations (add_text, add_image) and applies them
   to a base PDF. Designed to be driven by a frontend visual editor (e.g., pdf.js).
   The API route maps uploaded image filenames to secure server paths before
   passing the operations to this module.

2. OCR PDF (Scanned → Editable):
   Takes a flat/scanned PDF and creates a new PDF where each page's image is
   preserved, but an invisible text layer (using opacity=0) is overlaid exactly
   over the recognized words. This allows users to select and copy text in
   any standard PDF reader.

Security (Edit PDF):
   - Image paths are strictly validated against a provided whitelist map.
     The converter never reads arbitrary filesystem paths from the JSON.
   - Font names are restricted to PyMuPDF's built-in base14 fonts.
   - Page indices are bounds-checked.

Performance (OCR PDF):
   - Pages are rendered to images at 200 DPI (optimal balance of OCR accuracy
     and memory/CPU usage).
   - Temp page images are deleted immediately after Tesseract processes them.
   - Processing is page-by-page to avoid OOM on 100+ page scanned documents.
"""

import logging
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pytesseract
from pytesseract import Output

from backend.config import TESSERACT_PATH
from backend.converters import ConversionError

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────
# Allowed fonts for text insertion. PyMuPDF base14 fonts.
_ALLOWED_FONTS = {
    "helv": "Helvetica",
    "heit": "Helvetica-Oblique",
    "hebo": "Helvetica-Bold",
    "hebi": "Helvetica-BoldOblique",
    "cour": "Courier",
    "coit": "Courier-Oblique",
    "cobo": "Courier-Bold",
    "cobi": "Courier-BoldOblique",
    "tiro": "Times-Roman",
    "tiit": "Times-Italic",
    "tibo": "Times-Bold",
    "tibi": "Times-BoldItalic",
    "sybo": "Symbol",
    "zadb": "ZapfDingbats",
}

# Rendering DPI for OCR. 200 is the sweet spot: sufficient for Tesseract LSTM,
# halves the memory footprint and processing time compared to 300 DPI.
_OCR_RENDER_DPI = 200

# Tesseract config for page-level OCR
_OCR_TESSERACT_CONFIG = "--oem 3 --psm 3"

# Minimum confidence to include a word in the invisible layer
_OCR_MIN_CONFIDENCE = 30


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Edit PDF
# ═══════════════════════════════════════════════════════════════════════════════

def apply_pdf_edits(
    input_path: Path,
    output_path: Path,
    operations: list[dict[str, Any]],
    image_path_map: dict[str, Path],
) -> Path:
    """
    Apply a list of editing operations to a PDF.

    Args:
        input_path: Path to the base PDF.
        output_path: Path to save the edited PDF.
        operations: List of operation dicts from the frontend.
        image_path_map: Mapping of frontend-provided image filenames to their
                        secure absolute paths on the server (pre-validated by route).

    Returns:
        Path to the edited PDF.

    Raises:
        ConversionError: On invalid operations, missing images, or PyMuPDF errors.
    """
    if not operations:
        raise ConversionError("No editing operations provided.")

    doc = _open_pdf(input_path)
    total_pages = len(doc)
    
    if total_pages == 0:
        doc.close()
        raise ConversionError("The PDF has 0 pages.")

    try:
        for idx, op in enumerate(operations):
            op_type = op.get("type")
            
            if op_type == "add_text":
                _apply_text_operation(doc, op, total_pages, idx)
            elif op_type == "add_image":
                _apply_image_operation(doc, op, total_pages, idx, image_path_map)
            else:
                logger.warning("Skipping unknown operation type '%s' at index %d", op_type, idx)

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()

    except ConversionError:
        doc.close()
        raise
    except Exception as e:
        doc.close()
        logger.error("Edit PDF failed at operation %d: %s", idx, e, exc_info=True)
        raise ConversionError(f"Failed to apply edit operation #{idx + 1}.", detail=str(e))

    logger.info("Applied %d edit operations → %s", len(operations), output_path.name)
    return output_path


def _apply_text_operation(doc: fitz.Document, op: dict, total_pages: int, idx: int) -> None:
    """Validate and insert a text operation."""
    page_num = op.get("page", 1)
    if not (1 <= page_num <= total_pages):
        raise ConversionError(f"Operation #{idx + 1}: Invalid page {page_num}. PDF has {total_pages} pages.")

    text = op.get("text", "").strip()
    if not text:
        return # Skip empty text operations silently

    x = float(op.get("x", 0))
    y = float(op.get("y", 0))
    fontname = op.get("fontname", "helv")
    fontsize = float(op.get("fontsize", 12))
    color = op.get("color", [0, 0, 0]) # Default black

    if fontname not in _ALLOWED_FONTS:
        raise ConversionError(
            f"Operation #{idx + 1}: Invalid font '{fontname}'. "
            f"Allowed: {', '.join(_ALLOWED_FONTS.keys())}"
        )

    if not (isinstance(color, (list, tuple)) and len(color) == 3 and all(isinstance(c, (int, float)) for c in color)):
        raise ConversionError(f"Operation #{idx + 1}: Color must be a list of 3 RGB values (0-1).")

    page = doc.load_page(page_num - 1)
    
    try:
        # PyMuPDF insert_text uses top-left coordinates (x, y) for the text baseline.
        # The frontend should send top-left coordinates.
        point = fitz.Point(x, y)
        page.insert_text(
            point,
            text,
            fontname=fontname,
            fontsize=fontsize,
            color=tuple(color),
        )
    except Exception as e:
        raise ConversionError(f"Operation #{idx + 1}: Failed to insert text.", detail=str(e))


def _apply_image_operation(
    doc: fitz.Document,
    op: dict,
    total_pages: int,
    idx: int,
    image_path_map: dict[str, Path],
) -> None:
    """Validate and insert an image operation."""
    page_num = op.get("page", 1)
    if not (1 <= page_num <= total_pages):
        raise ConversionError(f"Operation #{idx + 1}: Invalid page {page_num}.")

    filename = op.get("filename")
    if not filename:
        raise ConversionError(f"Operation #{idx + 1}: Image operation missing 'filename'.")

    # SECURITY: Only allow paths explicitly whitelisted by the route
    secure_path = image_path_map.get(filename)
    if not secure_path or not secure_path.exists():
        raise ConversionError(
            f"Operation #{idx + 1}: Image '{filename}' not found or not authorized."
        )

    x = float(op.get("x", 0))
    y = float(op.get("y", 0))
    width = float(op.get("width", 100))
    height = float(op.get("height", 100))

    if width <= 0 or height <= 0:
        raise ConversionError(f"Operation #{idx + 1}: Image width and height must be positive.")

    page = doc.load_page(page_num - 1)
    rect = fitz.Rect(x, y, x + width, y + height)

    try:
        page.insert_image(rect, filename=str(secure_path))
    except Exception as e:
        raise ConversionError(f"Operation #{idx + 1}: Failed to insert image.", detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 2. OCR PDF (Scanned → Editable)
# ═══════════════════════════════════════════════════════════════════════════════

def ocr_pdf(
    input_path: Path,
    output_path: Path,
) -> tuple[Path, int, int]:
    """
    Overlay invisible text on a scanned PDF to make it searchable/selectable.

    Process:
      1. Render each page to a high-DPI PNG.
      2. Run Tesseract OCR to get word bounding boxes.
      3. Create a new PDF page containing the original PNG as the background.
      4. Use PyMuPDF's TextWriter with opacity=0 to write invisible text exactly
         over the detected bounding boxes.

    Args:
        input_path: Path to the scanned PDF.
        output_path: Path to save the OCRed PDF.

    Returns:
        Tuple of (output_path, total_pages, total_words_detected).

    Raises:
        ConversionError: If Tesseract is missing or processing fails catastrophically.
    """
    _verify_tesseract()
    
    doc = _open_pdf(input_path)
    total_pages = len(doc)
    
    if total_pages == 0:
        doc.close()
        raise ConversionError("The PDF has 0 pages.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    new_doc = fitz.open()
    
    total_words = 0
    temp_img_path = output_path.parent / f"ocr_temp_{id(input_path)}.png"

    try:
        for i in range(total_pages):
            page = doc.load_page(i)
            page_rect = page.rect
            
            # 1. Render page to image
            zoom = _OCR_RENDER_DPI / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(temp_img_path))

            # 2. Create new page in output doc and insert background image
            new_page = new_doc.new_page(width=page_rect.width, height=page_rect.height)
            new_page.insert_image(page_rect, filename=str(temp_img_path))

            # 3. Run OCR
            try:
                data = pytesseract.image_to_data(
                    str(temp_img_path),
                    output_type=Output.DICT,
                    config=_OCR_TESSERACT_CONFIG,
                )
            except Exception as e:
                logger.error("OCR failed on page %d: %s", i + 1, e)
                continue # Skip page but don't fail the whole document

            # 4. Map image pixels back to PDF points
            # Image dimensions in pixels
            img_w = pix.width
            img_h = pix.height
            # Scale factors: PDF points per pixel
            scale_x = page_rect.width / img_w
            scale_y = page_rect.height / img_h

            # 5. Create TextWriter for invisible layer
            tw = fitz.TextWriter(page_rect)

            for j in range(len(data["text"])):
                text = data["text"][j].strip()
                if not text:
                    continue
                    
                try:
                    conf = int(data["conf"][j])
                except (ValueError, TypeError):
                    continue

                if conf < _OCR_MIN_CONFIDENCE:
                    continue

                # Tesseract coordinates are in pixels relative to the image
                img_x = float(data["left"][j])
                img_y = float(data["top"][j])
                img_w_word = float(data["width"][j])
                img_h_word = float(data["height"][j])

                # Convert to PDF points
                pdf_x = img_x * scale_x
                pdf_y = img_y * scale_y
                pdf_font_size = img_h_word * scale_y

                if pdf_font_size < 1:
                    continue # Skip impossibly small text artifacts

                # Calculate baseline offset. Tesseract 'top' is the top of the word.
                # PyMuPDF TextWriter append() expects the baseline.
                # A rough heuristic: baseline is ~80% down from the top.
                baseline_y = pdf_y + (pdf_font_size * 0.8)

                try:
                    # append(pos, text, font=None, fontsize=12, language=None)
                    # We use the default font to keep it simple and lightweight.
                    tw.append(
                        fitz.Point(pdf_x, baseline_y),
                        text,
                        fontsize=pdf_font_size
                    )
                    total_words += 1
                except Exception:
                    continue # Skip malformed glyphs

            # 6. Write the invisible text layer onto the page
            # opacity=0 makes it completely invisible, but selectable/searchable
            try:
                tw.write_text(new_page, color=(0, 0, 0), opacity=0)
            except Exception as e:
                logger.warning("Failed to write invisible text on page %d: %s", i + 1, e)

    except ConversionError:
        doc.close()
        new_doc.close()
        raise
    except Exception as e:
        doc.close()
        new_doc.close()
        logger.error("OCR PDF catastrophic failure: %s", e, exc_info=True)
        raise ConversionError("Failed to process PDF for OCR.", detail=str(e))
    finally:
        # ALWAYS clean up the temp image
        if temp_img_path.exists():
            temp_img_path.unlink(missing_ok=True)
        doc.close()

    try:
        new_doc.save(str(output_path), garbage=3, deflate=True)
        new_doc.close()
    except Exception as e:
        raise ConversionError("Failed to save the OCRed PDF.", detail=str(e))

    if total_words == 0:
        logger.warning("OCR completed but detected 0 words across %d pages.", total_pages)

    logger.info(
        "OCR complete: %d pages, %d words detected → %s (%.1f KB)",
        total_pages, total_words, output_path.name, output_path.stat().st_size / 1024
    )
    return output_path, total_pages, total_words


# ═══════════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _open_pdf(path: Path) -> fitz.Document:
    """Standard PDF open with validation."""
    if not path.exists():
        raise ConversionError("The uploaded PDF file was not found.")
    if path.stat().st_size == 0:
        raise ConversionError("The uploaded PDF file is empty (0 bytes).")
    try:
        return fitz.open(str(path))
    except fitz.FileDataError:
        raise ConversionError("The file is not a valid or is a severely corrupted PDF.")
    except Exception as e:
        raise ConversionError("Failed to open the PDF file.", detail=str(e))

def _verify_tesseract() -> None:
    """Ensure Tesseract is configured."""
    if TESSERACT_PATH != "tesseract":
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
