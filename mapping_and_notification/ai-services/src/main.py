"""
main.py
-------
FastAPI application factory for the Campus Navigation AI Service.

Responsibilities:
  - Create and configure the FastAPI application instance.
  - Register global middleware (CORS, request logging).
  - Mount the versioned API router.
  - Expose the /health endpoint.
  - Handle startup / shutdown lifecycle events.

Entry point:
  uvicorn src.main:app --reload --port 8000
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware


from src.api.router import api_router
from src.config_settings import settings
from src.utils.logging_config import configure_logging, get_logger

# Initialise logging before anything else
configure_logging(
    log_level=settings.log_level,
    is_development=settings.is_development,
)

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan — startup and shutdown events
# ─────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    FastAPI lifespan context manager for startup and shutdown hooks.

    Startup:  Validate dependencies, warm up any caches.
    Shutdown: Release resources cleanly.
    """
    # ── Startup ────────────────────────────────────────────────────────────────
    logger.info(
        "AI service starting",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        host=settings.host,
        port=settings.port,
    )

    # Validate that OpenCV is importable and functional
    try:
        import cv2
        import numpy as np
        test_img = np.zeros((10, 10, 3), dtype=np.uint8)
        cv2.cvtColor(test_img, cv2.COLOR_BGR2GRAY)
        logger.info("OpenCV verified", version=cv2.__version__)
    except Exception as exc:
        logger.error("OpenCV validation failed — service may not function correctly", error=str(exc))

    logger.info(
        "AI service ready",
        docs_url=f"http://{settings.host}:{settings.port}/docs",
        health_url=f"http://{settings.host}:{settings.port}/health",
    )

    yield  # Application runs here

    # ── Shutdown ───────────────────────────────────────────────────────────────
    logger.info("AI service shutting down")


# ─────────────────────────────────────────────────────────────────────────────
# Application factory
# ─────────────────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Campus Navigation System — AI Services\n\n"
            "This service provides computer vision AI capabilities for the campus navigation platform. "
            "It is a stateless microservice called by the Node.js backend.\n\n"
            "**Implemented Modules:** Wall Detection"
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── CORS ───────────────────────────────────────────────────────────────────
    # Allow the Node.js backend and React frontend to call this service.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request logging middleware ─────────────────────────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        t_start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        logger.info(
            "HTTP request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed_ms, 2),
        )
        return response

    # ── Routers ────────────────────────────────────────────────────────────────
    app.include_router(api_router)

    # ── Health endpoint ────────────────────────────────────────────────────────
    @app.get(
        "/health",
        tags=["Health"],
        summary="Health check",
        description="Returns service health status. Used by Docker, orchestrators, and the Node.js backend.",
    )
    async def health_check() -> dict:
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
            "environment": settings.app_env,
        }

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Application instance (entry point for uvicorn)
# ─────────────────────────────────────────────────────────────────────────────

app = create_app()
