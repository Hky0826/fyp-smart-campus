"""
api/router.py
-------------
Master APIRouter that aggregates all v1 module routers.

To add a new AI module:
  1. Implement the module in src/modules/<module_name>/
  2. Create the route file in src/api/v1/<module_name>.py
  3. Import and include it here with the correct prefix.

No other file needs to be modified.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.v1 import (
    wall_detection,
    floorplan_analyzer,
)

api_router = APIRouter(prefix="/api/v1")

# ── Phase 1 — Wall Detection (existing, unchanged) ─────────────────────────────
api_router.include_router(
    wall_detection.router,
    prefix="/wall-detection",
    tags=["Wall Detection"],
)

# ── Phase 1 — Floorplan Analysis (new) ─────────────────────────────────────────
# POST /api/v1/analyze/floorplan
# Runs the full Phase 1 pipeline: Wall → Room → OCR → Node Generation
api_router.include_router(
    floorplan_analyzer.router,
    prefix="/analyze/floorplan",
    tags=["Floorplan Analysis"],
)
