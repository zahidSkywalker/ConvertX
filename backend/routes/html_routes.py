"""
HTML to PDF Route — accepts raw HTML string (no file upload).
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from backend.config import OUTPUT_DIR
from backend.utils.file_utils import register_output_file, format_file_size, _safe_delete
from backend.utils.response_models import ConversionResponse
from backend.converters import ConversionError
from backend.converters.html_to_pdf import convert_html_to_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["html"])


class HtmlToPdfRequest(BaseModel):
    html: str = Field(..., min_length=1, description="The HTML content to convert")
    css: Optional[str] = Field(None, description="Optional raw CSS to inject")


@router.post("/html-to-pdf", response_model=ConversionResponse)
async def html_to_pdf_endpoint(body: HtmlToPdfRequest):
    output_path = OUTPUT_DIR / "converted.html.pdf"
    try:
        convert_html_to_pdf(body.html, output_path, body.css)
        
        dl_name = register_output_file("converted.html.pdf", output_path)
        
        return ConversionResponse(
            download_url=f"/api/download/{dl_name}",
            filename="converted.html.pdf",
            size_bytes=output_path.stat().st_size,
            size_human=format_file_size(output_path.stat().st_size),
        )
    except ConversionError as e:
        _safe_delete(output_path)
        raise HTTPException(status_code=422, detail=e.message)
    except Exception as e:
        logger.error("HTML→PDF route error: %s", e, exc_info=True)
        _safe_delete(output_path)
        raise HTTPException(status_code=500, detail="Failed to render HTML to PDF.")
