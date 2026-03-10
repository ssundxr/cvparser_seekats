"""
app/utils/image_parser.py
--------------------------
OCR-based text extraction for image-only / scanned PDF documents
and standalone image files (JPG, JPEG, PNG).

Uses PyMuPDF (fitz) to render PDF pages to high-DPI images and
Pillow + pytesseract to perform OCR.

For PDFs, this module is invoked as a fallback when ``pdf_parser.is_image_based()``
returns ``True``.  For standalone images, ``parse_image_file()`` is called directly.
"""

from __future__ import annotations

import logging
from io import BytesIO

from app.exceptions import CorruptedDocumentError, OCRFailureError

logger = logging.getLogger(__name__)

try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False

try:
    from PIL import Image
    import pytesseract
    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False

_HAS_OCR = _HAS_FITZ and _HAS_TESSERACT

if not _HAS_TESSERACT:
    logger.warning(
        "OCR dependencies (Pillow, pytesseract) are not fully installed. "
        "Image-based text extraction will not be supported."
    )

# DPI used when rendering PDF pages to images — 300 gives good OCR accuracy
_RENDER_DPI: int = 300


def parse_image_pdf(file_bytes: bytes) -> str:
    """
    Perform Tesseract OCR on every page of an image-based PDF.

    Parameters
    ----------
    file_bytes : bytes
        Raw binary content of the PDF file.

    Returns
    -------
    str
        OCR-extracted text concatenated from all pages.

    Raises
    ------
    OCRFailureError
        If the required OCR dependencies are not installed, or if the OCR
        process encounters an unrecoverable error.
    """
    if not _HAS_OCR:
        raise OCRFailureError(
            "The document appears to be scanned / image-based, but the required "
            "OCR dependencies (PyMuPDF, Pillow, pytesseract) are not installed. "
            "Install them with: pip install pymupdf Pillow pytesseract"
        )

    text_parts: list[str] = []

    try:
        doc = fitz.open("pdf", file_bytes)
        logger.info("Starting OCR on %d page(s).", doc.page_count)

        for page_index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=_RENDER_DPI)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            page_text = pytesseract.image_to_string(img)
            text_parts.append(page_text)
            logger.debug("OCR page %d — %d chars.", page_index, len(page_text))

    except OCRFailureError:
        raise  # already typed, re-raise as-is
    except Exception as exc:
        logger.error("OCR processing failed: %s", exc)
        raise OCRFailureError(f"OCR processing failed: {exc}") from exc

    full_text = "\n".join(text_parts)
    logger.info("OCR complete — %d total characters extracted.", len(full_text))
    return full_text


def parse_image_file(file_bytes: bytes) -> str:
    """
    Perform Tesseract OCR on a standalone image file (JPG, JPEG, PNG).

    Parameters
    ----------
    file_bytes : bytes
        Raw binary content of the image file.

    Returns
    -------
    str
        OCR-extracted text from the image.

    Raises
    ------
    OCRFailureError
        If Pillow / pytesseract are not installed or OCR fails.
    CorruptedDocumentError
        If the image cannot be opened by Pillow.
    """
    if not _HAS_TESSERACT:
        raise OCRFailureError(
            "Image OCR requires Pillow and pytesseract. "
            "Install them with: pip install Pillow pytesseract"
        )

    try:
        img = Image.open(BytesIO(file_bytes))
        # Convert to RGB if needed (handles RGBA PNGs, palette images, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    except Exception as exc:
        logger.error("Failed to open image file: %s", exc)
        raise CorruptedDocumentError(
            f"The image file could not be opened and may be corrupted: {exc}"
        ) from exc

    try:
        text = pytesseract.image_to_string(img)
    except Exception as exc:
        logger.error("OCR failed on image: %s", exc)
        raise OCRFailureError(f"OCR processing failed on the image: {exc}") from exc

    logger.info("Image OCR complete — %d characters extracted.", len(text))
    return text
