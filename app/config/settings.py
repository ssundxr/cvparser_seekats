"""
app/config/settings.py
-----------------------
Central application configuration loaded from environment variables via
pydantic-settings.  Single source of truth for all tunable parameters.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Application metadata ──────────────────────────────────────────────
    APP_NAME: str = "CV Parser API"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = (
        "Production-grade, AI-powered CV / résumé parsing service. "
        "Upload a PDF or DOCX and receive a structured JSON candidate profile."
    )
    ENVIRONMENT: str = "development"   # development | staging | production
    DEBUG: bool = True

    # ── Server ────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # ── JWT Authentication ────────────────────────────────────────────────
    ADMIN_TOKEN: str = Field(
        ...,
        description="Master token required to generate a JWT. Must be set in .env"
    )
    JWT_SECRET_KEY: str = Field(
        ...,
        description="Secret key to sign JWTs. Must be set in .env"
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # ── Gemini AI ────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # ── File upload limits ────────────────────────────────────────────────
    MAX_FILE_SIZE_MB: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


# Convenience alias used throughout the application
settings: Settings = get_settings()
