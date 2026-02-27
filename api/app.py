"""
FastAPI application factory with lifespan events, CORS, and route registration.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pdf2zh_next.api.deps import get_user_manager
from pdf2zh_next.api.routes import auth, health, settings, translate
from pdf2zh_next.db.database import get_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("PDFMathTranslate Web API starting...")

    # Initialize database and recover stale tasks
    db = get_db()
    db.recover_stale_tasks()

    # Cleanup expired sessions
    get_user_manager().cleanup_expired_sessions()

    logger.info("Web API ready")
    yield
    logger.info("PDFMathTranslate Web API shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="PDFMathTranslate API",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(settings.router)
    app.include_router(translate.router)

    # Static files
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        css_dir = static_dir / "css"
        js_dir = static_dir / "js"

        if css_dir.exists():
            app.mount("/static/css", StaticFiles(directory=str(css_dir)), name="css")
        if js_dir.exists():
            app.mount("/static/js", StaticFiles(directory=str(js_dir)), name="js")

        app.mount(
            "/static", StaticFiles(directory=str(static_dir)), name="static_html"
        )
        app.mount(
            "/", StaticFiles(directory=str(static_dir), html=True), name="root"
        )

    return app


# Module-level app instance for uvicorn import
app = create_app()
