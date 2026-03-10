"""
tests/test_api_v1_cv_parse.py
------------------------------
Integration tests for POST /api/v1/cv/parse.

Uses FastAPI's TestClient (Starlette) — no real Gemini calls are made;
the AI parser service is mocked to isolate HTTP-layer behaviour.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.exceptions import (
    CorruptedDocumentError,
    GeminiAPIError,
    InvalidGeminiResponseError,
    MaliciousFileError,
    OCRFailureError,
    TextExtractionError,
)
from app.services.cv_parsing_service import CVData, ContactInfo, Education, Experience
from app.config.settings import settings
from app.main import create_app

app = create_app()
client = TestClient(app, raise_server_exceptions=False)

# ── Shared fixtures ───────────────────────────────────────────────────────────

MOCK_CV_DATA = CVData(
    name="Jane Smith",
    contact_info=ContactInfo(
        email="jane@example.com",
        phone="+44-7700900000",
        linkedin="linkedin.com/in/janesmith",
        github="github.com/janesmith",
    ),
    education=[
        Education(
            institution="University of Cambridge",
            degree="MEng Computer Science",
            graduation_year="2021",
        )
    ],
    experience=[
        Experience(
            company="DeepMind",
            role="Research Engineer",
            start_date="Aug 2021",
            end_date="Present",
            description="RL research.",
        )
    ],
    skills=["Python", "PyTorch", "Kubernetes"],
)

DUMMY_PDF_BYTES = b"%PDF-1.4 dummy content for testing"

# Minimal valid JPEG (smallest valid JFIF header)
DUMMY_JPG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

# Minimal valid PNG (8-byte signature)
DUMMY_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _get_jwt() -> str:
    """Helper: exchange the admin token for a short-lived JWT."""
    resp = client.post("/api/v1/auth/token", json={"admin_token": settings.ADMIN_TOKEN})
    assert resp.status_code == 200, f"Auth failed: {resp.json()}"
    return resp.json()["access_token"]


def _auth_headers(jwt: str, gemini_key: str = "test-gemini-key") -> dict:
    return {
        "Authorization": f"Bearer {jwt}",
        "X-Gemini-Api-Key": gemini_key,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAuthErrors:
    """Authentication error scenarios — 401."""

    def test_missing_jwt_returns_401(self):
        """No Authorization header → 401 with a clear message."""
        response = client.post(
            "/api/v1/cv/parse",
            files={"file": ("cv.pdf", DUMMY_PDF_BYTES, "application/pdf")},
            headers={"X-Gemini-Api-Key": "test-key"},
        )
        assert response.status_code == 401
        assert "Missing access token" in response.json()["detail"]

    def test_invalid_jwt_returns_401(self):
        """Garbage token string → 401."""
        response = client.post(
            "/api/v1/cv/parse",
            files={"file": ("cv.pdf", DUMMY_PDF_BYTES, "application/pdf")},
            headers={
                "Authorization": "Bearer this.is.garbage",
                "X-Gemini-Api-Key": "test-key",
            },
        )
        assert response.status_code == 401
        assert "Invalid access token" in response.json()["detail"]

    def test_missing_gemini_key_returns_401(self):
        """No X-Gemini-Api-Key header → 401."""
        jwt = _get_jwt()
        response = client.post(
            "/api/v1/cv/parse",
            files={"file": ("cv.pdf", DUMMY_PDF_BYTES, "application/pdf")},
            headers={"Authorization": f"Bearer {jwt}"},
        )
        assert response.status_code == 401
        assert "Missing Gemini API Key" in response.json()["detail"]


class TestFileErrors:
    """File validation error scenarios — 400, 413, 415."""

    def test_unsupported_file_type_returns_415(self):
        """Uploading a .txt file → 415 with a clear message."""
        jwt = _get_jwt()
        response = client.post(
            "/api/v1/cv/parse",
            files={"file": ("cv.txt", b"Name: John Smith", "text/plain")},
            headers=_auth_headers(jwt),
        )
        assert response.status_code == 415
        assert "Unsupported file type" in response.json()["detail"]

    def test_file_too_large_returns_413(self):
        """File exceeding MAX_FILE_SIZE_MB → 413."""
        oversized = b"x" * int((settings.MAX_FILE_SIZE_MB + 1) * 1024 * 1024)
        jwt = _get_jwt()
        response = client.post(
            "/api/v1/cv/parse",
            files={"file": ("big.pdf", oversized, "application/pdf")},
            headers=_auth_headers(jwt),
        )
        assert response.status_code == 413
        assert "exceeds" in response.json()["detail"]

    def test_malicious_file_returns_400(self):
        """File with .pdf extension but executable content → 400."""
        malicious_bytes = b"MZ" + b"\x00" * 100  # PE executable header
        jwt = _get_jwt()
        response = client.post(
            "/api/v1/cv/parse",
            files={"file": ("cv.pdf", malicious_bytes, "application/pdf")},
            headers=_auth_headers(jwt),
        )
        assert response.status_code == 400
        assert "does not appear to be a valid" in response.json()["detail"]

    def test_path_traversal_filename_sanitized(self):
        """Filename with path-traversal is sanitized — doesn't crash."""
        jwt = _get_jwt()
        # The filename contains path-traversal but the extension is still .pdf
        response = client.post(
            "/api/v1/cv/parse",
            files={"file": ("../../etc/passwd.pdf", DUMMY_PDF_BYTES, "application/pdf")},
            headers=_auth_headers(jwt),
        )
        # Should still process (extension is valid, magic bytes match %PDF)
        # It will fail later at text extraction, but NOT with a path-traversal exploit
        assert response.status_code != 500

    def test_image_extension_accepted(self):
        """JPG/PNG extensions are accepted (not rejected as unsupported)."""
        jwt = _get_jwt()
        # Mock the entire parse pipeline since the image bytes aren't a real image
        with (
            patch("app.services.cv_parsing_service.validate_file_content"),
            patch("app.services.cv_parsing_service._extract_text", return_value="raw cv text"),
            patch("app.services.cv_parsing_service._build_entity_hints", return_value=""),
            patch("app.services.gemini_service.call_gemini", return_value=MOCK_CV_DATA),
        ):
            response = client.post(
                "/api/v1/cv/parse",
                files={"file": ("cv.jpg", DUMMY_JPG_BYTES, "image/jpeg")},
                headers=_auth_headers(jwt),
            )
        assert response.status_code == 200
        assert response.json()["name"] == "Jane Smith"


class TestProcessingErrors:
    """Processing error scenarios — 422."""

    def _post_pdf(self, jwt: str) -> object:
        return client.post(
            "/api/v1/cv/parse",
            files={"file": ("cv.pdf", DUMMY_PDF_BYTES, "application/pdf")},
            headers=_auth_headers(jwt),
        )

    def test_corrupted_document_returns_422(self):
        """CorruptedDocumentError from parsers → 422."""
        jwt = _get_jwt()
        with patch(
            "app.services.cv_parsing_service._extract_text",
            side_effect=CorruptedDocumentError("The PDF file could not be read."),
        ):
            response = self._post_pdf(jwt)
        assert response.status_code == 422
        assert "could not be read" in response.json()["detail"].lower()

    def test_text_extraction_failure_returns_422(self):
        """TextExtractionError → 422."""
        jwt = _get_jwt()
        with patch(
            "app.services.cv_parsing_service._extract_text",
            side_effect=TextExtractionError("Could not extract readable text."),
        ):
            response = self._post_pdf(jwt)
        assert response.status_code == 422
        assert "text" in response.json()["detail"].lower()

    def test_ocr_failure_returns_422(self):
        """OCRFailureError → 422."""
        jwt = _get_jwt()
        with patch(
            "app.services.cv_parsing_service._extract_text",
            side_effect=OCRFailureError("OCR processing failed."),
        ):
            response = self._post_pdf(jwt)
        assert response.status_code == 422
        assert "OCR" in response.json()["detail"]


class TestExternalAPIErrors:
    """External API error scenarios — 502."""

    def _post_with_mocked_text(self, jwt: str, gemini_exc: Exception) -> object:
        with (
            patch("app.services.cv_parsing_service._extract_text", return_value="some cv text"),
            patch("app.services.cv_parsing_service._build_entity_hints", return_value=""),
            patch("app.services.gemini_service.call_gemini", side_effect=gemini_exc),
        ):
            return client.post(
                "/api/v1/cv/parse",
                files={"file": ("cv.pdf", DUMMY_PDF_BYTES, "application/pdf")},
                headers=_auth_headers(jwt),
            )

    def test_gemini_api_failure_returns_502(self):
        """GeminiAPIError → 502."""
        jwt = _get_jwt()
        response = self._post_with_mocked_text(
            jwt, GeminiAPIError("Gemini service unavailable.")
        )
        assert response.status_code == 502
        assert "Gemini" in response.json()["detail"]

    def test_invalid_gemini_response_returns_502(self):
        """InvalidGeminiResponseError → 502."""
        jwt = _get_jwt()
        response = self._post_with_mocked_text(
            jwt, InvalidGeminiResponseError("Gemini returned malformed JSON.")
        )
        assert response.status_code == 502
        assert "Gemini" in response.json()["detail"]


class TestSuccessAndHealth:
    """Happy-path and health check."""

    def test_successful_parse_returns_200(self):
        """Valid PDF + valid JWT + API key → 200 with structured CVData."""
        jwt = _get_jwt()
        with (
            patch("app.services.cv_parsing_service._extract_text", return_value="raw cv text"),
            patch("app.services.cv_parsing_service._build_entity_hints", return_value=""),
            patch("app.services.gemini_service.call_gemini", return_value=MOCK_CV_DATA),
        ):
            response = client.post(
                "/api/v1/cv/parse",
                files={"file": ("cv.pdf", DUMMY_PDF_BYTES, "application/pdf")},
                headers=_auth_headers(jwt),
            )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Jane Smith"
        assert body["contact_info"]["email"] == "jane@example.com"
        assert "Python" in body["skills"]

    def test_health_check(self):
        """GET /health → 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestFileSanitization:
    """Unit-level tests for the file_detector module's sanitization utilities."""

    def test_sanitize_strips_path_traversal(self):
        from app.utils.file_detector import sanitize_filename
        assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"

    def test_sanitize_removes_null_bytes(self):
        from app.utils.file_detector import sanitize_filename
        assert "\x00" not in sanitize_filename("cv\x00.pdf")

    def test_sanitize_replaces_dangerous_chars(self):
        from app.utils.file_detector import sanitize_filename
        result = sanitize_filename('cv<script>.pdf')
        assert "<" not in result
        assert ">" not in result

    def test_sanitize_empty_falls_back(self):
        from app.utils.file_detector import sanitize_filename
        assert sanitize_filename("") == "upload"
        assert sanitize_filename("\x00") == "upload"

    def test_magic_byte_pdf_valid(self):
        from app.utils.file_detector import validate_file_content
        # Should not raise — starts with %PDF
        validate_file_content(b"%PDF-1.4 content", ".pdf")

    def test_magic_byte_pdf_invalid(self):
        from app.utils.file_detector import validate_file_content
        with pytest.raises(MaliciousFileError):
            validate_file_content(b"MZ\x00\x00not-a-pdf", ".pdf")

    def test_magic_byte_jpg_valid(self):
        from app.utils.file_detector import validate_file_content
        validate_file_content(b"\xff\xd8\xff\xe0some-image-data", ".jpg")

    def test_magic_byte_png_valid(self):
        from app.utils.file_detector import validate_file_content
        validate_file_content(b"\x89PNG\r\n\x1a\nimage-data", ".png")
