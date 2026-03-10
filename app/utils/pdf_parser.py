"""
app/utils/pdf_parser.py
------------------------
Extracts raw text from native (text-layer) PDF files using pdfplumber.

This module handles only text-layer PDFs.  For image-based / scanned PDFs
where text extraction yields unusably sparse results, the caller should
fall back to ``app.utils.image_parser.parse_image_pdf``.
"""

from __future__ import annotations

import logging
from io import BytesIO

from app.exceptions import CorruptedDocumentError, TextExtractionError

logger = logging.getLogger(__name__)

try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False
    logger.warning("pdfplumber is not installed — PDF text extraction unavailable.")

# Pages that yield fewer than this many characters are considered image-based
_SPARSE_TEXT_THRESHOLD: int = 50


def parse_pdf(file_bytes: bytes) -> str:
    """
    Extract text from a PDF using pdfplumber's layout-aware engine.

    Parameters
    ----------
    file_bytes : bytes
        Raw binary content of the PDF file.

    Returns
    -------
    str
        Extracted text.  May be sparse or empty for scanned documents — use
        ``is_image_based()`` to detect this case.

    Raises
    ------
    TextExtractionError
        If pdfplumber is not installed.
    CorruptedDocumentError
        If the PDF cannot be opened or is structurally invalid.
    """
    if not _HAS_PDFPLUMBER:
        raise TextExtractionError(
            "PDF text extraction is unavailable (pdfplumber not installed)."
        )

    text = ""
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                # layout=True preserves visual column order and table alignment
                page_text = page.extract_text(layout=True)
                if page_text:
                    text += page_text + "\n"
    except Exception as exc:
        logger.error("pdfplumber failed to open PDF: %s", exc)
        raise CorruptedDocumentError(
            f"The PDF file could not be read and may be corrupted: {exc}"
        ) from exc

    logger.debug("PDF text extraction — %d characters extracted.", len(text))
    return text


def is_image_based(text: str) -> bool:
    """
    Heuristic check: returns ``True`` when the extracted text is too sparse
    to be useful, indicating a scanned / image-only PDF.

    Parameters
    ----------
    text : str
        Text returned by ``parse_pdf()``.
    """
    return len(text.strip()) < _SPARSE_TEXT_THRESHOLD
