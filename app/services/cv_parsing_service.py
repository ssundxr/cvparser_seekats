"""
app/services/cv_parsing_service.py
------------------------------------
CV parsing orchestration service + domain models.

This module is the single entry point for the full CV parsing pipeline.
It owns the ``CVData`` domain models and coordinates the following stages:

  1. File type detection   → app.utils.file_detector
  2. Text extraction       → app.utils.pdf_parser / docx_parser / image_parser
  3. NLP entity hints      → spaCy NER (lazy-loaded inline)
  4. AI structured parsing → app.services.gemini_service

Callers (routes) interact only with ``parse_cv_file()`` and the models
defined in this module.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.exceptions import TextExtractionError
from app.utils.file_detector import detect_and_validate, validate_file_content
from app.utils.pdf_parser import is_image_based, parse_pdf
from app.utils.image_parser import parse_image_file, parse_image_pdf
from app.utils.docx_parser import parse_docx

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Domain Models
# Defined here because this service owns the output contract for the pipeline.
# ─────────────────────────────────────────────────────────────────────────────

class ContactInfo(BaseModel):
    """Contact details and online profile links."""
    email:     Optional[str] = Field(None, description="Email address.")
    phone:     Optional[str] = Field(None, description="Phone number with country code.")
    location:  Optional[str] = Field(None, description="City / country as stated on CV.")
    linkedin:  Optional[str] = Field(None, description="LinkedIn profile URL or handle.")
    github:    Optional[str] = Field(None, description="GitHub profile URL or handle.")
    portfolio: Optional[str] = Field(None, description="Personal website or portfolio URL.")


class Education(BaseModel):
    """A single educational qualification."""
    institution:     str = Field(description="University, college, or school name.")
    degree:          str = Field(description="Degree or qualification awarded.")
    graduation_year: str = Field(description="Year of graduation.")


class Experience(BaseModel):
    """A single work experience entry."""
    company:     str = Field(description="Employer name.")
    role:        str = Field(description="Job title.")
    start_date:  str = Field(description="Role start date.")
    end_date:    str = Field(description="Role end date ('Present' if current).")
    description: str = Field(description="Responsibilities and achievements.")


class Certification(BaseModel):
    """A professional certification or accreditation."""
    name:   str           = Field(description="Certification name.")
    issuer: Optional[str] = Field(None, description="Issuing organisation.")
    date:   Optional[str] = Field(None, description="Issue or expiry date.")


class CVData(BaseModel):
    """
    Fully structured candidate profile.
    Designed to be stored directly in a candidate database.
    """
    name:           str                     = Field(description="Full candidate name.")
    contact_info:   ContactInfo             = Field(description="Contact details and online profiles.")
    summary:        Optional[str]           = Field(None, description="Professional summary or objective.")
    education:      list[Education]         = Field(default_factory=list)
    experience:     list[Experience]        = Field(default_factory=list)
    skills:         list[str]               = Field(default_factory=list)
    certifications: list[Certification]     = Field(default_factory=list)
    languages:      list[str]               = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Jane Smith",
                "contact_info": {
                    "email": "jane@example.com",
                    "phone": "+44-7700900000",
                    "location": "London, UK",
                    "linkedin": "linkedin.com/in/janesmith",
                    "github": "github.com/janesmith",
                    "portfolio": "janesmith.io",
                },
                "summary": "Research engineer specialising in RL and robotics.",
                "education": [{"institution": "Cambridge", "degree": "MEng CS", "graduation_year": "2021"}],
                "experience": [{"company": "DeepMind", "role": "Research Engineer", "start_date": "Aug 2021", "end_date": "Present", "description": "RL agent development."}],
                "skills": ["Python", "PyTorch", "Kubernetes"],
                "certifications": [{"name": "Google ML Engineer", "issuer": "Google Cloud", "date": "Nov 2022"}],
                "languages": ["English (Native)", "French (Intermediate)"],
            }
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# NLP Entity Hints (private, lazy-loaded)
# ─────────────────────────────────────────────────────────────────────────────

_nlp = None
_spacy_ready = False


def _get_nlp():
    """Lazily load the spaCy model to avoid startup pydantic v1/v2 conflicts."""
    global _nlp, _spacy_ready
    if _spacy_ready:
        return _nlp
    _spacy_ready = True
    try:
        import spacy  # noqa: PLC0415
        _nlp = spacy.load("en_core_web_sm")
        logger.info("spaCy model loaded.")
    except Exception:
        logger.warning("spaCy unavailable — NER hints will be skipped.")
    return _nlp


def _build_entity_hints(text: str) -> str:
    """Run NER on the first 10 000 characters and format as a prompt hint string."""
    nlp = _get_nlp()
    if nlp is None:
        return ""

    doc = nlp(text[:10_000])
    buckets: dict[str, set[str]] = {"ORG": set(), "PERSON": set(), "GPE": set()}
    for ent in doc.ents:
        if ent.label_ in buckets:
            cleaned = ent.text.replace("\n", " ").strip()
            if cleaned:
                buckets[ent.label_].add(cleaned)

    if not any(buckets.values()):
        return ""

    return (
        "\n[NLP Pre-processing Hints — use these to improve accuracy]\n"
        f"Organisations: {', '.join(list(buckets['ORG'])[:15]) or 'none'}\n"
        f"Locations: {', '.join(list(buckets['GPE'])[:15]) or 'none'}\n"
        f"People: {', '.join(list(buckets['PERSON'])[:15]) or 'none'}\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public orchestration interface
# ─────────────────────────────────────────────────────────────────────────────

def parse_cv_file(file_bytes: bytes, filename: str, api_key: str) -> CVData:
    """
    Run the full CV parsing pipeline end-to-end.

    Parameters
    ----------
    file_bytes : bytes
        Raw binary content of the uploaded file.
    filename : str
        Original filename (used for file type detection only).
    api_key : str
        Validated Gemini API key from the security layer.

    Returns
    -------
    CVData
        Validated structured candidate profile.

    Raises
    ------
    UnsupportedFileTypeError
        When the file extension is not supported.
    RuntimeError
        When text extraction or AI parsing fails.
    """
    # ── Stage 1: File type detection ─────────────────────────────────────
    ext = detect_and_validate(filename)
    logger.info("Processing file '%s' (ext=%s).", filename, ext)

    # ── Stage 1b: Magic-byte validation (anti-malicious-upload) ──────────
    validate_file_content(file_bytes, ext)

    # ── Stage 2: Text extraction ──────────────────────────────────────────
    raw_text = _extract_text(file_bytes, ext)
    logger.info("Text extraction complete — %d characters.", len(raw_text))

    if not raw_text.strip():
        raise TextExtractionError(
            "Could not extract any readable text from the document. "
            "The file may be empty, image-only without OCR support, or use unsupported formatting."
        )

    # ── Stage 3: NLP entity hints ─────────────────────────────────────────
    entity_hints = _build_entity_hints(raw_text)

    # ── Stage 4: AI parsing ───────────────────────────────────────────────
    # Import here to avoid circular import (gemini_service imports CVData from here)
    from app.services.gemini_service import call_gemini  # noqa: PLC0415
    return call_gemini(raw_text, entity_hints, api_key)


_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})


def _extract_text(file_bytes: bytes, ext: str) -> str:
    """Route to the correct parser based on detected file extension."""
    if ext == ".docx":
        return parse_docx(file_bytes)

    # Standalone image files — direct OCR
    if ext in _IMAGE_EXTENSIONS:
        return parse_image_file(file_bytes)

    # PDF: attempt text extraction first, fall back to OCR if image-based
    text = parse_pdf(file_bytes)
    if is_image_based(text):
        logger.info("Sparse text detected — switching to OCR fallback.")
        text = parse_image_pdf(file_bytes)
    return text
