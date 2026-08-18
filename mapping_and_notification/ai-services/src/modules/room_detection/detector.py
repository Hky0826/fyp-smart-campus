"""
room_detection/detector.py
--------------------------
RoomDetector — detects individual rooms from a pre-processed room_view image.

Now accepts the room_view from ImagePreprocessorService (already inverted and
gap-closed) rather than a raw wall_mask. This separates preprocessing concerns
from detection logic and allows the preprocessor to tune the gap-closing
separately from room scoring.

Algorithm:
  1. Run Connected Component Analysis (CCA) on the room_view
     (255=walkable space, 0=wall — already gap-closed by preprocessor)
  2. For every candidate component, compute multi-criteria scores
  3. Reject candidates outside configurable area bounds
  4. Reject candidates below min_confidence_score
  5. For each accepted component, extract the contour polygon and centroid
  6. Return ordered list of RoomPolygon objects

Multi-Criteria Scoring (replaces single area threshold):
  - rectangularity:  how rectangular the room is (area / bounding rect area)
  - convexity:       area / convex hull area (rooms are generally convex)
  - compactness:     4π·area / perimeter² (penalises very elongated shapes)
  - size_score:      normalised area within the valid range (not too small, not exterior)
  Combined confidence = weighted sum of the four scores.

Detailed Diagnostics:
  Every candidate's rejection reason is logged individually, so you can
  diagnose room detection failures by inspecting the logs rather than guessing.

Coordinate System:
  Input:  room_view at AI analysis resolution (ai_width × ai_height).
  Output: RoomPolygon coordinates in AI analysis space.
  Use CoordinateTransformer to convert to frontend 800×600 canvas space.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

from src.shared.models.v1.domain import BoundingBox, Point, RoomPolygon
from src.utils.debug_images import DebugImageWriter
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Default Thresholds — all configurable per-request
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MIN_ROOM_AREA_PX    = 1500   # Lower than before; relying on scoring too
DEFAULT_MAX_ROOM_AREA_RATIO = 0.35   # Slightly more permissive than before
DEFAULT_MIN_CONFIDENCE      = 0.28   # Minimum combined confidence score to keep


@dataclass
class _CandidateResult:
    """Internal result for one CCA component during filtering."""
    label_id:    int
    area:        int
    x: int; y: int; w: int; h: int
    accepted:    bool
    reject_reason: Optional[str]
    confidence:  float = 0.0


class RoomDetector:
    """
    Stateless room detector — finds enclosed room regions from a room_view image.

    Usage:
        detector = RoomDetector()
        rooms = detector.detect(
            room_view=views.room_view,
            ai_width=views.ai_width,
            ai_height=views.ai_height,
        )
    """

    def detect(
        self,
        room_view:           np.ndarray,
        ai_width:            int,
        ai_height:           int,
        min_room_area_px:    int   = DEFAULT_MIN_ROOM_AREA_PX,
        max_room_area_ratio: float = DEFAULT_MAX_ROOM_AREA_RATIO,
        min_confidence:      float = DEFAULT_MIN_CONFIDENCE,
        debug_writer:        Optional[DebugImageWriter] = None,
        original_bgr:        Optional[np.ndarray]       = None,
    ) -> List[RoomPolygon]:
        """
        Detect room regions from a pre-processed room_view binary image.

        Args:
            room_view:           Binary image from preprocessor: 255=walkable, 0=wall.
                                 Already gap-closed by preprocessor.
            ai_width:            Width of the AI analysis image in pixels.
            ai_height:           Height of the AI analysis image in pixels.
            min_room_area_px:    Minimum area (px²) for a candidate to be considered.
            max_room_area_ratio: Maximum fraction of total image area (exterior filter).
            min_confidence:      Minimum combined confidence score to keep a room.
            debug_writer:        Optional DebugImageWriter for saving debug images.
            original_bgr:        Original BGR image for annotated debug output.

        Returns:
            List of RoomPolygon objects sorted by area descending.
        """
        if room_view is None:
            logger.warning("RoomDetector received None room_view — returning empty list")
            return []

        dbg = debug_writer or DebugImageWriter(prefix="", enabled=False)

        ai_area       = ai_width * ai_height
        max_room_area = ai_area * max_room_area_ratio

        logger.info(
            "Stage 1C: room detection started",
            ai_size=f"{ai_width}×{ai_height}",
            min_area_px=min_room_area_px,
            max_area_ratio=max_room_area_ratio,
            min_confidence=min_confidence,
        )

        # ── CCA on room_view (255=walkable) ────────────────────────────────────
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            room_view, connectivity=8, ltype=cv2.CV_32S
        )

        # ── Identify exterior components BEFORE the per-label loop ─────────────
        # The exterior space (background outside the building) ALWAYS touches at
        # least one image border pixel. By checking which CCA labels appear on
        # any border row or column, we correctly exclude exterior without relying
        # on a fragile max_area_ratio threshold alone.
        h_img, w_img = room_view.shape[:2]
        border_labels: set = set()
        border_labels.update(labels[0, :].tolist())          # top row
        border_labels.update(labels[h_img - 1, :].tolist())  # bottom row
        border_labels.update(labels[:, 0].tolist())          # left col
        border_labels.update(labels[:, w_img - 1].tolist())  # right col
        border_labels.discard(0)  # Label 0 is always the CCA background (wall pixels)

        logger.info(
            "Exterior component identification",
            border_touching_labels=len(border_labels),
            total_components=num_labels - 1,
        )

        # Track results per candidate for diagnostics
        candidate_results: List[_CandidateResult] = []
        rooms:             List[RoomPolygon]       = []
        accepted_ids:      List[int]               = []
        room_counter = 0

        for i in range(1, num_labels):  # Skip label 0 (background)
            area = int(stats[i, cv2.CC_STAT_AREA])
            x    = int(stats[i, cv2.CC_STAT_LEFT])
            y    = int(stats[i, cv2.CC_STAT_TOP])
            w    = int(stats[i, cv2.CC_STAT_WIDTH])
            h    = int(stats[i, cv2.CC_STAT_HEIGHT])

            # ── Filter 1: Exterior (touches image border) ───────────────────────
            if i in border_labels:
                candidate_results.append(_CandidateResult(
                    label_id=i, area=area, x=x, y=y, w=w, h=h,
                    accepted=False,
                    reject_reason=f"exterior_border_touching (area={area})",
                ))
                continue

            # ── Filter 2: Too small ─────────────────────────────────────────────
            if area < min_room_area_px:
                candidate_results.append(_CandidateResult(
                    label_id=i, area=area, x=x, y=y, w=w, h=h,
                    accepted=False,
                    reject_reason=f"too_small (area={area} < min={min_room_area_px})",
                ))
                continue

            # ── Filter 3: Too large interior (secondary sanity check) ───────────
            if area > max_room_area:
                candidate_results.append(_CandidateResult(
                    label_id=i, area=area, x=x, y=y, w=w, h=h,
                    accepted=False,
                    reject_reason=f"interior_too_large (area={area} > max={max_room_area:.0f})",
                ))
                continue


            # ── Extract contour ─────────────────────────────────────────────────
            component_mask = np.zeros_like(room_view, dtype=np.uint8)
            component_mask[labels == i] = 255
            contours, _ = cv2.findContours(
                component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if not contours:
                candidate_results.append(_CandidateResult(
                    label_id=i, area=area, x=x, y=y, w=w, h=h,
                    accepted=False, reject_reason="no_contour",
                ))
                continue

            contour = max(contours, key=cv2.contourArea)

            # ── Multi-criteria confidence score ────────────────────────────────
            confidence = self._compute_confidence(
                contour=contour,
                area=area,
                width=w,
                height=h,
                min_area=min_room_area_px,
                max_area=int(max_room_area),
            )

            # ── Filter 3: Low confidence ────────────────────────────────────────
            if confidence < min_confidence:
                candidate_results.append(_CandidateResult(
                    label_id=i, area=area, x=x, y=y, w=w, h=h,
                    accepted=False,
                    reject_reason=f"low_confidence ({confidence:.3f} < {min_confidence})",
                    confidence=confidence,
                ))
                continue

            # ── Accepted: build RoomPolygon ─────────────────────────────────────
            epsilon = 0.02 * cv2.arcLength(contour, True)
            approx  = cv2.approxPolyDP(contour, epsilon, True)
            polygon_points = [
                Point(x=float(pt[0][0]), y=float(pt[0][1]))
                for pt in approx
            ]

            # Centroid from moments (more accurate than stats centroid)
            M = cv2.moments(contour)
            if M["m00"] != 0:
                cx = float(M["m10"] / M["m00"])
                cy = float(M["m01"] / M["m00"])
            else:
                cx = float(centroids[i][0])
                cy = float(centroids[i][1])

            room_id = f"room_{room_counter}"
            room_counter += 1
            accepted_ids.append(i)

            rooms.append(RoomPolygon(
                id=room_id,
                polygon=polygon_points,
                centroid=Point(x=cx, y=cy),
                area_px=float(area),
                bounding_rect=BoundingBox(
                    x=float(x), y=float(y), width=float(w), height=float(h)
                ),
                confidence=confidence,
            ))

            candidate_results.append(_CandidateResult(
                label_id=i, area=area, x=x, y=y, w=w, h=h,
                accepted=True, reject_reason=None, confidence=confidence,
            ))

        # ── Diagnostics ─────────────────────────────────────────────────────────
        total       = num_labels - 1
        n_small     = sum(1 for c in candidate_results if c.reject_reason and "too_small"   in c.reject_reason)
        n_exterior  = sum(1 for c in candidate_results if c.reject_reason and "exterior"    in c.reject_reason)
        n_shape     = sum(1 for c in candidate_results if c.reject_reason and "low_conf"    in c.reject_reason)
        n_no_cont   = sum(1 for c in candidate_results if c.reject_reason and "no_contour"  in c.reject_reason)
        n_accepted  = len(rooms)

        logger.info(
            "Stage 1C: room detection completed",
            total_candidates=total,
            rejected_too_small=n_small,
            rejected_exterior=n_exterior,
            rejected_low_confidence=n_shape,
            rejected_no_contour=n_no_cont,
            accepted=n_accepted,
        )

        # Per-candidate detail log (debug level — only shown when debug logging enabled)
        for c in candidate_results:
            if c.accepted:
                logger.debug(
                    "  Component ACCEPTED",
                    label_id=c.label_id,
                    area=c.area,
                    confidence=round(c.confidence, 3),
                )
            else:
                logger.debug(
                    "  Component REJECTED",
                    label_id=c.label_id,
                    area=c.area,
                    reason=c.reject_reason,
                )

        # Debug images
        dbg.write_colored_components(
            "08_room_candidates", labels, num_labels, accepted_ids=accepted_ids
        )
        base_for_rooms = original_bgr if original_bgr is not None else room_view
        dbg.write_labeled_rooms("09_room_accepted", base_for_rooms, rooms)

        # Sort by area descending
        rooms.sort(key=lambda r: r.area_px, reverse=True)
        return rooms

    # ── Confidence Scoring ─────────────────────────────────────────────────────

    @staticmethod
    def _compute_confidence(
        contour: np.ndarray,
        area:    int,
        width:   int,
        height:  int,
        min_area: int,
        max_area: int,
    ) -> float:
        """
        Compute a combined confidence score (0.0–1.0) for a room candidate.

        Criteria:
          rectangularity (0.35): area / bounding_rect_area
            — most rooms are close to rectangular
          convexity (0.30):      contour_area / convex_hull_area
            — rooms are generally convex; very non-convex shapes penalised
          compactness (0.15):    4π·area / perimeter²
            — penalises very elongated or thin shapes (corridors)
          size_score (0.20):     log-normalised area within valid range
            — penalises regions near the minimum threshold
        """
        # Rectangularity
        rect_area      = width * height
        rectangularity = (area / rect_area) if rect_area > 0 else 0.0
        rectangularity = min(1.0, rectangularity)

        # Convexity
        hull      = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        convexity = (area / hull_area) if hull_area > 0 else 0.0
        convexity = min(1.0, convexity)

        # Compactness (isoperimetric ratio)
        perimeter   = cv2.arcLength(contour, True)
        compactness = (4 * math.pi * area / (perimeter ** 2)) if perimeter > 0 else 0.0
        compactness = min(1.0, compactness)

        # Size score — log-scale between min and max
        valid_range = max(1, max_area - min_area)
        size_norm   = (area - min_area) / valid_range
        size_score  = min(1.0, max(0.0, size_norm ** 0.3))  # cube-root to flatten near-threshold penalty

        confidence = (
            0.35 * rectangularity +
            0.30 * convexity       +
            0.15 * compactness     +
            0.20 * size_score
        )
        return round(min(1.0, confidence), 4)
