"""
app/main.py
-----------
FastAPI application factory.

This module is the sole place responsible for:
  - Creating the FastAPI instance with OpenAPI / Swagger metadata
  - Registering routers and middleware
  - Mounting the static frontend
  - Managing the application lifespan (startup / shutdown hooks)

No business logic, routing handlers, or service calls live here.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.exceptions import CVParserBaseError
from app.routes.cv_routes import router as cv_router

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.info(
        "🚀  %s v%s starting [%s]",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
    )
    yield
    logger.info("🛑  %s shutting down.", settings.APP_NAME)


# ── Application factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create, configure, and return the FastAPI application."""

    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=settings.APP_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "SeekATS Team"},
        license_info={"name": "Proprietary"},
        openapi_tags=[
            {
                "name": "CV Parsing",
                "description": (
                    "AI-powered endpoint that accepts a PDF or DOCX résumé and "
                    "returns a fully structured JSON candidate profile."
                ),
            },
            {
                "name": "Health",
                "description": "Service health and readiness checks.",
            },
        ],
    )

    # ── CORS ─────────────────────────────────────────────────────────────
    # Restrict allow_origins to your production domain(s) before deploying.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health check ──────────────────────────────────────────────────────
    @application.get("/health", tags=["Health"], summary="Health check")
    async def health_check() -> dict:
        return {
            "status": "ok",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }

    # ── API routes ────────────────────────────────────────────────────────
    from app.routes.auth_routes import router as auth_router
    application.include_router(auth_router)
    application.include_router(cv_router)

    # ── Global domain exception handler ───────────────────────────────────
    # Safety net: converts any CVParserBaseError that escapes route handlers
    # into a structured JSON response with the correct HTTP status code.
    @application.exception_handler(CVParserBaseError)
    async def domain_exception_handler(
        request: Request, exc: CVParserBaseError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": exc.detail},
        )

    return application


# ── WSGI/ASGI entry point ─────────────────────────────────────────────────────

app: FastAPI = create_app()
