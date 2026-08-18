"""
api/v1/floorplan_analyzer.py
-----------------------------
Route handler for POST /api/v1/analyze/floorplan

This endpoint accepts a multipart/form-data POST with a floorplan image and
optional tuning parameters, runs the Phase 1 AI analysis pipeline, and
returns the FloorplanAnalysisResult JSON.

The handler is intentionally thin:
  - Validates the uploaded file
  - Passes parameters to FloorplanAnalyzerService
  - Returns the result or an appropriate HTTP error

No analysis logic lives here. All processing is in services/floorplan_analyzer.py.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from src.services.floorplan_analyzer import FloorplanAnalyzerService
from src.shared.models.v1.domain import FloorplanAnalysisResult
from src.modules.wall_detection.schemas import ErrorResponse
from src.utils.image_loader import ImageLoadError
from src.utils.logging_config import get_logger

logger   = get_logger(__name__)
router   = APIRouter()

# The service is instantiated once at module level — this is important because
# PaddleOCR lazy-initializes on first use and we want that to happen once,
# not per request. FastAPI handles the async context safely for this pattern.
_analyzer = FloorplanAnalyzerService()


@router.post(
    "",
    response_model=FloorplanAnalysisResult,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid image or parameters"},
        422: {"description": "Parameter validation error"},
        500: {"model": ErrorResponse, "description": "Internal processing error"},
    },
    summary="Analyze a floorplan and generate room nodes automatically",
    description=(
        "Upload a floorplan image and receive automatically generated room nodes "
        "with detected room labels. Runs the improved Phase 1 pipeline: "
        "Preprocessing (aspect-ratio-preserved) → Wall Detection → Room Detection → "
        "OCR → Node Generation (distance-transform safe positioning) → "
        "Coordinate Transformation to 800×600 canvas space. "
        "Pass debug_mode=true to save intermediate images to ai-services/debug_output/."
    ),
)
async def analyze_floorplan(
    file: UploadFile = File(
        ...,
        description="Floorplan image file (JPEG, PNG, WEBP, or BMP).",
    ),
    canvas_width: int = Form(
        default=800,
        gt=0,
        description="Virtual canvas width in pixels. Must match CANVAS_WIDTH in mapConstants.js.",
    ),
    canvas_height: int = Form(
        default=600,
        gt=0,
        description="Virtual canvas height in pixels. Must match CANVAS_HEIGHT in mapConstants.js.",
    ),
    sensitivity: int = Form(
        default=120,
        ge=0,
        le=255,
        description="Wall detection threshold (0–255). Higher = fewer walls detected.",
    ),
    grid_scale: int = Form(
        default=8,
        gt=0,
        description="Pixels per wall grid cell. Must match GRID_SCALE in mapConstants.js.",
    ),
    room_gap_close_px: int = Form(
        default=25,
        ge=5,
        le=100,
        description=(
            "Morphological closing kernel size (pixels). Controls how large a wall gap "
            "can be and still have the room detected. Increase for wider door openings."
        ),
    ),
    min_room_area_px: int = Form(
        default=2000,
        ge=100,
        description="Minimum room area in canvas pixels². Regions smaller than this are rejected as noise.",
    ),
    max_room_area_ratio: float = Form(
        default=0.30,
        ge=0.01,
        le=0.95,
        description="Maximum fraction of canvas area a room may occupy. Larger regions are treated as background.",
    ),
    min_ocr_confidence: float = Form(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Minimum PaddleOCR confidence threshold (0.0–1.0).",
    ),
    wall_clearance_px: int = Form(
        default=8,
        ge=0,
        le=50,
        description="Minimum clearance from wall pixels for generated node positions.",
    ),
    # ── New parameters (Phase 1 improvements) ─────────────────────────────────
    max_ai_width: int = Form(
        default=1200,
        gt=0,
        description=(
            "Maximum AI analysis image width. The image is resized with uniform "
            "scale to this width (or height) while preserving aspect ratio. "
            "Higher = better detection but slower. Default 1200."
        ),
    ),
    max_ai_height: int = Form(
        default=900,
        gt=0,
        description="Maximum AI analysis image height (aspect-ratio preserved). Default 900.",
    ),
    min_confidence_score: float = Form(
        default=0.28,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum room detection confidence score (0.0–1.0). "
            "Rooms below this threshold are rejected regardless of area. Default 0.28."
        ),
    ),
    debug_mode: bool = Form(
        default=False,
        description=(
            "When true, saves 12 intermediate analysis images to "
            "ai-services/debug_output/{analysis_id}/. Useful for diagnosing "
            "room detection failures on specific floorplans."
        ),
    ),
) -> FloorplanAnalysisResult:
    """
    Run the Phase 1 floorplan analysis pipeline and return AI-generated room nodes.
    """

    # ── Validate file type ─────────────────────────────────────────────────────
    allowed_types = (
        "image/jpeg", "image/png", "image/webp", "image/bmp",
        "application/octet-stream",  # Some clients omit content-type
    )
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file.content_type}. Use JPEG, PNG, WEBP, or BMP.",
        )

    logger.info(
        "Floorplan analysis request received",
        filename=file.filename,
        content_type=file.content_type,
        canvas=f"{canvas_width}×{canvas_height}",
        sensitivity=sensitivity,
        room_gap_close_px=room_gap_close_px,
        min_room_area_px=min_room_area_px,
        max_ai_width=max_ai_width,
        max_ai_height=max_ai_height,
        debug_mode=debug_mode,
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

    # ── Run analysis pipeline ──────────────────────────────────────────────────
    try:
        result = _analyzer.analyze(
            image_bytes=image_bytes,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            sensitivity=sensitivity,
            grid_scale=grid_scale,
            room_gap_close_px=room_gap_close_px,
            min_room_area_px=min_room_area_px,
            max_room_area_ratio=max_room_area_ratio,
            min_ocr_confidence=min_ocr_confidence,
            wall_clearance_px=wall_clearance_px,
            max_ai_width=max_ai_width,
            max_ai_height=max_ai_height,
            debug_mode=debug_mode,
            debug_prefix=f"fp_{file.filename or 'unknown'}",
        )
    except ImageLoadError as exc:
        logger.warning("Image load failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image processing error: {exc}",
        ) from exc
    except Exception as exc:
        logger.error(
            "Floorplan analysis failed unexpectedly",
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal analysis error. See server logs for details.",
        ) from exc

    return result
