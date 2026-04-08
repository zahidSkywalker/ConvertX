"""
Pydantic response schemas — every API endpoint returns one of these.

Using Pydantic v2 syntax (model_dump, not dict()). These schemas serve
as both documentation (via FastAPI's auto-generated OpenAPI) and runtime
validation for response serialization.
"""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response for GET /api/health — reports tool availability."""
    status: str = Field(default="ok", description="Service health status")
    version: str = Field(default="1.0.0", description="API version")
    tesseract_available: bool = Field(
        description="Whether Tesseract OCR is installed and accessible"
    )
    libreoffice_available: bool = Field(
        description="Whether LibreOffice is installed and accessible"
    )


class ConversionResponse(BaseModel):
    """Base response for successful file conversions."""
    success: bool = Field(default=True, description="Whether conversion succeeded")
    download_url: str = Field(
        description="Relative URL to download the converted file"
    )
    filename: str = Field(
        description="Human-readable filename for the download"
    )
    size_bytes: int = Field(description="Output file size in bytes")
    size_human: str = Field(
        description="Human-readable file size (e.g. '2.4 MB')"
    )


class ImageToPdfResponse(ConversionResponse):
    """Extended response for image-to-PDF with page count."""
    page_count: int = Field(
        description="Number of pages (images) in the generated PDF"
    )


class ImageToExcelResponse(ConversionResponse):
    """Extended response for image-to-Excel with extraction stats."""
    rows_extracted: int = Field(
        description="Number of data rows extracted via OCR"
    )


class ErrorResponse(BaseModel):
    """Response for any API error (4xx, 5xx)."""
    success: bool = Field(default=False, description="Always false for errors")
    error: str = Field(description="Short error summary")
    detail: str = Field(
        default="",
        description="Extended error details (may include specifics about what went wrong)",
    )
