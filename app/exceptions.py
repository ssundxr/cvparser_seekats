"""
app/exceptions.py
------------------
Domain exception hierarchy for the CV Parser API.

All public exceptions inherit from ``CVParserBaseError``, which carries an
``http_status`` attribute.  This lets the global exception handler in
``app.main`` convert any domain error into a well-formed HTTP response without
any per-exception ``isinstance`` checks.

Exception map
-------------
┌─────────────────────────────┬────────┬────────────────────────────────────┐
│ Exception                   │ Status │ Scenario                           │
├─────────────────────────────┼────────┼────────────────────────────────────┤
│ UnsupportedFileTypeError    │  415   │ Extension not supported             │
│ MaliciousFileError          │  400   │ File content does not match ext    │
│ FileSizeLimitError          │  413   │ Upload exceeds MAX_FILE_SIZE_MB    │
│ CorruptedDocumentError      │  422   │ PDF/DOCX cannot be opened / parsed │
│ TextExtractionError         │  422   │ Extracted text is empty            │
│ OCRFailureError             │  422   │ Tesseract / PyMuPDF OCR failed     │
│ GeminiAPIError              │  502   │ Gemini network / quota / API error │
│ InvalidGeminiResponseError  │  502   │ Gemini returned bad / no JSON      │
└─────────────────────────────┴────────┴────────────────────────────────────┘
"""

from __future__ import annotations

from fastapi import status


# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────

class CVParserBaseError(Exception):
    """
    Base class for all domain errors in the CV Parser API.

    Attributes
    ----------
    http_status : int
        The HTTP status code that should be returned to the caller.
    detail : str
        Human-readable error description (safe to expose in API responses).
    """

    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:  # noqa: D105
        return self.detail


# ─────────────────────────────────────────────────────────────────────────────
# Authentication errors  (401 / 403)   — raised by security layer
# ─────────────────────────────────────────────────────────────────────────────
# Note: Auth errors are currently handled via FastAPI's built-in HTTPException
# inside token_validator.py.  They are NOT domain exceptions — this block is
# intentionally left empty to keep auth logic self-contained in that module.


# ─────────────────────────────────────────────────────────────────────────────
# File errors  (413 / 415 / 422)
# ─────────────────────────────────────────────────────────────────────────────

class UnsupportedFileTypeError(CVParserBaseError):
    """Raised when the uploaded file extension is not in the supported set."""

    http_status = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    def __init__(self, extension: str) -> None:
        super().__init__(
            f"Unsupported file type '{extension}'. "
            "Accepted formats: PDF (.pdf), Word (.docx), JPEG (.jpg/.jpeg), PNG (.png)."
        )
        self.extension = extension


class MaliciousFileError(CVParserBaseError):
    """Raised when the file content does not match the declared extension (magic-byte mismatch)."""

    http_status = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str = "The file content does not match its extension. Upload rejected.") -> None:
        super().__init__(detail)


class FileSizeLimitError(CVParserBaseError):
    """Raised when the uploaded file exceeds the configured size limit."""

    http_status = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    def __init__(self, size_mb: float, limit_mb: float) -> None:
        super().__init__(
            f"File size {size_mb:.1f} MB exceeds the {limit_mb} MB limit."
        )
        self.size_mb = size_mb
        self.limit_mb = limit_mb


class CorruptedDocumentError(CVParserBaseError):
    """Raised when a PDF or DOCX file cannot be opened or is structurally invalid."""

    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, detail: str = "The document is corrupted or cannot be read.") -> None:
        super().__init__(detail)


class TextExtractionError(CVParserBaseError):
    """Raised when text extraction produces no usable content."""

    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(
        self,
        detail: str = "Could not extract readable text from the document.",
    ) -> None:
        super().__init__(detail)


class OCRFailureError(CVParserBaseError):
    """Raised when the OCR pipeline fails on a scanned / image-based document or image."""

    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, detail: str = "OCR processing failed for this document.") -> None:
        super().__init__(detail)


# ─────────────────────────────────────────────────────────────────────────────
# External API errors  (502)
# ─────────────────────────────────────────────────────────────────────────────

class GeminiAPIError(CVParserBaseError):
    """Raised when the Google Gemini API returns an error or is unreachable."""

    http_status = status.HTTP_502_BAD_GATEWAY

    def __init__(self, detail: str = "The Gemini AI service is currently unavailable.") -> None:
        super().__init__(detail)


class InvalidGeminiResponseError(CVParserBaseError):
    """Raised when Gemini returns a response that cannot be parsed into CVData."""

    http_status = status.HTTP_502_BAD_GATEWAY

    def __init__(
        self,
        detail: str = "The Gemini AI returned an unexpected or malformed response.",
    ) -> None:
        super().__init__(detail)
