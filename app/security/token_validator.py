"""
app/security/token_validator.py
--------------------------------
FastAPI dependencies that authenticate callers.

Two layers of authentication are enforced on every CV parsing request:

1. ``verify_jwt`` — validates the short-lived JWT in the ``Authorization: Bearer`` header.
2. ``get_gemini_api_key`` — extracts the Gemini API key from ``X-Gemini-Api-Key``.

Both dependencies raise ``HTTPException`` with the appropriate 401 status so
that FastAPI returns a standard, well-formed error response.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

from app.config.settings import settings

# ── JWT bearer scheme ─────────────────────────────────────────────────────────
# auto_error=False so we can return 401 instead of FastAPI's default 403
# for a completely missing Authorization header.
_bearer_scheme = HTTPBearer(auto_error=False)

# ── Gemini API key header scheme ──────────────────────────────────────────────
_gemini_key_scheme = APIKeyHeader(
    name="X-Gemini-Api-Key",
    description="Your personal Google Gemini API key used for parsing.",
    auto_error=False,
)


# ─────────────────────────────────────────────────────────────────────────────
# Token creation
# ─────────────────────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    """Create a new JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Dependencies
# ─────────────────────────────────────────────────────────────────────────────

async def verify_jwt(
    auth: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency — validates the JWT token in the Authorization header.

    Returns the ``sub`` claim if authorised.

    Raises
    ------
    HTTPException 401
        - Missing access token (no Authorization header).
        - Expired access token.
        - Invalid / malformed access token.
    """
    # ── Missing token ─────────────────────────────────────────────────────
    if auth is None or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing access token. "
                "Provide 'Authorization: Bearer <token>' in the request headers. "
                "Obtain a token via POST /api/v1/auth/token."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth.credentials

    # ── Validate token ────────────────────────────────────────────────────
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload.get("sub", "authorized")

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Access token has expired. "
                "Re-authenticate via POST /api/v1/auth/token to obtain a new token."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token. The token is malformed or has been tampered with.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_gemini_api_key(
    x_gemini_api_key: str | None = Depends(_gemini_key_scheme),
) -> str:
    """
    FastAPI dependency — extracts the Gemini API Key from the ``X-Gemini-Api-Key`` header.

    Raises
    ------
    HTTPException 401
        When the header is absent or empty.
    """
    key = (x_gemini_api_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing Gemini API Key. "
                "Provide a valid Google Gemini API key via the 'X-Gemini-Api-Key' header."
            ),
        )
    return key
