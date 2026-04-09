"""
Advanced PDF Editing Routes — Edit PDF and OCR PDF.

Edit PDF is architecturally unique: it receives a base PDF, multiple image
files, and a JSON string of operations in a single multipart/form-data request.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from backend.config import TOOL_INPUT_TYPES, OUTPUT_DIR
from backend.utils.file_utils import (
    save_upload_file,
    save_upload_files,
    register_output_file,
    format_file_size,
    _safe_delete,
)
from backend.utils.response_models import ConversionResponse, OcrPdfResponse
from backend.converters import ConversionError
from backend.converters.pdf_edit import apply_pdf_edits, ocr_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["pdf-advanced"])


@router.post("/edit-pdf", response_model=ConversionResponse)
async def edit_pdf_endpoint(
    file: UploadFile = File(..., description="Base PDF file"),
    images: List[UploadFile] = File(default=[], description="Images to insert"),
    operations: str = Form(..., description='JSON string of operations, e.g. \'[{"type": "add_text", ...}]\''),
):
    """
    Apply edits to a PDF.
    Operations JSON format:
    [{"type": "add_text", "page": 1, "x": 100, "y": 100, "text": "Hello", "fontsize": 12},
     {"type": "add_image", "page": 1, "x": 50, "y": 50, "width": 200, "height": 200, "filename": "logo.png"}]
    """
    upload_path = output_path = None
    image_upload_paths: list[Path] = []
    
    try:
        # 1. Validate JSON payload
        try:
            ops_list = json.loads(operations)
            if not isinstance(ops_list, list):
                raise ValueError("Operations must be a JSON array.")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 2. Save base PDF
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["edit-pdf"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}_edited.pdf"

        # 3. Save uploaded images and build secure path map
        image_path_map = {}
        if images:
            saved_images = await save_upload_files(images, allowed_types=["image/jpeg", "image/png", "image/webp"])
            image_upload_paths = [p for p, _ in saved_images]
            
            # Map the ORIGINAL filename (sent by frontend) to the SECURE server path
            for img_file, (secure_path, _) in zip(images, saved_images):
                if img_file.filename:
                    image_path_map[img_file.filename] = secure_path

        # 4. Apply edits
        apply_pdf_edits(upload_path, output_path, ops_list, image_path_map)
        
        # 5. Register and cleanup
        dl_name = register_output_file(f"{upload_path.stem}_edited.pdf", output_path)
        _safe_delete(upload_path)
        # NOTE: Do NOT delete image_upload_paths here! They might be needed if the
        # user re-opens the editor. They will be cleaned up by the TTL background task.
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_edited.pdf",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )

    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except Exception as e:
        logger.error("Edit PDF route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error applying edits.")


@router.post("/ocr-pdf", response_model=OcrPdfResponse)
async def ocr_pdf_endpoint(
    file: UploadFile = File(..., description="Scanned PDF to make searchable"),
):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["ocr-pdf"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}_searchable.pdf"
        
        output_path, pages, words = ocr_pdf(upload_path, output_path)
        
        dl_name = register_output_file(f"{upload_path.stem}_searchable.pdf", output_path)
        _safe_delete(upload_path)
        
        return OcrPdfResponse(
            download_url=f"/api/download/{dl_name}",
            filename=f"{upload_path.stem}_searchable.pdf",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
            pages_processed=pages,
            words_detected=words,
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("OCR PDF route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during OCR processing.")
