"""
api/v1/wall_detection.py
------------------------
Route handler for POST /api/v1/wall-detection.

This module is intentionally thin — it:
  1. Parses the multipart/form-data request (image file + optional params).
  2. Delegates processing to WallDetector.
  3. Maps the DetectionResult to the WallDetectionResponse schema.
  4. Handles all errors with consistent HTTP status codes.

No business logic lives here. All CV processing is in modules/wall_detection/.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status


from src.shared.models.v1.domain import ProcessingResult
from src.modules.wall_detection.detector import WallDetector
from src.modules.wall_detection.schemas import ErrorResponse, WallDetectionResponse
from src.utils.image_loader import ImageLoadError
from src.utils.logging_config import get_logger

logger   = get_logger(__name__)
router   = APIRouter()
detector = WallDetector()  # Stateless — safe to instantiate at module level


@router.post(
    "",
    response_model=ProcessingResult,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image or parameters"},
        422: {"description": "Validation error (Pydantic)"},
        500: {"model": ErrorResponse, "description": "Internal processing error"},
    },
    summary="Detect structural walls in a floorplan image",
    description=(
        "Upload a floorplan image and receive a binary wall grid compatible "
        "with the frontend A* pathfinding algorithm (findAStarPath in pathfinding.js). "
        "The grid is a 2D list of 0 (passable) / 1 (wall), indexed as grid[y][x]."
    ),
)
async def detect_walls(
    file: UploadFile = File(
        ...,
        description="Floorplan image file (JPEG, PNG, or WEBP).",
    ),
    sensitivity: int = Form(
        default=120,
        ge=0,
        le=255,
        description=(
            "Binary threshold value 0–255. Higher = fewer walls detected. "
            "Default 120 matches the wallSensitivity default in useOpenCV.js."
        ),
    ),
    canvas_width: int = Form(
        default=800,
        gt=0,
        description="Virtual canvas width in pixels. Default: 800 (CANVAS_WIDTH in mapConstants.js).",
    ),
    canvas_height: int = Form(
        default=600,
        gt=0,
        description="Virtual canvas height in pixels. Default: 600 (CANVAS_HEIGHT in mapConstants.js).",
    ),
    grid_scale: int = Form(
        default=8,
        gt=0,
        description="Pixels per grid cell. Default: 8 (GRID_SCALE in mapConstants.js). Produces 100×75 grid.",
    ),
) -> WallDetectionResponse:
    """
    Detect structural walls in a floorplan image.

    Accepts a multipart/form-data POST with the image file and optional
    detection parameters. Returns the wall grid in a format directly
    compatible with the React frontend's pathfinding utilities.
    """
    # ── Validate file type ─────────────────────────────────────────────────────
    if file.content_type and file.content_type not in (
        "image/jpeg", "image/png", "image/webp", "image/bmp",
        "application/octet-stream",  # Some HTTP clients omit content-type
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}. Use JPEG, PNG, or WEBP.",
        )

    logger.info(
        "Wall detection request received",
        filename=file.filename,
        content_type=file.content_type,
        sensitivity=sensitivity,
        canvas=f"{canvas_width}x{canvas_height}",
        grid_scale=grid_scale,
    )

    # ── Read file bytes ────────────────────────────────────────────────────────
    try:
        image_bytes = await file.read()
    except Exception as exc:
        logger.error("Failed to read uploaded file", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {exc}",
        ) from exc

    if len(image_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # ── Run wall detection ─────────────────────────────────────────────────────
    try:
        result = detector.detect(
            image_bytes=image_bytes,
            sensitivity=sensitivity,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            grid_scale=grid_scale,
        )
    except ImageLoadError as exc:
        logger.warning("Image load failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image processing error: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("Wall detection failed unexpectedly", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal wall detection error. See server logs.",
        ) from exc

    # ── Build response ─────────────────────────────────────────────────────────
    response_data = WallDetectionResponse(
        status="success",
        grid=result.wall_grid.grid,
        grid_width=result.wall_grid.grid_width,
        grid_height=result.wall_grid.grid_height,
        canvas_width=result.wall_grid.canvas_width,
        canvas_height=result.wall_grid.canvas_height,
        grid_scale=result.wall_grid.grid_scale,
        sensitivity_used=result.sensitivity_used,
        processing_time_ms=result.processing_time_ms,
        wall_cell_count=result.wall_cell_count,
        total_cells=result.total_cells,
        wall_ratio=result.wall_ratio,
    )

    return ProcessingResult(
        status="success",
        version="1.0.0",
        algorithm="opencv-threshold-v1",
        processing_time_ms=result.processing_time_ms,
        data=response_data.model_dump()
    )
