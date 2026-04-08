"""
ConvertX converter modules.

Each converter module is grouped by the primary library it depends on:
  - pdf_core: PyMuPDF (fitz) for structural/image manipulations
  - pdf_edit: PyMuPDF + Tesseract for advanced editing/OCR
  - pdf_to_office: pdf2docx, pdfplumber, python-pptx for extraction
  - office_to_pdf: LibreOffice CLI for Office suite conversions
  - image_tools: fpdf2, pytesseract for image conversions
  - html_to_pdf: WeasyPrint for HTML rendering

All converters raise ConversionError on failure. Routes catch these
and translate them to HTTP responses.
"""


class ConversionError(Exception):
    """
    Raised when a file conversion cannot be completed.

    Attributes:
        message: Short, user-facing error description.
        detail: Optional extended detail for debugging.
    """

    def __init__(self, message: str, detail: str = ""):
        self.message = message
        self.detail = detail
        super().__init__(message)
