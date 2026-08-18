"""
logging_config.py
-----------------
Configures structured logging using Python's stdlib `logging` module,
augmented with `structlog` for consistent JSON output in production
and human-readable coloured output during development.

Usage:
    from src.utils.logging_config import get_logger

    logger = get_logger(__name__)
    logger.info("Wall detection started", sensitivity=120, canvas_width=800)
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(log_level: str = "INFO", is_development: bool = True) -> None:
    """
    Configure structlog and stdlib logging.

    Args:
        log_level:      Logging level string ("DEBUG", "INFO", "WARNING", "ERROR").
        is_development: If True, use coloured console renderer; otherwise JSON renderer.
    """
    log_level_int = getattr(logging, log_level.upper(), logging.INFO)

    # ── stdlib root logger ─────────────────────────────────────────────────────
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level_int,
    )

    # Suppress noisy third-party loggers in production
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # ── structlog shared processors ────────────────────────────────────────────
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if is_development:
        # Pretty coloured output for local development
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # JSON output for production log aggregation
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level_int)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Returns a named structlog logger bound to the given module name.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A bound structlog logger instance.
    """
    return structlog.get_logger(name)
