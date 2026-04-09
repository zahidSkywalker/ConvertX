"""
PDF to Office Routes — Extraction endpoints for Word, Excel, and PowerPoint.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.config import TOOL_INPUT_TYPES, OUTPUT_DIR
from backend.utils.file_utils import save_upload_file, register_output_file, format_file_size, _safe_delete
from backend.utils.response_models import (
    ConversionResponse,
    PdfToExcelResponse,
    PdfToPowerPointResponse,
)
from backend.converters import ConversionError
from backend.converters.pdf_to_office import (
    convert_pdf_to_word,
    convert_pdf_to_excel,
    convert_pdf_to_powerpoint,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["pdf-to-office"])


@router.post("/pdf-to-word", response_model=ConversionResponse)
async def pdf_to_word_endpoint(file: UploadFile = File(...)):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["pdf-to-word"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}.docx"
        convert_pdf_to_word(upload_path, output_path)
        
        dl_name = register_output_file(f"{upload_path.stem}.docx", output_path)
        _safe_delete(upload_path)
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}", filename=f"{upload_path.stem}.docx",
            size_bytes=output_path.stat().st_size, size_human=format_file_size(output_path.stat().st_size),
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("PDF→Word route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during conversion.")


@router.post("/pdf-to-excel", response_model=PdfToExcelResponse)
async def pdf_to_excel_endpoint(file: UploadFile = File(...)):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["pdf-to-excel"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}.xlsx"
        
        output_path, tables, rows = convert_pdf_to_excel(upload_path, output_path)
        
        dl_name = register_output_file(f"{upload_path.stem}.xlsx", output_path)
        _safe_delete(upload_path)
        
        return PdfToExcelResponse(
            download_url=f"/api/download/{dl_name}", filename=f"{upload_path.stem}.xlsx",
            size_bytes=output_path.stat().st_size, size_human=format_file_size(output_path.stat().st_size),
            tables_found=tables, rows_extracted=rows,
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("PDF→Excel route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during extraction.")


@router.post("/pdf-to-powerpoint", response_model=PdfToPowerPointResponse)
async def pdf_to_powerpoint_endpoint(file: UploadFile = File(...)):
    upload_path = output_path = None
    try:
        upload_path, _ = await save_upload_file(file, allowed_types=TOOL_INPUT_TYPES["pdf-to-powerpoint"])
        output_path = OUTPUT_DIR / f"{upload_path.stem}.pptx"
        
        output_path, slides = convert_pdf_to_powerpoint(upload_path, output_path)
        
        dl_name = register_output_file(f"{upload_path.stem}.pptx", output_path)
        _safe_delete(upload_path)
        
        return PdfToPowerPointResponse(
            download_url=f"/api/download/{dl_name}", filename=f"{upload_path.stem}.pptx",
            size_bytes=output_path.stat().st_size, size_human=format_file_size(output_path.stat().st_size),
            slide_count=slides,
        )
    except ConversionError as e:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except HTTPException:
        _safe_delete(upload_path); _safe_delete(output_path)
        raise
    except Exception as e:
        logger.error("PDF→PPT route error: %s", e, exc_info=True)
        _safe_delete(upload_path); _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Unexpected error during extraction.")
