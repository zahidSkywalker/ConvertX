"""
Pydantic response schemas — every API endpoint returns one of these.

Extended to include metadata fields for tools that return statistics
(e.g., compression ratio, OCR word counts, extracted table counts).
"""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response for GET /api/health."""
    status: str = Field(default="ok", description="Service health status")
    version: str = Field(default="1.0.0", description="API version")
    tesseract_available: bool = Field(description="Tesseract OCR installed")
    libreoffice_available: bool = Field(description="LibreOffice installed")


class ConversionResponse(BaseModel):
    """Base response for successful conversions (file in, file out)."""
    success: bool = Field(default=True)
    download_url: str = Field(description="Relative URL to download the file")
    filename: str = Field(description="Human-readable filename for download")
    size_bytes: int = Field(description="Output file size in bytes")
    size_human: str = Field(description="Human-readable file size")


class ImageToPdfResponse(ConversionResponse):
    """Image to PDF — includes page count."""
    page_count: int = Field(description="Number of pages in the generated PDF")


class ImageToExcelResponse(ConversionResponse):
    """Image to Excel — includes OCR stats."""
    rows_extracted: int = Field(description="Number of data rows extracted via OCR")


class CompressPdfResponse(ConversionResponse):
    """Compress PDF — includes compression stats."""
    original_size_bytes: int = Field(description="Original file size in bytes")
    compressed_size_bytes: int = Field(description="Compressed file size in bytes")
    reduction_percent: float = Field(description="Percentage of size reduced")


class SplitPdfResponse(ConversionResponse):
    """Split PDF — includes page count (output is a ZIP)."""
    page_count: int = Field(description="Number of pages in the original PDF")


class PdfToImageResponse(ConversionResponse):
    """PDF to Image — includes page count (output is a ZIP)."""
    page_count: int = Field(description="Number of images extracted")


class PdfToExcelResponse(ConversionResponse):
    """PDF to Excel — includes table extraction stats."""
    tables_found: int = Field(description="Number of tables detected in the PDF")
    rows_extracted: int = Field(description="Total data rows extracted across all tables")


class PdfToPowerPointResponse(ConversionResponse):
    """PDF to PowerPoint — includes slide count."""
    slide_count: int = Field(description="Number of slides created")


class OcrPdfResponse(ConversionResponse):
    """OCR PDF — includes processing stats."""
    pages_processed: int = Field(description="Number of pages processed")
    words_detected: int = Field(description="Total words detected via OCR")


class RepairPdfResponse(ConversionResponse):
    """Repair PDF — includes recovery stats."""
    pages_recovered: int = Field(description="Number of pages recovered from the corrupted file")


class ErrorResponse(BaseModel):
    """Response for any API error (4xx, 5xx)."""
    success: bool = Field(default=False)
    error: str = Field(description="Short error summary")
    detail: str = Field(default="", description="Extended error details")
