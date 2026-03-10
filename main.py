"""
main.py  (project root)
-----------------------
Thin entry-point shim.

Imports the application instance from ``app.main`` so that the service can
be started with either:

    uvicorn main:app --reload         (backward-compatible, from project root)
    uvicorn app.main:app --reload     (canonical form matching the target structure)

No logic lives here — everything is in app/.
"""

from app.main import app  # noqa: F401 — re-exported for uvicorn

if __name__ == "__main__":
    import uvicorn
    from app.config.settings import settings

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
