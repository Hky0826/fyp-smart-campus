"""
config.py
---------
Centralised configuration management using Pydantic Settings.

All values are loaded from environment variables (or the .env file).
This is the single source of truth for every configurable constant in the
AI service — no magic strings should appear elsewhere in the codebase.
"""

from __future__ import annotations

from typing import Any, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application-wide settings, loaded from environment variables.

    Priority order (highest → lowest):
      1. Actual environment variables
      2. Values in the .env file
      3. Field defaults defined here
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service Identity ────────────────────────────────────────────────────────
    app_name: str = "campus-ai-services"
    app_version: str = "1.0.0"
    app_env: str = "development"

    # ── Server ─────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Logging ────────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── CORS ───────────────────────────────────────────────────────────────────
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:3001"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        """Allow comma-separated string, JSON string, or list in env."""
        if isinstance(v, str):
            v_trimmed = v.strip()
            if v_trimmed.startswith("[") and v_trimmed.endswith("]"):
                import json
                try:
                    return json.loads(v_trimmed)
                except Exception:
                    pass
            return [origin.strip() for origin in v_trimmed.split(",") if origin.strip()]
        return v

    # ── Wall Detection Defaults ─────────────────────────────────────────────────
    # These must match the constants in frontend/src/constants/mapConstants.js:
    #   CANVAS_WIDTH = 800, CANVAS_HEIGHT = 600, GRID_SCALE = 8
    default_canvas_width: int = 800
    default_canvas_height: int = 600
    default_grid_scale: int = 8
    default_wall_sensitivity: int = 120  # Binary threshold value 0–255

    # ── AI Analysis Resolution ──────────────────────────────────────────────────
    # Images are resized to this resolution for analysis (aspect-ratio preserved)
    default_max_ai_width:  int = 1200
    default_max_ai_height: int = 900

    # ── OCR Detection Defaults ──────────────────────────────────────────────────
    default_min_ocr_confidence:   float = 0.60  # Minimum PaddleOCR confidence
    default_ocr_fragment_merge_px: int  = 40    # Max px gap for merging fragments

    # ── Room Detection Defaults ─────────────────────────────────────────────────
    default_min_room_area_px:   int   = 2000    # Minimum enclosed room area (px²)
    default_max_room_area_ratio: float = 0.30   # Max fraction of canvas a room may fill
    default_room_gap_close_px:  int   = 25      # Morphological closing kernel (px)
    default_min_confidence_score: float = 0.28  # Minimum room detection confidence

    # ── Node Generation Defaults ────────────────────────────────────────────────
    default_wall_clearance_px: int   = 8    # Min clearance from wall for node placement
    default_min_node_confidence: float = 0.30  # Soft threshold — flagged if below this
    default_dedup_threshold_px:  float = 50.0  # Same-label spatial cluster radius (px)

    # ── Debug Image Generation ──────────────────────────────────────────────────
    # Master switch. When False, NO debug images are written to disk regardless
    # of the debug_mode parameter sent by the client. Set to True in development.
    enable_debug_images: bool = False

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


# Singleton instance — import this throughout the application
settings = Settings()
