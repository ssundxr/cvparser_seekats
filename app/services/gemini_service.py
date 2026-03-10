"""
app/services/gemini_service.py
-------------------------------
Pure Gemini AI interaction layer.

Responsibility: Build the extraction prompt, call the Google Gemini API,
and return a validated ``CVData`` domain object.

No file I/O, no HTTP concerns, no orchestration logic lives here.
Both ``instructor`` (guaranteed schema) and native JSON mode (fallback)
are supported transparently.
"""

from __future__ import annotations

import json
import logging

import google.generativeai as genai

from app.config.settings import settings
from app.exceptions import GeminiAPIError, InvalidGeminiResponseError
from app.services.cv_parsing_service import CVData

logger = logging.getLogger(__name__)

# ── Optional instructor guard ─────────────────────────────────────────────────
try:
    import instructor
    _HAS_INSTRUCTOR = True
    logger.info("instructor library detected — using structured output mode.")
except ImportError:
    _HAS_INSTRUCTOR = False
    logger.warning("instructor not installed — falling back to native Gemini JSON mode.")

# ── Gemini response schema (native JSON fallback) ─────────────────────────────
_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "contact_info": {
            "type": "object",
            "properties": {
                "email":     {"type": "string"},
                "phone":     {"type": "string"},
                "location":  {"type": "string"},
                "linkedin":  {"type": "string"},
                "github":    {"type": "string"},
                "portfolio": {"type": "string"},
            },
        },
        "summary": {"type": "string"},
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution":     {"type": "string"},
                    "degree":          {"type": "string"},
                    "graduation_year": {"type": "string"},
                },
            },
        },
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company":     {"type": "string"},
                    "role":        {"type": "string"},
                    "start_date":  {"type": "string"},
                    "end_date":    {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "certifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":   {"type": "string"},
                    "issuer": {"type": "string"},
                    "date":   {"type": "string"},
                },
            },
        },
        "languages": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "contact_info", "education", "experience", "skills"],
}


def _build_prompt(cv_text: str, entity_hints: str) -> str:
    """Compose the extraction prompt sent to Gemini."""
    return f"""You are an expert HR data extraction system. Parse the provided résumé / CV text
and extract ALL of the following fields with extreme precision and accuracy.

Fields to extract:
- name: Full candidate name
- contact_info.email: Email address
- contact_info.phone: Phone number (include country code if present)
- contact_info.location: City, state, or country (as written on the CV)
- contact_info.linkedin: LinkedIn URL or handle
- contact_info.github: GitHub URL or handle
- contact_info.portfolio: Personal website or portfolio URL
- summary: Professional summary or objective statement (verbatim or paraphrased)
- education: All educational qualifications (institution, degree, graduation_year)
- experience: All work experiences (company, role, start_date, end_date, description)
- skills: Comprehensive de-duplicated list of technical AND soft skills
- certifications: Professional certifications (name, issuer, date)
- languages: Languages spoken with proficiency level where stated

Rules:
- Extract ALL entries found — do not summarise or truncate.
- Preserve exact names and dates as written in the CV.
- If a field is absent, use an empty string ("") or empty list ([]).
- Do NOT infer or hallucinate information not explicitly stated.
{entity_hints}
--- CV TEXT START ---
{cv_text}
--- CV TEXT END ---"""


def call_gemini(cv_text: str, entity_hints: str, api_key: str) -> CVData:
    """
    Send the CV text to Gemini and return a validated ``CVData`` object.

    Parameters
    ----------
    cv_text : str
        Raw text extracted from the CV document.
    entity_hints : str
        Formatted NER hint block from the orchestration layer (may be empty).
    api_key : str
        Caller-supplied Gemini API key (already validated by the security layer).

    Returns
    -------
    CVData
        Validated, structured candidate profile.

    Raises
    ------
    GeminiAPIError
        On Gemini API failure (network error, quota exceeded, invalid key, etc.).
    InvalidGeminiResponseError
        When Gemini returns a response that cannot be parsed into CVData.
    """
    genai.configure(api_key=api_key)
    prompt = _build_prompt(cv_text, entity_hints)

    logger.info(
        "Sending %d characters to Gemini model '%s'.",
        len(cv_text),
        settings.GEMINI_MODEL,
    )

    if _HAS_INSTRUCTOR:
        return _call_with_instructor(prompt)
    return _call_with_native_json(prompt)


def _call_with_instructor(prompt: str) -> CVData:
    """Use instructor for schema-guaranteed Gemini output."""
    try:
        base_model = genai.GenerativeModel(settings.GEMINI_MODEL)
        client = instructor.from_gemini(
            client=base_model,
            mode=instructor.Mode.GEMINI_JSON,
        )
        result: CVData = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            response_model=CVData,
            max_retries=3,
        )
        logger.info("Gemini parsing succeeded via instructor.")
        return result
    except Exception as exc:
        logger.error("instructor Gemini call failed: %s", exc)
        raise GeminiAPIError(
            f"The Gemini AI service returned an error: {exc}"
        ) from exc


def _call_with_native_json(prompt: str) -> CVData:
    """Use Gemini's native JSON mode as a fallback."""
    try:
        model = genai.GenerativeModel(
            settings.GEMINI_MODEL,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": _RESPONSE_SCHEMA,
            },
        )
        response = model.generate_content(prompt)
        raw: dict = json.loads(response.text)
    except json.JSONDecodeError as exc:
        logger.error("Gemini returned non-JSON response.")
        raise InvalidGeminiResponseError(
            "Gemini returned a response that could not be parsed as JSON."
        ) from exc
    except Exception as exc:
        logger.error("Native JSON Gemini call failed: %s", exc)
        raise GeminiAPIError(
            f"The Gemini AI service returned an error: {exc}"
        ) from exc

    try:
        result = CVData(**raw)
    except Exception as exc:
        logger.error("Gemini response failed CVData validation: %s", exc)
        raise InvalidGeminiResponseError(
            f"Gemini returned a response that does not match the expected schema: {exc}"
        ) from exc

    logger.info("Gemini parsing succeeded via native JSON mode.")
    return result
