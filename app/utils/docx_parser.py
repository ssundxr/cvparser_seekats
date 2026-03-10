"""
app/utils/docx_parser.py
-------------------------
Extracts raw text from Microsoft Word (.docx) documents using python-docx.

Paragraph text is joined with newlines to preserve the logical document
structure for downstream NLP and AI processing.
"""

from __future__ import annotations

import logging
from io import BytesIO

from app.exceptions import CorruptedDocumentError, TextExtractionError

logger = logging.getLogger(__name__)

try:
    import docx as python_docx
    _HAS_DOCX = True
except ImportError:
    _HAS_DOCX = False
    logger.warning("python-docx is not installed — DOCX parsing unavailable.")


def parse_docx(file_bytes: bytes) -> str:
    """
    Extract plain text from a DOCX file.

    Parameters
    ----------
    file_bytes : bytes
        Raw binary content of the DOCX file.

    Returns
    -------
    str
        Paragraph text joined with newlines.

    Raises
    ------
    TextExtractionError
        If python-docx is not installed.
    CorruptedDocumentError
        If the file is corrupted or cannot be parsed as a valid DOCX document.
    TextExtractionError
        If the document contains no readable text after extraction.
    """
    if not _HAS_DOCX:
        raise TextExtractionError(
            "DOCX text extraction is unavailable (python-docx not installed)."
        )

    try:
        document = python_docx.Document(BytesIO(file_bytes))
        text = "\n".join(
            paragraph.text
            for paragraph in document.paragraphs
            if paragraph.text.strip()  # skip blank paragraphs
        )
    except Exception as exc:
        logger.error("python-docx failed to parse DOCX: %s", exc)
        raise CorruptedDocumentError(
            f"The DOCX file could not be read and may be corrupted: {exc}"
        ) from exc

    if not text.strip():
        raise TextExtractionError(
            "The DOCX document contains no readable text. "
            "It may be empty or use unsupported formatting."
        )

    logger.debug("DOCX extraction — %d characters extracted.", len(text))
    return text
