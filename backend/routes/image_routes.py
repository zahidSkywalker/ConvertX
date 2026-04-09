"""
Image Routes — Image to PDF and Image to Excel (OCR).
"""

import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.config import TOOL_INPUT_TYPES, OUTPUT_DIR
from backend.utils.file_utils import (
    save_upload_file,
    save_upload_files,
    register_output_file,
    format_file_size,
    _safe_delete,
)
from backend.utils.response_models import ImageToPdfResponse, ImageToExcelResponse
from backend.converters import ConversionError
from backend.converters.image_tools import convert_images_to_pdf, convert_image_to_excel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["image-tools"])


@router.post("/image-to-pdf", response_model=ImageToPdfResponse)
async def image_to_pdf_endpoint(
    files: list[UploadFile] = File(..., description="Images to combine (.jpg, .png, .webp)"),
):
    upload_paths: list[Path] = []
    output_path = OUTPUT_DIR / "images_combined.pdf"
    
    try:
        saved = await save_upload_files(files, allowed_types=TOOL_INPUT_TYPES["image-to-pdf"])
        upload_paths = [p for p, _ in saved]
        
        output_path, page_count = convert_images_to_pdf(upload_paths, output_path)
        
        dl_name = register_output_file("images_combined.pdf", output_path)
        for p in upload_paths: _safe_delete(p)
        
        return ImageToPdfResponse(
            download_url=f"/api/download/{dl_name}", filename="images_combined.pdf",
            size_bytes=output_path.stat().st_size, size_human=format_file_size(output_path.stat().st_size),
            page_count=page_count,
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
        logger.error("Image→PDF route error: %s", e, exc_info=True)
        for p in upload_paths: _safe_delete(p)
        _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error creating PDF.")


@router.post("/image-to-excel", response_model=ImageToExcelResponse)
async def image_to_excel_endpoint(
    file: UploadFile = File(..., description="Image containing a table"),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["image-to-excel"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}.xlsx"
        
        output_path, rows = convert_image_to_excel(upload_path, output_path)
        
        dl_name = register_output_file(f"{upload_path.stem}.xlsx", output_path)
        _safe_delete(upload_path)
        
        return ImageToExcelResponse(
            download_url=f"/api/download/{dl_name}", filename=f"{upload_path.stem}.xlsx",
            size_bytes=output_path.stat().st_size, size_human=format_file_size(output_path.stat().st_size),
            rows_extracted=rows,
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("Image→Excel route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error extracting data.")
