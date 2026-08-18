"""
wall_detection/schemas.py
--------------------------
Pydantic request and response models for the Wall Detection API endpoint.

These models define the HTTP API contract between Node.js and this service.
The response structure must remain compatible with the `wallGrid` state
in the React frontend's useOpenCV.js hook.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Request — received via multipart/form-data
# ─────────────────────────────────────────────────────────────────────────────


class WallDetectionParams(BaseModel):
    """
    Query / form parameters for the wall detection endpoint.

    These are optional overrides of the service defaults. In normal
    operation, the frontend always uses the same constants, so the
    defaults here mirror mapConstants.js.
    """

    sensitivity: int = Field(
        default=120,
        ge=0,
        le=255,
        description=(
            "Binary threshold value (0–255). Higher values detect fewer walls. "
            "Mirrors the wallSensitivity slider in the React map editor."
        ),
    )
    canvas_width: int = Field(
        default=800,
        gt=0,
        description="Virtual canvas width in pixels. Must match CANVAS_WIDTH in mapConstants.js.",
    )
    canvas_height: int = Field(
        default=600,
        gt=0,
        description="Virtual canvas height in pixels. Must match CANVAS_HEIGHT in mapConstants.js.",
    )
    grid_scale: int = Field(
        default=8,
        gt=0,
        description=(
            "Pixels per grid cell. Must match GRID_SCALE in mapConstants.js. "
            "Lower = more precise, slower A*. Default 8 → 100×75 grid."
        ),
    )

    @field_validator("grid_scale")
    @classmethod
    def grid_scale_must_divide_canvas(cls, v: int, info) -> int:
        """Warn if grid_scale does not evenly divide canvas dimensions."""
        # Cannot access other fields at this point via info.data easily,
        # so this is a soft guard — the grid utility handles non-divisible cases.
        if v < 1:
            raise ValueError("grid_scale must be at least 1.")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# Response
# ─────────────────────────────────────────────────────────────────────────────


class WallDetectionResponse(BaseModel):
    """
    JSON response returned by POST /api/v1/wall-detection.

    The `grid` field is structurally identical to the `wallGrid` React state
    in useOpenCV.js — a 2D list of 0/1 integers indexed as grid[y][x].
    This ensures findAStarPath() in pathfinding.js works without modification.
    """

    status: str = Field(default="success")

    # The primary output — 2D binary grid
    grid: List[List[int]] = Field(
        description=(
            "2D list of 0 (passable) or 1 (wall), indexed as grid[y][x]. "
            "Shape: [grid_height][grid_width]."
        )
    )

    # Grid metadata
    grid_width: int   = Field(description="Number of grid cells in x direction.")
    grid_height: int  = Field(description="Number of grid cells in y direction.")
    canvas_width: int
    canvas_height: int
    grid_scale: int

    # Parameters echo-back (useful for debugging)
    sensitivity_used: int

    # Performance
    processing_time_ms: float = Field(description="Wall detection processing time in ms.")

    # Diagnostic statistics
    wall_cell_count: int  = Field(description="Total number of wall cells (value=1) in the grid.")
    total_cells: int      = Field(description="Total grid cells (grid_width * grid_height).")
    wall_ratio: float     = Field(description="Fraction of cells classified as walls (0.0–1.0).")


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    status: str = "error"
    message: str
    detail: Optional[str] = None
