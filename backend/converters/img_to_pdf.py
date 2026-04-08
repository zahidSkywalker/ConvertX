"""
Image to PDF converter — stitches multiple images into a single PDF.

Uses Pillow for image validation/processing and fpdf2 for PDF generation.

Each image is placed on its own page, scaled to fit within A4 margins
while preserving aspect ratio. The page orientation (portrait/landscape)
is automatically selected based on each image's dimensions.

Supported input formats: JPEG, PNG, WebP (validated upstream).
All images are converted to RGB before embedding (handles transparency,
grayscale, palette-mode images correctly).
"""

import logging
from pathlib import Path

from PIL import Image
from fpdf import FPDF

from backend.converters import ConversionError

logger = logging.getLogger(__name__)

# ─── Page layout constants (millimeters) ────────────────────────────────────
_A4_WIDTH_MM = 210.0
_A4_HEIGHT_MM = 297.0
_PAGE_MARGIN_MM = 10.0

# Maximum image dimension in pixels — images larger than this are downscaled
# to prevent fpdf2 from creating bloated PDFs (>100MB for a single page).
_MAX_IMAGE_PIXELS = 4000


def convert_images_to_pdf(
    image_paths: list[Path],
    output_path: Path,
) -> tuple[Path, int]:
    """
    Convert a list of images into a single multi-page PDF.

    Each image occupies one page. Pages are A4-sized with automatic
    orientation selection per image.

    Args:
        image_paths: Ordered list of paths to image files.
                     Order is preserved in the PDF.
        output_path: Path where the output PDF will be written.
                     Parent directory must exist.

    Returns:
        Tuple of (output_file_path, page_count).

    Raises:
        ConversionError: If any image cannot be opened, the list is empty,
                         or PDF generation fails.
    """
    # ── Validate inputs ──
    if not image_paths:
        raise ConversionError(
            message="No images provided for conversion.",
        )

    for i, path in enumerate(image_paths):
        if not path.exists():
            raise ConversionError(
                message=f"Image file #{i + 1} was not found.",
                detail=f"Expected file at: {path}",
            )
        if path.stat().st_size == 0:
            raise ConversionError(
                message=f"Image file #{i + 1} ('{path.name}') is empty (0 bytes).",
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting Image→PDF: %d images",
        len(image_paths),
    )

    # ── Create PDF ──
    try:
        pdf = FPDF(unit="mm", format="A4")
        pdf.set_auto_page_break(auto=False)
        # Disable fpdf2's internal compression to keep generation fast
        pdf.set_compression_level(6)

        for idx, img_path in enumerate(image_paths):
            _add_image_page(pdf, img_path, idx + 1, len(image_paths))

        pdf.output(str(output_path))

    except ConversionError:
        raise
    except Exception as e:
        logger.error(
            "Error generating PDF at image #%d: %s",
            idx + 1 if 'idx' in dir() else '?',
            e,
            exc_info=True,
        )
        raise ConversionError(
            message="Failed to generate the PDF. One of the images may be corrupted.",
            detail=f"{type(e).__name__}: {e}",
        )

    # ── Verify output ──
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise ConversionError(
            message="PDF generation completed but the output file is empty or missing.",
        )

    page_count = len(image_paths)
    logger.info(
        "Image→PDF complete: %d pages → %s (%.1f KB)",
        page_count,
        output_path.name,
        output_path.stat().st_size / 1024,
    )

    return output_path, page_count


def _add_image_page(
    pdf: FPDF,
    img_path: Path,
    index: int,
    total: int,
) -> None:
    """
    Open an image, compute layout, add a page to the PDF, and embed the image.

    The image is converted to RGB, downscaled if excessively large, then
    fitted within A4 page margins while preserving aspect ratio.
    """
    # ── Open and validate image ──
    try:
        img = Image.open(img_path)
    except Exception as e:
        raise ConversionError(
            message=f"Cannot open image #{index} ('{img_path.name}'). "
                    f"The file may be corrupted.",
            detail=str(e),
        )

    try:
        # ── Convert to RGB ──
        # fpdf2 handles RGB well. For images with alpha (PNG, WebP),
        # composite onto a white background so transparency doesn't
        # render as black in the PDF.
        if img.mode in ("RGBA", "LA", "PA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            # Extract alpha channel for compositing
            if img.mode == "PA":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode == "P":
            # Palette mode — convert through RGBA to handle transparency
            img_rgba = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img_rgba, mask=img_rgba.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # ── Downscale if excessively large ──
        img_w_px, img_h_px = img.size
        max_dim = max(img_w_px, img_h_px)
        if max_dim > _MAX_IMAGE_PIXELS:
            scale = _MAX_IMAGE_PIXELS / max_dim
            new_w = int(img_w_px * scale)
            new_h = int(img_h_px * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            img_w_px, img_h_px = new_w, new_h
            logger.debug(
                "Image #%d downscaled from %dx%d to %dx%d",
                index, img_w_px, img_h_px,
                int(img_w_px / scale), int(img_h_px / scale),
            )

        # ── Compute aspect ratio ──
        aspect = img_w_px / img_h_px

        # ── Determine page orientation ──
        if aspect > (_A4_WIDTH_MM / _A4_HEIGHT_MM):
            # Image is wider than A4 portrait — use landscape
            orientation = "L"
            page_w = _A4_HEIGHT_MM  # Landscape: width becomes height
            page_h = _A4_WIDTH_MM
        else:
            orientation = "P"
            page_w = _A4_WIDTH_MM
            page_h = _A4_HEIGHT_MM

        # ── Compute display dimensions (fit within margins) ──
        avail_w = page_w - 2 * _PAGE_MARGIN_MM
        avail_h = page_h - 2 * _PAGE_MARGIN_MM

        if aspect > (avail_w / avail_h):
            # Image is wider relative to available space — constrain by width
            display_w = avail_w
            display_h = avail_w / aspect
        else:
            # Image is taller relative to available space — constrain by height
            display_h = avail_h
            display_w = avail_h * aspect

        # ── Center on page ──
        x = _PAGE_MARGIN_MM + (avail_w - display_w) / 2
        y = _PAGE_MARGIN_MM + (avail_h - display_h) / 2

        # ── Add page and embed image ──
        pdf.add_page(orientation=orientation)
        pdf.image(img, x=x, y=y, w=display_w, h=display_h)

        logger.debug(
            "Added page %d/%d: %s (%dx%d px, %s, %.0fx%.0f mm)",
            index, total, img_path.name,
            img_w_px, img_h_px,
            orientation,
            display_w, display_h,
        )

    finally:
        img.close()
