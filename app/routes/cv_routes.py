"""
app/routes/cv_routes.py
------------------------
HTTP route handlers for the CV Parser API v1.

This module contains ONLY routing logic:
  - Accept and size-validate the uploaded file
  - Extract credentials via security dependencies
  - Delegate to ``cv_parsing_service.parse_cv_file()``
  - Map domain errors to HTTP responses
  - Return the serialised ``CVData`` response

No business logic, file parsing, or AI calls live here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.config.settings import settings
from app.exceptions import (
    CorruptedDocumentError,
    FileSizeLimitError,
    GeminiAPIError,
    InvalidGeminiResponseError,
    MaliciousFileError,
    OCRFailureError,
    TextExtractionError,
    UnsupportedFileTypeError,
)
from app.security.token_validator import get_gemini_api_key, verify_jwt
from app.services.cv_parsing_service import CVData, parse_cv_file

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["CV Parsing"],
)


@router.post(
    "/cv/parse",
    response_model=CVData,
    status_code=status.HTTP_200_OK,
    summary="Parse a CV / résumé",
    description="""
Upload a **PDF**, **DOCX**, **JPG/JPEG**, or **PNG** résumé and receive a fully structured JSON
candidate profile suitable for direct storage in a candidate database.

### Processing Pipeline
1. **File Detection** — Extension + magic-byte validated against supported types.
2. **Text Extraction** — Layout-aware extraction from native PDFs; automatic
   OCR fallback for scanned / image-based documents; paragraph extraction for DOCX;
   direct OCR for standalone image files (JPG, PNG).
3. **NLP Pre-processing** — spaCy NER extracts organisation, location, and
   person entities as contextual hints for the AI model.
4. **AI Parsing** — Google Gemini extracts and structures all fields with
   schema-validated output (via `instructor` when available).

### Security
- File size limited to the configured maximum (see parameter description).
- File extensions are validated against the supported set.
- Magic-byte verification blocks disguised / malicious file uploads.
- Filenames are sanitized to prevent path-traversal and injection.
- **No uploaded files are stored** — all processing is done in memory.

### Authentication (2-Tier)
To successfully parse a CV, you must provide **two** headers:
1. `Authorization: Bearer <token>`: The short-lived JWT access token (obtainable via `/api/v1/auth/token`).
2. `X-Gemini-Api-Key: <key>`: Your personal Google Gemini API key used by the parsing engine.

### Supported Formats
`application/pdf` · `application/vnd.openxmlformats-officedocument.wordprocessingml.document` · `image/jpeg` · `image/png`
""",
    responses={
        200: {"description": "CV parsed successfully.", "model": CVData},
        400: {"description": "File content does not match its declared extension (malicious upload)."},
        401: {"description": "Missing or invalid JWT token, or missing Gemini API Key."},
        413: {"description": "File size exceeds the configured limit."},
        415: {"description": "Unsupported file type."},
        422: {"description": "Corrupted document, or text/OCR extraction failed."},
        502: {"description": "Gemini AI service error or unexpected response."},
    },
)
async def parse_cv(
    file: UploadFile = File(
        ...,
        description=(
            f"PDF, DOCX, JPG, JPEG, or PNG résumé file. "
            f"Maximum size: {settings.MAX_FILE_SIZE_MB} MB."
        ),
    ),
    authorized_user: str = Depends(verify_jwt),
    gemini_api_key: str = Depends(get_gemini_api_key),
) -> CVData:
    """Parse a CV/résumé and return structured candidate data."""

    # ── 1. Read upload & enforce size limit ───────────────────────────────
    file_bytes = await file.read()
    size_mb = len(file_bytes) / (1024 * 1024)

    logger.info(
        "Received '%s' (%.2f MB) via user '%s'.",
        file.filename,
        size_mb,
        authorized_user,
    )

    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=FileSizeLimitError(size_mb, settings.MAX_FILE_SIZE_MB).detail,
        )

    # ── 2. Delegate to the orchestration service ──────────────────────────
    try:
        return parse_cv_file(
            file_bytes=file_bytes,
            filename=file.filename or "",
            api_key=gemini_api_key,
        )

    # ── File errors ───────────────────────────────────────────────────────
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=exc.detail,
        ) from exc

    except MaliciousFileError as exc:
        logger.warning("Malicious file blocked: %s", exc.detail)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
        ) from exc

    except CorruptedDocumentError as exc:
        logger.warning("Corrupted document: %s", exc.detail)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc

    # ── Processing errors ─────────────────────────────────────────────────
    except TextExtractionError as exc:
        logger.warning("Text extraction failed: %s", exc.detail)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc

    except OCRFailureError as exc:
        logger.warning("OCR failure: %s", exc.detail)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.detail,
        ) from exc

    # ── External API errors ───────────────────────────────────────────────
    except GeminiAPIError as exc:
        logger.error("Gemini API error: %s", exc.detail)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.detail,
        ) from exc

    except InvalidGeminiResponseError as exc:
        logger.error("Invalid Gemini response: %s", exc.detail)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.detail,
        ) from exc
