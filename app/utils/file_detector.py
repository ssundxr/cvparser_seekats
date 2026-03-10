"""
app/utils/file_detector.py
---------------------------
Detects and validates the type of an uploaded CV file.

Centralises all file-type logic including:
  - Extension validation against the supported set
  - Magic-byte verification to block disguised/malicious uploads
  - Filename sanitization to strip path-traversal and null bytes

The rest of the codebase never needs to inspect filenames directly.
"""

from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath

from app.exceptions import MaliciousFileError, UnsupportedFileTypeError

logger = logging.getLogger(__name__)

__all__ = [
    "UnsupportedFileTypeError",
    "MaliciousFileError",
    "SUPPORTED_EXTENSIONS",
    "detect_and_validate",
    "validate_file_content",
    "sanitize_filename",
]

# Supported file extensions
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx",
    ".jpg", ".jpeg", ".png",
})

# ── Magic-byte signatures ─────────────────────────────────────────────────────
# Each extension maps to a tuple of byte-prefixes that legitimate files begin
# with.  DOCX is a ZIP archive, so we check the PK header.
_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    ".pdf":  (b"%PDF",),
    ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".jpg":  (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png":  (b"\x89PNG\r\n\x1a\n",),
}


def sanitize_filename(filename: str) -> str:
    """
    Clean a user-supplied filename to prevent path-traversal and injection.

    - Strips directory components (e.g. ``../../etc/passwd`` → ``passwd``)
    - Removes null bytes and non-printable characters
    - Collapses whitespace
    - Replaces dangerous characters (``\\ / : * ? " < > |``)
    - Falls back to ``"upload"`` if the result is empty

    Parameters
    ----------
    filename : str
        Raw filename from the HTTP upload.

    Returns
    -------
    str
        Safe, flat filename suitable for logging and extension extraction.
    """
    # Remove null bytes
    name = filename.replace("\x00", "")

    # Strip directory components (handles both / and \)
    name = PurePosixPath(name.replace("\\", "/")).name

    # Remove non-printable characters
    name = re.sub(r"[^\x20-\x7E]", "", name)

    # Replace dangerous path characters
    name = re.sub(r'[\\/:*?"<>|]', "_", name)

    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()

    return name or "upload"


def detect_and_validate(filename: str) -> str:
    """
    Determine and validate the file type from the (sanitized) filename.

    Parameters
    ----------
    filename : str
        Original filename provided by the uploader (will be sanitized internally).

    Returns
    -------
    str
        Lower-case file extension (e.g. ``".pdf"``, ``".docx"``, ``".jpg"``).

    Raises
    ------
    UnsupportedFileTypeError
        When the extension is not in ``SUPPORTED_EXTENSIONS``.
    """
    safe_name = sanitize_filename(filename)
    extension = PurePosixPath(safe_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(extension)
    return extension


def validate_file_content(file_bytes: bytes, extension: str) -> None:
    """
    Verify the file content matches the declared extension via magic-byte check.

    This prevents a user from renaming ``malware.exe`` to ``cv.pdf`` and
    bypassing extension-only validation.

    Parameters
    ----------
    file_bytes : bytes
        Raw binary content of the uploaded file.
    extension : str
        Validated lower-case extension (e.g. ``".pdf"``).

    Raises
    ------
    MaliciousFileError
        When the file's leading bytes do not match the expected magic signature.
    """
    expected_prefixes = _MAGIC_BYTES.get(extension)
    if expected_prefixes is None:
        return  # no magic-byte rule for this extension — skip

    if not any(file_bytes.startswith(prefix) for prefix in expected_prefixes):
        logger.warning(
            "Magic-byte mismatch: extension '%s' but file starts with %r",
            extension,
            file_bytes[:16],
        )
        raise MaliciousFileError(
            f"The uploaded file does not appear to be a valid '{extension}' file. "
            "The file content does not match the expected format."
        )
