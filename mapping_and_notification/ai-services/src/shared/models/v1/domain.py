"""
shared/models/v1/domain.py
---------------------------
Versioned shared domain models (v1) for the Campus Navigation AI Pipeline.

These Pydantic models define the structured data objects that flow between
AI modules. Each module in the pipeline consumes the output of the previous
stage as one of these typed objects.

Domain Hierarchy:
  - Primitives: Point, BoundingBox, ImageMetadata
  - Intermediate Structures: Grid, Wall, WallGrid
  - Phase 1 Analysis: RoomPolygon, TextDetection, AiNode, FloorplanAnalysisResult
  - Envelopes: ProcessingResult metadata envelope
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Foundational Primitives
# ─────────────────────────────────────────────────────────────────────────────


class ImageMetadata(BaseModel):
    """Metadata describing a loaded floorplan image and its coordinate spaces."""

    original_width:  int
    original_height: int
    canvas_width:    int
    canvas_height:   int
    channels:        int   = 3
    format:          str   = "JPEG"
    aspect_ratio:    float

    # Legacy fields — ratio from original to 800×600 canvas (distorted, kept for compatibility)
    scale_x: float = Field(
        description="canvas_width / original_width (may differ from ai_uniform_scale)."
    )
    scale_y: float = Field(
        description="canvas_height / original_height (may differ from ai_uniform_scale)."
    )

    # AI Analysis space — aspect-ratio-preserved resize used during detection
    ai_width:         int   = Field(
        default=0,
        description="Width of the AI analysis image (aspect-ratio preserving)."
    )
    ai_height:        int   = Field(
        default=0,
        description="Height of the AI analysis image (aspect-ratio preserving)."
    )
    ai_uniform_scale: float = Field(
        default=1.0,
        description="Uniform scale applied to original for AI analysis: min(max_w/orig_w, max_h/orig_h)."
    )
    # Scale from AI space to canvas space — equals canvas_w/ai_w and canvas_h/ai_h
    canvas_scale_x: float = Field(
        default=1.0,
        description="Scale from AI-space X to canvas X: canvas_width / ai_width."
    )
    canvas_scale_y: float = Field(
        default=1.0,
        description="Scale from AI-space Y to canvas Y: canvas_height / ai_height."
    )


class Point(BaseModel):
    """A 2D point. Coordinates may be in AI space or canvas space depending on pipeline stage."""

    x: float
    y: float


class BoundingBox(BaseModel):
    """Axis-aligned bounding box in canvas pixel space."""

    x: float       # Top-left x
    y: float       # Top-left y
    width: float
    height: float


# ─────────────────────────────────────────────────────────────────────────────
# Intermediate Pipeline Structures
# ─────────────────────────────────────────────────────────────────────────────


class Grid(BaseModel):
    """Generic 2D integer grid representation."""

    data: List[List[int]]
    width: int
    height: int
    scale: int


class WallGrid(BaseModel):
    """
    2D binary grid produced by the Wall Detection module.
    0 = passable, 1 = wall. Indexed as grid[y][x].
    """

    grid: List[List[int]] = Field(
        description="2D list of 0 (passable) or 1 (wall). Indexed as grid[y][x]."
    )
    grid_width: int  = Field(description="Number of cells in the x direction.")
    grid_height: int = Field(description="Number of cells in the y direction.")
    canvas_width: int
    canvas_height: int
    grid_scale: int  = Field(description="Pixels per grid cell.")


class Wall(BaseModel):
    """A structural wall segment extracted from contours/lines."""

    start: Point
    end: Point
    thickness: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Room Detection Domain Models
# ─────────────────────────────────────────────────────────────────────────────


class RoomPolygon(BaseModel):
    """
    A detected room or enclosed space from the floorplan.

    Coordinates are in canvas pixel space (i.e., already scaled from the
    original image dimensions to the 800×600 virtual canvas).

    The polygon approximates the room boundary. Rooms with wall openings
    (entrances/doors) are still detected — the closing operation in the
    room detector temporarily bridges gaps before analysis.
    """

    id: str = Field(description="Stable identifier e.g. 'room_0', 'room_1'.")
    polygon: List[Point] = Field(
        description="Ordered list of polygon vertices approximating the room boundary."
    )
    centroid: Point = Field(description="Geometric centroid of the polygon.")
    area_px: float  = Field(description="Area of the detected region in canvas pixels².")
    bounding_rect: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0, description="Detection confidence score.")

    # Populated by the OCR association stage
    label: Optional[str]             = Field(default=None, description="OCR-detected room label, if any.")
    label_confidence: Optional[float] = Field(default=None, description="OCR text confidence.")
    label_center: Optional[Point]    = Field(default=None, description="Center of the OCR text bounding box.")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — OCR Domain Models
# ─────────────────────────────────────────────────────────────────────────────


class TextDetection(BaseModel):
    """
    A single text region detected by PaddleOCR, or a merged group of fragments.

    Coordinates are in AI space during processing; transformed to canvas space
    before being included in FloorplanAnalysisResult.
    """

    text: str
    bbox: List[Point] = Field(
        description="4-point polygon bounding box from PaddleOCR (TL, TR, BR, BL)."
    )
    center: Point
    confidence: float = Field(ge=0.0, le=1.0)

    # Set by OcrFragmentMerger
    id: Optional[str] = Field(
        default=None,
        description="Stable identifier assigned during merging (e.g. 'merged_0'). "
                    "Used by AiNode.source_text_id for cross-referencing."
    )
    fragment_count: int = Field(
        default=1,
        description="Number of raw OCR fragments merged into this detection. "
                    "1 = single unmerged fragment."
    )

    # Populated by the association stage
    associated_room_id: Optional[str] = Field(
        default=None,
        description="ID of the RoomPolygon this text was assigned to, if any."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Node Generation Domain Models
# ─────────────────────────────────────────────────────────────────────────────


class AiNodeSource(str, Enum):
    """Origin of an AI-generated node — controls how it was detected."""
    OCR_PRIMARY        = "ocr_primary"         # Primary: node generated directly from OCR label
    ROOM_DETECTION_OCR = "room_detection+ocr"  # Room polygon confirmed + OCR label assigned
    ROOM_DETECTION     = "room_detection"       # Room polygon only — no OCR label (Unknown Room)


class AiReviewStatus(str, Enum):
    """Admin review status for AI-generated nodes."""
    PENDING  = "PENDING"   # Freshly generated by AI
    MODIFIED = "MODIFIED"  # Admin moved it or changed properties
    APPROVED = "APPROVED"  # Admin explicitly approved it
    FLAGGED  = "FLAGGED"   # AI flagged node due to soft validation failures


class AiNode(BaseModel):
    """
    An automatically generated navigation node from Phase 1 analysis.

    This model represents a candidate room node before it is saved to MySQL.
    It is consumed by the React/Konva frontend for display and admin review.

    Coordinate System:
        x, y are in canvas pixel space (0..800, 0..600) — directly usable
        by the existing Konva stage and the pathfinding.js wall grid.
    """

    temp_id: str = Field(
        description="Temporary client-side identifier. Not a DB node_id."
    )
    node_type: str     = Field(default="ROOM")
    room_label: str    = Field(description="Room name from OCR or 'Unknown Room'.")
    x: float           = Field(description="Canvas x coordinate (0..canvas_width).")
    y: float           = Field(description="Canvas y coordinate (0..canvas_height).")

    # AI metadata (passed through to frontend for review UI)
    ai_generated: bool        = True
    ai_confidence: float      = Field(ge=0.0, le=1.0)
    ai_source: AiNodeSource

    # Source cross-references — at most one will be set depending on ai_source
    source_room_id: Optional[str] = Field(
        default=None,
        description="ID of the originating RoomPolygon (room_detection / room_detection+ocr nodes)."
    )
    source_text_id: Optional[str] = Field(
        default=None,
        description="ID of the merged TextDetection (ocr_primary nodes)."
    )

    review_status: AiReviewStatus = AiReviewStatus.PENDING

    # RBAC — always empty from AI. Admin assigns permissions after review.
    allowed_roles: List[int]   = Field(default_factory=list)
    is_accessible: str         = "ALLOW"
    node_id: None              = None  # Not in DB yet


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Full Analysis Result
# ─────────────────────────────────────────────────────────────────────────────


class AnalysisSummary(BaseModel):
    """Summary statistics for a completed floorplan analysis."""
    rooms_detected: int
    rooms_with_labels: int
    rooms_without_labels: int
    nodes_generated: int
    nodes_from_ocr: int            = Field(default=0, description="Nodes generated via OCR_PRIMARY.")
    nodes_from_room_detection: int = Field(default=0, description="Gap-fill nodes from room detection.")
    nodes_flagged: int             = Field(default=0, description="Nodes failing soft validation checks.")
    texts_detected: int
    texts_after_merge: int         = Field(default=0, description="Merged fragment count after OcrFragmentMerger.")


class FloorplanAnalysisResult(BaseModel):
    """
    Complete Phase 1 analysis result returned by POST /api/v1/analyze/floorplan.

    All node x/y coordinates are in 800×600 frontend canvas space — directly
    usable by the Konva stage. Room polygon and text coordinates are also
    transformed to canvas space before being included here.

    The frontend receives this and uses it to:
      1. Display AI-generated room nodes on the Konva canvas (already in canvas space).
      2. Show the admin a review panel for each node.
      3. Allow the admin to modify/approve nodes before saving via POST /api/map-data.
    """

    status: str = "success"
    processing_time_ms: float
    pipeline_stages_completed: int = 10  # 1A–1J in Phase 1.5.1 pipeline

    image: ImageMetadata
    wall_grid: WallGrid
    rooms: List[RoomPolygon]
    text_detections: List[TextDetection]
    nodes: List[AiNode]
    summary: AnalysisSummary

    # Populated when debug_mode=True in the API request
    debug_image_paths: Optional[Dict[str, str]] = Field(
        default=None,
        description="Paths to debug images saved by DebugImageWriter when debug_mode=True."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Standardized API Response Envelope (unchanged)
# ─────────────────────────────────────────────────────────────────────────────


class ProcessingResult(BaseModel):
    """
    Standardized API metadata envelope returned by all AI endpoints.
    Encapsulates status, timing, algorithm versioning, and payload data.
    """

    status: str = "success"
    version: str = "1.0.0"
    algorithm: str
    processing_time_ms: float
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    data: Dict[str, Any] = Field(default_factory=dict)
