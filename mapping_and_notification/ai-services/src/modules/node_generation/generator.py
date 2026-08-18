"""
node_generation/generator.py
-----------------------------
NodeGenerator — generates AiNode objects from detected room polygons.

Improvements over the original implementation:
  - Uses OpenCV distance transform to find the safest interior position
    (point with maximum clearance from all walls), rather than grid sampling.
  - Works in AI analysis space (ai_width × ai_height), not 800×600 canvas.
  - Detailed per-node logging for debugging.

For each validated RoomPolygon:
  1. Validate that the room centroid is not on a wall (with clearance).
  2. If invalid, use distance transform to find the maximum-clearance position
     inside the polygon — this is more robust than random grid sampling,
     especially for L-shaped and irregular rooms.
  3. Assign the room label from OCR (or 'Unknown Room').
  4. Compute combined confidence from room detection + OCR confidence.
  5. Return an AiNode in AI analysis space.

Node coordinates are later transformed to 800×600 canvas space by
CoordinateTransformer in FloorplanAnalyzerService.

Coordinate System:
  All input and output coordinates are in AI analysis space.
  Do NOT apply canvas scaling here.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

from src.shared.models.v1.domain import (
    AiNode,
    AiNodeSource,
    AiReviewStatus,
    Point,
    RoomPolygon,
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_WALL_CLEARANCE_PX = 8


class NodeGenerator:
    """
    Stateless node generator — converts RoomPolygon list to AiNode list.

    Usage:
        generator = NodeGenerator()
        nodes = generator.generate(
            rooms=rooms,
            wall_mask=wall_result.wall_mask,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
        )
    """

    def generate(
        self,
        rooms:             List[RoomPolygon],
        wall_mask:         Optional[np.ndarray],
        ai_width:          int   = 800,
        ai_height:         int   = 600,
        wall_clearance_px: int   = DEFAULT_WALL_CLEARANCE_PX,
    ) -> List[AiNode]:
        """
        Generate one AiNode per RoomPolygon.

        Args:
            rooms:             RoomPolygon list (coordinates in AI space).
            wall_mask:         Binary wall mask at AI resolution (255=wall, 0=space).
                               May be None — centroid used directly without validation.
            ai_width:          AI analysis image width.
            ai_height:         AI analysis image height.
            wall_clearance_px: Min clearance from wall pixels for a valid position.

        Returns:
            List of AiNode objects (coordinates in AI space, transformed later).
        """
        # Pre-compute distance transform once for all rooms (expensive operation)
        dist_transform: Optional[np.ndarray] = None
        if wall_mask is not None:
            # Distance transform: each pixel = distance to nearest wall pixel.
            # inverted_mask = 255 where space (not wall).
            inverted = cv2.bitwise_not(wall_mask)
            dist_transform = cv2.distanceTransform(inverted, cv2.DIST_L2, 5)

        nodes: List[AiNode] = []
        for i, room in enumerate(rooms):
            node = self._generate_node_for_room(
                room=room,
                node_index=i,
                wall_mask=wall_mask,
                dist_transform=dist_transform,
                ai_width=ai_width,
                ai_height=ai_height,
                wall_clearance_px=wall_clearance_px,
            )
            nodes.append(node)

        labeled   = sum(1 for n in nodes if n.room_label != "Unknown Room")
        unlabeled = len(nodes) - labeled
        invalid   = sum(1 for n in nodes if n.ai_source == AiNodeSource.ROOM_DETECTION
                        and n.ai_confidence < 0.5)

        logger.info(
            "Stage 1F: node generation completed",
            nodes_generated=len(nodes),
            labeled=labeled,
            unlabeled=unlabeled,
            low_confidence=invalid,
        )
        return nodes

    def _generate_node_for_room(
        self,
        room:             RoomPolygon,
        node_index:       int,
        wall_mask:        Optional[np.ndarray],
        dist_transform:   Optional[np.ndarray],
        ai_width:         int,
        ai_height:        int,
        wall_clearance_px: int,
    ) -> AiNode:
        """Generate a single AiNode for one RoomPolygon (in AI space)."""

        room_label = room.label if room.label else "Unknown Room"
        has_label  = room.label is not None
        label_conf = room.label_confidence if room.label_confidence is not None else 0.0

        # Find safe interior node position
        node_x, node_y = self._find_valid_position(
            room=room,
            wall_mask=wall_mask,
            dist_transform=dist_transform,
            ai_width=ai_width,
            ai_height=ai_height,
            wall_clearance_px=wall_clearance_px,
        )

        # Combined confidence
        if has_label:
            combined_confidence = round(0.60 * room.confidence + 0.40 * label_conf, 4)
            source = AiNodeSource.ROOM_DETECTION_OCR
        else:
            combined_confidence = round(room.confidence * 0.85, 4)
            source = AiNodeSource.ROOM_DETECTION

        temp_id = f"ai_room_{node_index}"

        logger.debug(
            "Node generated (AI space)",
            temp_id=temp_id,
            label=room_label,
            x=round(node_x, 1),
            y=round(node_y, 1),
            confidence=combined_confidence,
            source=source.value,
        )

        return AiNode(
            temp_id=temp_id,
            node_type="ROOM",
            room_label=room_label,
            x=round(node_x, 2),
            y=round(node_y, 2),
            ai_confidence=combined_confidence,
            ai_source=source,
            source_room_id=room.id,
            review_status=AiReviewStatus.PENDING,
            allowed_roles=[],
            is_accessible="ALLOW",
        )

    def _find_valid_position(
        self,
        room:             RoomPolygon,
        wall_mask:        Optional[np.ndarray],
        dist_transform:   Optional[np.ndarray],
        ai_width:         int,
        ai_height:        int,
        wall_clearance_px: int,
    ) -> Tuple[float, float]:
        """
        Find the safest interior node position for a room using distance transform.

        Strategy:
          1. Try the polygon centroid first (fast path).
          2. If centroid is on a wall or too close, use distance transform
             to find the point with maximum clearance from walls within the polygon.
             This is the 'largest inscribed circle centre' approximation.
          3. Last resort: raw centroid with a warning.
        """
        cx = max(0.0, min(float(room.centroid.x), float(ai_width  - 1)))
        cy = max(0.0, min(float(room.centroid.y), float(ai_height - 1)))

        # No wall mask — return centroid directly
        if wall_mask is None or dist_transform is None:
            return cx, cy

        # Fast path: centroid has sufficient clearance
        if self._clearance_at(cx, cy, dist_transform) >= wall_clearance_px:
            return cx, cy

        logger.debug(
            "Centroid has insufficient wall clearance — using distance transform fallback",
            room_id=room.id,
            centroid=(round(cx, 1), round(cy, 1)),
        )

        # Build polygon contour for point-in-polygon masking
        contour = np.array(
            [[int(p.x), int(p.y)] for p in room.polygon], dtype=np.int32
        ).reshape((-1, 1, 2))

        # Create a mask of pixels inside this room polygon at AI resolution
        poly_mask = np.zeros((ai_height, ai_width), dtype=np.uint8)
        cv2.fillPoly(poly_mask, [contour], 255)

        # Mask the distance transform to only consider pixels inside the polygon
        masked_dist = dist_transform.copy()
        masked_dist[poly_mask == 0] = 0

        # Also zero out pixels below the required clearance
        masked_dist[masked_dist < wall_clearance_px] = 0

        if masked_dist.max() > 0:
            # Find the pixel with maximum distance-from-wall inside the polygon
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(masked_dist)
            best_x, best_y = float(max_loc[0]), float(max_loc[1])
            logger.debug(
                "Distance-transform fallback found valid position",
                room_id=room.id,
                position=(round(best_x, 1), round(best_y, 1)),
                clearance=round(float(max_val), 1),
            )
            return best_x, best_y

        # Last resort
        logger.warning(
            "No valid interior position found — using raw centroid. "
            "Admin should review this node.",
            room_id=room.id,
            centroid=(round(cx, 1), round(cy, 1)),
        )
        return cx, cy

    @staticmethod
    def _clearance_at(
        x: float, y: float, dist_transform: np.ndarray
    ) -> float:
        """Return the distance-transform value at (x, y) — i.e., clearance from nearest wall."""
        h, w = dist_transform.shape[:2]
        ix, iy = int(round(x)), int(round(y))
        if ix < 0 or ix >= w or iy < 0 or iy >= h:
            return 0.0
        return float(dist_transform[iy, ix])
