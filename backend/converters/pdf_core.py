"""
PDF Core Manipulation — 9 tools powered by PyMuPDF (fitz).

Handles structural and visual operations on PDF files without relying
on external CLI tools (no Ghostscript, no Poppler).

Tools included:
  1. Merge PDFs
  2. Split PDF
  3. Rotate PDF
  4. Compress PDF (Lossless optimization + metadata stripping)
  5. Watermark PDF (Diagonal text stamp via SVG injection)
  6. Add Page Numbers
  7. Page Organizer (Reorder pages)
  8. Repair PDF (Structural rebuild, xref fix)
  9. PDF to Image (Render pages to PNG, zipped)

Security:
  - All text injected into PDFs (watermarks, page numbers) is XML-escaped
    to prevent XML/SVG injection attacks.
  - Page numbers are strictly bounds-checked against the document length.
"""

import io
import logging
import math
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import fitz  # PyMuPDF

from backend.converters import ConversionError

logger = logging.getLogger(__name__)

# ─── Rendering Constants ────────────────────────────────────────────────────
# DPI for PDF to Image conversion. 150 is the sweet spot for mobile:
# clear enough to read, small enough to keep ZIP size manageable.
_PDF_TO_IMAGE_DPI = 150

# ─── Compression Constants ──────────────────────────────────────────────────
# PyMuPDF save options for maximum lossless compression.
_COMPRESS_SAVE_OPTIONS = {
    "garbage": 4,      # Aggressively remove unused objects
    "deflate": True,   # Compress streams
    "clean": True,     # Clean up redundant data structures
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Merge PDFs
# ═══════════════════════════════════════════════════════════════════════════════

def merge_pdfs(
    pdf_paths: list[Path],
    output_path: Path,
) -> Path:
    """
    Merge multiple PDF files into a single document.

    Maintains the exact order of the input list. Handles varying page sizes
    (e.g., mixing A4 and Letter) correctly — each page retains its original size.

    Args:
        pdf_paths: Ordered list of PDF file paths to merge.
        output_path: Destination path for the merged PDF.

    Returns:
        Path to the merged PDF file.

    Raises:
        ConversionError: If no files provided, any file is invalid, or merge fails.
    """
    if not pdf_paths:
        raise ConversionError("No PDF files provided for merging.")

    if len(pdf_paths) == 1:
        # Single file — copy it to output location
        try:
            import shutil
            shutil.copy2(pdf_paths[0], output_path)
            return output_path
        except Exception as e:
            raise ConversionError("Failed to process the PDF file.", detail=str(e))

    logger.info("Merging %d PDF files", len(pdf_paths))

    try:
        merged_doc = fitz.open()

        for i, path in enumerate(pdf_paths):
            if not path.exists():
                merged_doc.close()
                raise ConversionError(
                    f"PDF file #{i + 1} ('{path.name}') was not found.",
                )

            try:
                source_doc = fitz.open(str(path))
                merged_doc.insert_pdf(source_doc)
                source_doc.close()
                logger.debug("Merged file %d/%d: %s (%d pages)", i + 1, len(pdf_paths), path.name, len(source_doc))
            except Exception as e:
                merged_doc.close()
                raise ConversionError(
                    f"Failed to read PDF file #{i + 1} ('{path.name}'). It may be corrupted.",
                    detail=str(e),
                )

        merged_doc.save(str(output_path), garbage=3, deflate=True)
        merged_doc.close()

    except ConversionError:
        raise
    except Exception as e:
        logger.error("Merge failed: %s", e, exc_info=True)
        raise ConversionError("An unexpected error occurred while merging PDFs.", detail=str(e))

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ConversionError("Merge completed but the output file is empty.")

    logger.info("Merge complete: %d files → %s (%.1f KB)", len(pdf_paths), output_path.name, output_path.stat().st_size / 1024)
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Split PDF
# ═══════════════════════════════════════════════════════════════════════════════

def split_pdf(
    input_path: Path,
    output_dir: Path,
) -> tuple[Path, int]:
    """
    Split a PDF into individual pages, packaged as a ZIP file.

    Each page becomes a separate PDF named `page_1.pdf`, `page_2.pdf`, etc.

    Args:
        input_path: Path to the source PDF.
        output_dir: Directory to write temporary split files to.

    Returns:
        Tuple of (zip_file_path, total_page_count).

    Raises:
        ConversionError: If PDF cannot be opened or split fails.
    """
    doc = _open_pdf(input_path)
    page_count = len(doc)
    
    if page_count == 0:
        doc.close()
        raise ConversionError("The PDF has 0 pages. Nothing to split.")
        
    if page_count == 1:
        doc.close()
        raise ConversionError("The PDF has only 1 page. Nothing to split.")

    logger.info("Splitting PDF: %d pages", page_count)

    split_files = []
    try:
        for i in range(page_count):
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=i, to_page=i)
            
            page_filename = f"page_{i + 1}.pdf"
            page_path = output_dir / page_filename
            new_doc.save(str(page_path), garbage=3, deflate=True)
            new_doc.close()
            split_files.append((page_filename, page_path))

        doc.close()

        # Package into ZIP
        zip_path = output_dir / f"{input_path.stem}_split_pages.zip"
        _create_zip(split_files, zip_path)

        # Clean up individual page PDFs
        for _, path in split_files:
            _safe_delete(path)

    except ConversionError:
        doc.close()
        raise
    except Exception as e:
        doc.close()
        logger.error("Split failed: %s", e, exc_info=True)
        raise ConversionError("Failed to split the PDF.", detail=str(e))

    logger.info("Split complete: %d pages → %s", page_count, zip_path.name)
    return zip_path, page_count


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Rotate PDF
# ═══════════════════════════════════════════════════════════════════════════════

def rotate_pdf(
    input_path: Path,
    output_path: Path,
    degrees: int,
    page_numbers: list[int] | None = None,
) -> Path:
    """
    Rotate pages in a PDF.

    Args:
        input_path: Path to the source PDF.
        output_path: Destination path for the rotated PDF.
        degrees: Rotation angle (must be 90, 180, or 270).
        page_numbers: Optional list of 1-based page numbers to rotate.
                      If None, all pages are rotated.

    Raises:
        ConversionError: If degrees invalid or pages out of range.
    """
    if degrees not in (90, 180, 270, -90, -270):
        raise ConversionError("Rotation must be 90, 180, or 270 degrees.")

    doc = _open_pdf(input_path)
    total_pages = len(doc)

    if page_numbers:
        invalid = [p for p in page_numbers if p < 1 or p > total_pages]
        if invalid:
            doc.close()
            raise ConversionError(
                f"Page numbers out of range: {invalid}. PDF has {total_pages} pages."
            )

    try:
        pages_to_rotate = page_numbers if page_numbers else range(1, total_pages + 1)
        
        for p in pages_to_rotate:
            page = doc.load_page(p - 1)  # 0-based index
            current_rotation = page.rotation
            page.set_rotation(current_rotation + degrees)

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()

    except ConversionError:
        doc.close()
        raise
    except Exception as e:
        doc.close()
        logger.error("Rotate failed: %s", e, exc_info=True)
        raise ConversionError("Failed to rotate the PDF.", detail=str(e))

    logger.info("Rotated %s by %d°", "all pages" if not page_numbers else f"pages {page_numbers}", degrees)
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Compress PDF
# ═══════════════════════════════════════════════════════════════════════════════

def compress_pdf(
    input_path: Path,
    output_path: Path,
) -> tuple[Path, dict]:
    """
    Compress a PDF using lossless optimization.

    Steps performed:
      1. Strip metadata (author, creator, timestamps, etc.)
      2. Remove duplicate objects
      3. Deflate all uncompressed streams
      4. Remove unused data structures

    Note: This is lossless — it does NOT reduce image DPI or degrade quality.
    It typically reduces file size by 20-60% depending on the original PDF.

    Args:
        input_path: Path to the source PDF.
        output_path: Destination path for compressed PDF.

    Returns:
        Tuple of (output_path, stats_dict with original_size and compressed_size).

    Raises:
        ConversionError: If compression fails.
    """
    original_size = input_path.stat().st_size
    
    doc = _open_pdf(input_path)
    
    try:
        # Strip metadata
        doc.set_metadata({}) 

        # Save with aggressive garbage collection
        doc.save(
            str(output_path),
            garbage=4,
            deflate=True,
            clean=True,
            no_new_id=True, # Prevents adding new creation timestamps
        )
        doc.close()

    except Exception as e:
        doc.close()
        logger.error("Compress failed: %s", e, exc_info=True)
        raise ConversionError("Failed to compress the PDF.", detail=str(e))

    compressed_size = output_path.stat().st_size
    
    if compressed_size >= original_size:
        # If compression made it bigger (rare, but happens on tiny/already-optimized PDFs),
        # just copy the original.
        output_path.unlink()
        import shutil
        shutil.copy2(input_path, output_path)
        compressed_size = original_size
        logger.info("Compression yielded no improvement, using original file.")

    stats = {
        "original_size": original_size,
        "compressed_size": compressed_size,
        "reduction_percent": round((1 - compressed_size / original_size) * 100, 1)
    }

    logger.info("Compressed: %.1f KB → %.1f KB (%.1f%% reduction)", 
                original_size/1024, compressed_size/1024, stats["reduction_percent"])
    
    return output_path, stats


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Watermark PDF
# ═══════════════════════════════════════════════════════════════════════════════

def watermark_pdf(
    input_path: Path,
    output_path: Path,
    watermark_text: str,
    opacity: float = 0.3,
    angle: int = 45,
) -> Path:
    """
    Add a diagonal text watermark to all pages of a PDF.

    Uses SVG injection for perfect resolution-independent rendering at any angle.
    Text is XML-escaped to prevent injection attacks.

    Args:
        input_path: Path to the source PDF.
        output_path: Destination path for watermarked PDF.
        watermark_text: The text to stamp (e.g., "CONFIDENTIAL").
        opacity: Transparency level (0.0 to 1.0).
        angle: Rotation angle in degrees.

    Raises:
        ConversionError: If text empty or rendering fails.
    """
    if not watermark_text or not watermark_text.strip():
        raise ConversionError("Watermark text cannot be empty.")

    opacity = max(0.05, min(1.0, opacity)) # Clamp between 5% and 100%
    safe_text = xml_escape(watermark_text.strip())

    doc = _open_pdf(input_path)
    
    try:
        for page in doc:
            rect = page.rect
            
            # Calculate responsive font size based on page width
            font_size = max(20, int(rect.width / 8))
            
            cx, cy = rect.width / 2, rect.height / 2
            
            svg = f'''
            <svg width="{rect.width}" height="{rect.height}">
                <text 
                    x="{cx}" y="{cy}" 
                    transform="rotate({angle} {cx} {cy})"
                    font-family="Helvetica, sans-serif" 
                    font-size="{font_size}" 
                    font-weight="bold"
                    fill="gray" 
                    fill-opacity="{opacity}"
                    text-anchor="middle" 
                    dominant-baseline="middle"
                >
                    {safe_text}
                </text>
            </svg>'''.strip()

            page.insert_svg(svg)
            
        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()

    except ConversionError:
        doc.close()
        raise
    except Exception as e:
        doc.close()
        logger.error("Watermark failed: %s", e, exc_info=True)
        raise ConversionError("Failed to apply watermark.", detail=str(e))

    logger.info("Watermark applied: '%s' (%.0f°, %.0f%% opacity)", watermark_text, angle, opacity * 100)
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Add Page Numbers
# ═══════════════════════════════════════════════════════════════════════════════

def add_page_numbers(
    input_path: Path,
    output_path: Path,
    position: str = "bottom-center",
) -> Path:
    """
    Add page numbers (e.g., "Page 1 of 10") to a PDF.

    Args:
        input_path: Path to the source PDF.
        output_path: Destination path.
        position: One of 'bottom-center', 'bottom-left', 'bottom-right',
                  'top-center', 'top-left', 'top-right'.

    Raises:
        ConversionError: If invalid position or rendering fails.
    """
    valid_positions = ("bottom-center", "bottom-left", "bottom-right", 
                       "top-center", "top-left", "top-right")
    if position not in valid_positions:
        raise ConversionError(f"Invalid position. Must be one of: {', '.join(valid_positions)}")

    doc = _open_pdf(input_path)
    total_pages = len(doc)
    
    try:
        for i in range(total_pages):
            page = doc.load_page(i)
            rect = page.rect
            text = f"Page {i + 1} of {total_pages}"
            
            # Determine coordinates (fitz Point uses bottom-left origin for text insertion)
            font_size = 10
            margin = 40
            
            x, y = 0, 0
            if "bottom" in position:
                y = rect.height - margin
            else:
                y = margin
                
            if "left" in position:
                x = margin
            elif "right" in position:
                x = rect.width - margin - len(text) * (font_size * 0.5) # Approx text width
            else:
                x = (rect.width - len(text) * (font_size * 0.5)) / 2

            # Use insert_textbox for automatic text fitting
            text_rect = fitz.Rect(x, y - font_size, x + 300, y + font_size)
            page.insert_textbox(
                text_rect,
                text,
                fontsize=font_size,
                fontname="helv",
                color=(0.3, 0.3, 0.3), # Dark gray
                align=0 if "left" in position else (1 if "right" in position else 1), # center approximation
            )

        doc.save(str(output_path), garbage=3, deflate=True)
        doc.close()

    except ConversionError:
        doc.close()
        raise
    except Exception as e:
        doc.close()
        logger.error("Page numbering failed: %s", e, exc_info=True)
        raise ConversionError("Failed to add page numbers.", detail=str(e))

    logger.info("Added page numbers to %d pages (position: %s)", total_pages, position)
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Page Organizer
# ═══════════════════════════════════════════════════════════════════════════════

def organize_pages(
    input_path: Path,
    output_path: Path,
    new_order: list[int],
) -> Path:
    """
    Reorder, delete, or duplicate pages in a PDF.

    Args:
        input_path: Path to the source PDF.
        output_path: Destination path.
        new_order: List of 1-based page indices defining the new sequence.
                   Example: [3, 1, 1, 4] creates a 4-page PDF where page 1
                   is the original page 3, page 2 is original page 1, etc.

    Raises:
        ConversionError: If order is empty or contains out-of-range indices.
    """
    doc = _open_pdf(input_path)
    total_pages = len(doc)

    if not new_order:
        doc.close()
        raise ConversionError("Page order list cannot be empty.")

    invalid = [p for p in new_order if p < 1 or p > total_pages]
    if invalid:
        doc.close()
        raise ConversionError(
            f"Page numbers out of range: {invalid}. PDF has {total_pages} pages."
        )

    try:
        new_doc = fitz.open()
        
        for p in new_order:
            new_doc.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
            
        new_doc.save(str(output_path), garbage=3, deflate=True)
        new_doc.close()
        doc.close()

    except ConversionError:
        doc.close()
        raise
    except Exception as e:
        doc.close()
        logger.error("Organize failed: %s", e, exc_info=True)
        raise ConversionError("Failed to reorganize pages.", detail=str(e))

    logger.info("Reorganized %d pages → %d pages", total_pages, len(new_order))
    return output_path


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Repair PDF
# ═══════════════════════════════════════════════════════════════════════════════

def repair_pdf(
    input_path: Path,
    output_path: Path,
) -> tuple[Path, dict]:
    """
    Attempt to repair a corrupted PDF.

    Strategy: PyMuPDF automatically attempts recovery on open. We then rebuild
    the PDF structure from scratch by creating a new document and copying all
    recoverable pages over. This fixes broken xref tables, missing page trees,
    and removes orphaned objects.

    Args:
        input_path: Path to the potentially corrupted PDF.
        output_path: Destination path for the repaired PDF.

    Returns:
        Tuple of (output_path, stats_dict with pages_recovered).

    Raises:
        ConversionError: If PyMuPDF cannot recover any data.
    """
    logger.info("Attempting PDF repair for: %s", input_path.name)
    
    try:
        # Open with recovery enabled
        doc = fitz.open(str(input_path))
    except Exception as e:
        raise ConversionError(
            "This file is too corrupted to repair. No readable data could be extracted.",
            detail=str(e),
        )

    if len(doc) == 0:
        doc.close()
        raise ConversionError(
            "Repair failed. The file structure is broken and no pages could be recovered."
        )

    try:
        recovered_count = len(doc)
        
        # Rebuild completely from scratch
        new_doc = fitz.open()
        new_doc.insert_pdf(doc)
        
        new_doc.save(str(output_path), garbage=4, deflate=True, clean=True)
        new_doc.close()
        doc.close()

    except Exception as e:
        doc.close()
        logger.error("Repair rebuild failed: %s", e, exc_info=True)
        raise ConversionError(
            "Failed during the repair rebuild process.",
            detail=str(e),
        )

    stats = {"pages_recovered": recovered_count}
    logger.info("Repair successful: %d pages recovered", recovered_count)
    
    return output_path, stats


# ═══════════════════════════════════════════════════════════════════════════════
# 9. PDF to Image
# ═══════════════════════════════════════════════════════════════════════════════

def pdf_to_images(
    input_path: Path,
    output_dir: Path,
    dpi: int = _PDF_TO_IMAGE_DPI,
) -> tuple[Path, int]:
    """
    Convert each page of a PDF into a PNG image, packaged as a ZIP.

    Args:
        input_path: Path to the source PDF.
        output_dir: Temporary directory to write images to.
        dpi: Rendering resolution (dots per inch).

    Returns:
        Tuple of (zip_file_path, page_count).

    Raises:
        ConversionError: If rendering fails.
    """
    doc = _open_pdf(input_path)
    page_count = len(doc)
    
    if page_count == 0:
        doc.close()
        raise ConversionError("The PDF has 0 pages.")

    logger.info("Converting %d PDF pages to images at %d DPI", page_count, dpi)
    image_files = []

    try:
        for i in range(page_count):
            page = doc.load_page(i)
            # Use matrix for DPI scaling to ensure high quality
            zoom = dpi / 72  # PDF standard base is 72 DPI
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            img_filename = f"page_{i + 1}.png"
            img_path = output_dir / img_filename
            
            pix.save(str(img_path))
            image_files.append((img_filename, img_path))

        doc.close()

        zip_path = output_dir / f"{input_path.stem}_images.zip"
        _create_zip(image_files, zip_path)

        # Clean up raw PNGs
        for _, path in image_files:
            _safe_delete(path)

    except ConversionError:
        doc.close()
        raise
    except Exception as e:
        doc.close()
        logger.error("PDF to Image failed: %s", e, exc_info=True)
        raise ConversionError("Failed to render PDF pages to images.", detail=str(e))

    logger.info("PDF→Image complete: %d pages → %s", page_count, zip_path.name)
    return zip_path, page_count


# ═══════════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _open_pdf(path: Path) -> fitz.Document:
    """Open a PDF with standard error handling for ConversionError."""
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


def _create_zip(files: list[tuple[str, Path]], output_path: Path) -> Path:
    """Package a list of (filename, Path) into a ZIP archive."""
    try:
        with zipfile.ZipFile(str(output_path), "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, path in files:
                zf.write(path, arcname=filename)
    except Exception as e:
        raise ConversionError("Failed to package files into a ZIP archive.", detail=str(e))
    
    return output_path


def _safe_delete(path: Path | None) -> None:
    """Delete a file silently. Used for temp cleanup."""
    if path and path.exists():
        try:
            path.unlink()
        except Exception:
            pass
