"""
utils/coord_transform.py
------------------------
CoordinateTransformer — the single authoritative coordinate transformation
implementation for the Campus Navigation AI Pipeline.

Three coordinate spaces exist in the pipeline:

  1. ORIGINAL space  — pixel coordinates in the original uploaded image.

  2. AI space        — pixel coordinates in the aspect-ratio-preserved analysis
                       image produced by ImagePreprocessorService.
                       Uses a SINGLE uniform scale factor so morphological
                       operations, distance measurements, and area calculations
                       are not distorted by independent X/Y stretching.

  3. CANVAS space    — pixel coordinates in the 800×600 Konva canvas.
                       The frontend renders the floorplan image stretched to
                       fill the entire 800×600 stage via:
                           <KonvaImage width={800} height={600} />
                       Canvas coordinates therefore use independent X/Y scale
                       factors that match this frontend rendering exactly.

All AI detection (wall, room, OCR, nodes) runs in AI space.
Only final output coordinates are transformed to canvas space.

MATH:
  AI-space was produced by: ai_scale = min(max_w/orig_w, max_h/orig_h)
  So: orig_x = ai_x / ai_scale  (same for y)

  Canvas uses independent scales matching the frontend stretch:
    canvas_x = orig_x * (canvas_width  / orig_width)
    canvas_y = orig_y * (canvas_height / orig_height)

  Combining:
    canvas_x = ai_x * (canvas_width  / ai_width)
    canvas_y = ai_y * (canvas_height / ai_height)

This is the ONLY module that calculates coordinate transforms.
No other module should independently compute canvas scaling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from src.shared.models.v1.domain import AiNode, BoundingBox, Point, RoomPolygon, TextDetection


@dataclass(frozen=True)
class CoordinateTransformer:
    """
    Transforms coordinates between AI analysis space and frontend canvas space.

    Args:
        original_width:   Width of the original uploaded image in pixels.
        original_height:  Height of the original uploaded image in pixels.
        ai_width:         Width of the AI analysis image (aspect-ratio preserved).
        ai_height:        Height of the AI analysis image (aspect-ratio preserved).
        canvas_width:     Frontend canvas width (default 800).
        canvas_height:    Frontend canvas height (default 600).
    """

    original_width:  int
    original_height: int
    ai_width:        int
    ai_height:       int
    canvas_width:    int = 800
    canvas_height:   int = 600

    @property
    def canvas_scale_x(self) -> float:
        """Scale factor from AI-space X to canvas X."""
        return self.canvas_width / self.ai_width

    @property
    def canvas_scale_y(self) -> float:
        """Scale factor from AI-space Y to canvas Y."""
        return self.canvas_height / self.ai_height

    # ── Point Transforms ──────────────────────────────────────────────────────

    def ai_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        """Transform a single (x, y) point from AI space to canvas space."""
        return (
            round(x * self.canvas_scale_x, 2),
            round(y * self.canvas_scale_y, 2),
        )

    def canvas_to_ai(self, fx: float, fy: float) -> Tuple[float, float]:
        """Transform a single (fx, fy) point from canvas space to AI space."""
        return (
            fx / self.canvas_scale_x,
            fy / self.canvas_scale_y,
        )

    def transform_point(self, p: Point) -> Point:
        """Transform a Point object from AI space to canvas space."""
        cx, cy = self.ai_to_canvas(p.x, p.y)
        return Point(x=cx, y=cy)

    # ── Composite Object Transforms ───────────────────────────────────────────

    def transform_bbox(self, bbox: BoundingBox) -> BoundingBox:
        """Transform a BoundingBox from AI space to canvas space."""
        cx, cy = self.ai_to_canvas(bbox.x, bbox.y)
        cw = round(bbox.width  * self.canvas_scale_x, 2)
        ch = round(bbox.height * self.canvas_scale_y, 2)
        return BoundingBox(x=cx, y=cy, width=cw, height=ch)

    def transform_room(self, room: RoomPolygon) -> RoomPolygon:
        """
        Transform all coordinates in a RoomPolygon from AI space to canvas space.
        Returns a new RoomPolygon; the original is not modified.
        """
        canvas_polygon  = [self.transform_point(p) for p in room.polygon]
        canvas_centroid = self.transform_point(room.centroid)
        canvas_bbox     = self.transform_bbox(room.bounding_rect)
        canvas_area     = round(
            room.area_px * self.canvas_scale_x * self.canvas_scale_y, 2
        )
        label_center = (
            self.transform_point(room.label_center)
            if room.label_center is not None
            else None
        )
        return room.model_copy(update={
            "polygon":      canvas_polygon,
            "centroid":     canvas_centroid,
            "bounding_rect": canvas_bbox,
            "area_px":      canvas_area,
            "label_center": label_center,
        })

    def transform_text(self, text: TextDetection) -> TextDetection:
        """Transform a TextDetection bbox and center from AI space to canvas space."""
        canvas_bbox   = [self.transform_point(p) for p in text.bbox]
        canvas_center = self.transform_point(text.center)
        return text.model_copy(update={
            "bbox":   canvas_bbox,
            "center": canvas_center,
        })

    def transform_node(self, node: AiNode) -> AiNode:
        """Transform an AiNode position from AI space to canvas space."""
        cx, cy = self.ai_to_canvas(node.x, node.y)
        return node.model_copy(update={"x": cx, "y": cy})

    # ── Batch Transforms ──────────────────────────────────────────────────────

    def transform_rooms(self, rooms: List[RoomPolygon]) -> List[RoomPolygon]:
        return [self.transform_room(r) for r in rooms]

    def transform_texts(self, texts: List[TextDetection]) -> List[TextDetection]:
        return [self.transform_text(t) for t in texts]

    def transform_nodes(self, nodes: List[AiNode]) -> List[AiNode]:
        return [self.transform_node(n) for n in nodes]
