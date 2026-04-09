"""
PDF Core Routes — 8 endpoints for structural and visual PDF manipulations.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from backend.config import TOOL_INPUT_TYPES, OUTPUT_DIR
from backend.utils.file_utils import (
    save_upload_file,
    save_upload_files,
    register_output_file,
    format_file_size,
)
from backend.utils.response_models import (
    ConversionResponse,
    CompressPdfResponse,
    SplitPdfResponse,
    PdfToImageResponse,
)
from backend.converters import ConversionError
from backend.converters.pdf_core import (
    merge_pdfs,
    split_pdf,
    rotate_pdf,
    compress_pdf,
    watermark_pdf,
    add_page_numbers,
    organize_pages,
    repair_pdf,
    pdf_to_images,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["pdf-core"])


def _safe_delete(path: Path | None) -> None:
    if path and path.exists():
        try: path.unlink()
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Merge PDF
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/merge-pdf", response_model=ConversionResponse)
async def merge_pdf_endpoint(
    files: list[UploadFile] = File(..., description="Multiple PDF files to merge"),
):
    upload_paths: list[Path] = []
    output_path = OUTPUT_DIR / "merged.pdf"
    
    try:
        saved = await save_upload_files(files, allowed_types=TOOL_INPUT_TYPES["merge-pdf"])
        upload_paths = [p for p, _ in saved]
        merge_pdfs(upload_paths, output_path)
        
        dl_name = register_output_file("merged.pdf", output_path)
        for p in upload_paths: _safe_delete(p)
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}",
            filename="merged.pdf",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )
    except ConversionError as e:
        for p in upload_paths: _safe_delete(p)
        _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        for p in upload_paths: _safe_delete(p)
        _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("Merge route error: %s", e, exc_info=True)
        for p in upload_paths: _safe_delete(p)
        _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during merge.")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Split PDF
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/split-pdf", response_model=SplitPdfResponse)
async def split_pdf_endpoint(
    file: UploadFile = File(..., description="PDF file to split"),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["split-pdf"])
        temp_dir = OUTPUT_DIR / f"split_temp_{upload_path.stem}"
        temp_dir.mkdir(exist_ok=True)
        
        output_path, page_count = split_pdf(upload_path, temp_dir)
        dl_name = register_output_file(f"{upload_path.stem}_split_pages.zip", output_path)
        
        _safe_delete(upload_path)
        # Clean temp dir if anything remains
        try:
            if temp_dir.exists(): 
                for f in temp_dir.iterdir(): f.unlink(missing_ok=True)
                temp_dir.rmdir()
        except Exception: pass

        return SplitPdfResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_split_pages.zip",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
            page_count=page_count,
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("Split route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during split.")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Rotate PDF
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/rotate-pdf", response_model=ConversionResponse)
async def rotate_pdf_endpoint(
    file: UploadFile = File(...),
    degrees: int = Form(..., description="Rotation angle (90, 180, 270)"),
    page_numbers: Optional[str] = Form(None, description="JSON list of 1-based page numbers. If omitted, rotates all."),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["rotate-pdf"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}_rotated.pdf"
        
        pages = json.loads(page_numbers) if page_numbers else None
        rotate_pdf(upload_path, output_path, degrees, pages)
        
        dl_name = register_output_file(f"{upload_path.stem}_rotated.pdf", output_path)
        _safe_delete(upload_path)
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_rotated.pdf",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )
    except json.JSONDecodeError:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=400, detail="page_numbers must be a valid JSON array of integers.")
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("Rotate route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during rotation.")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Compress PDF
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/compress-pdf", response_model=CompressPdfResponse)
async def compress_pdf_endpoint(
    file: UploadFile = File(...),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["compress-pdf"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}_compressed.pdf"
        
        output_path, stats = compress_pdf(upload_path, output_path)
        
        dl_name = register_output_file(f"{upload_path.stem}_compressed.pdf", output_path)
        _safe_delete(upload_path)
        
        return CompressPdfResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_compressed.pdf",
            size_bytes=stats["compressed_size"],
            size_human=format_file_size(stats["compressed_size"]),
            original_size_bytes=stats["original_size"],
            compressed_size_bytes=stats["compressed_size"],
            reduction_percent=stats["reduction_percent"],
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("Compress route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during compression.")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Watermark PDF
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/watermark-pdf", response_model=ConversionResponse)
async def watermark_pdf_endpoint(
    file: UploadFile = File(...),
    watermark_text: str = Form(..., description="Text to stamp (e.g. CONFIDENTIAL)"),
    opacity: float = Form(0.3, description="Opacity 0.05 to 1.0"),
    angle: int = Form(45, description="Angle in degrees"),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["watermark-pdf"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}_watermarked.pdf"
        
        watermark_pdf(upload_path, output_path, watermark_text, opacity, angle)
        
        dl_name = register_output_file(f"{upload_path.stem}_watermarked.pdf", output_path)
        _safe_delete(upload_path)
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_watermarked.pdf",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("Watermark route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error applying watermark.")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Add Page Numbers
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/add-page-numbers", response_model=ConversionResponse)
async def add_page_numbers_endpoint(
    file: UploadFile = File(...),
    position: str = Form("bottom-center", description="Position: bottom-center, top-right, etc."),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["add-page-numbers"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}_numbered.pdf"
        
        add_page_numbers(upload_path, output_path, position)
        
        dl_name = register_output_file(f"{upload_path.stem}_numbered.pdf", output_path)
        _safe_delete(upload_path)
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_numbered.pdf",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("Page numbers route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error adding page numbers.")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Organize Pages
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/organize-pages", response_model=ConversionResponse)
async def organize_pages_endpoint(
    file: UploadFile = File(...),
    new_order: str = Form(..., description='JSON array of 1-based page indices, e.g. "[3, 1, 2]"'),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["organize-pages"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}_reordered.pdf"
        
        order = json.loads(new_order)
        if not isinstance(order, list) or not all(isinstance(p, int) for p in order):
            raise HTTPException(status_code=400, detail="new_order must be a JSON array of integers.")
            
        organize_pages(upload_path, output_path, order)
        
        dl_name = register_output_file(f"{upload_path.stem}_reordered.pdf", output_path)
        _safe_delete(upload_path)
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_reordered.pdf",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )
    except json.JSONDecodeError:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=400, detail="new_order must be valid JSON.")
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except Exception as e:
        logger.error("Organize route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error reorganizing pages.")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. PDF to Image
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/pdf-to-image", response_model=PdfToImageResponse)
async def pdf_to_image_endpoint(
    file: UploadFile = File(...),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["pdf-to-image"])
        temp_dir = OUTPUT_DIR / f"img_temp_{upload_path.stem}"
        temp_dir.mkdir(exist_ok=True)
        
        output_path, page_count = pdf_to_images(upload_path, temp_dir)
        dl_name = register_output_file(f"{upload_path.stem}_images.zip", output_path)
        
        _safe_delete(upload_path)
        try:
            if temp_dir.exists(): 
                for f in temp_dir.iterdir(): f.unlink(missing_ok=True)
                temp_dir.rmdir()
        except Exception: pass

        return PdfToImageResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_images.zip",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
            page_count=page_count,
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("PDF to Image route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error rendering images.")
