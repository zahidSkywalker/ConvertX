"""
Office to PDF Routes — Unified handler for Word, Excel, and PowerPoint.
Uses a DRY internal helper since the logic is identical for all three.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.config import TOOL_INPUT_TYPES, OUTPUT_DIR
from backend.utils.file_utils import save_upload_file, register_output_file, format_file_size, _safe_delete
from backend.utils.response_models import ConversionResponse
from backend.converters import ConversionError
from backend.converters.office_to_pdf import (
    convert_word_to_pdf,
    convert_excel_to_pdf,
    convert_powerpoint_to_pdf,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["office-to-pdf"])


async def _handle_conversion(tool_name: str, file: UploadFile, converter_func):
    """DRY handler for all Office -> PDF conversions."""
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES[tool_name])
        
        # Converter returns the actual path (LibreOffice controls the filename)
        output_path = converter_func(upload_path, OUTPUT_DIR)
        out_name = output_path.name
        
        dl_name = register_output_file(out_name, output_path)
        _safe_delete(upload_path)
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}", filename=out_name,
            size_bytes=output_path.stat().st_size, size_human=format_file_size(output_path.stat().st_size),
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("%s route error: %s", tool_name, e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during conversion.")


@router.post("/word-to-pdf", response_model=ConversionResponse)
async def word_to_pdf_endpoint(file: UploadFile = File(...)):
    return await _handle_conversion("word-to-pdf", file, convert_word_to_pdf)


@router.post("/excel-to-pdf", response_model=ConversionResponse)
async def excel_to_pdf_endpoint(file: UploadFile = File(...)):
    return await _handle_conversion("excel-to-pdf", file, convert_excel_to_pdf)


@router.post("/powerpoint-to-pdf", response_model=ConversionResponse)
async def powerpoint_to_pdf_endpoint(file: UploadFile = File(...)):
    return await _handle_conversion("powerpoint-to-pdf", file, convert_powerpoint_to_pdf)
