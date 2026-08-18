"""
ocr/detector.py
---------------
OcrDetector — detects room labels using PaddleOCR.

Phase 1.5 role:
  Stage 1C — detect_text():
    Runs PaddleOCR on the OCR-optimized image from ImagePreprocessorService.
    Returns raw TextDetection list in AI space.
    Raw detections are passed to OcrFragmentMerger (Stage 1D) before use.

  Stage 1F-b — associate_labels_to_rooms():
    After room detection runs (Stage 1F), associates merged text labels with
    detected room polygons. Used to provide room metadata and gap-fill labels.
    In Phase 1.5 this is a supplementary role; primary node generation comes
    from OcrNodeGenerator in Stage 1E.

Two responsibilities:
  1. detect_text(ocr_view) → List[TextDetection]
     Runs PaddleOCR on the OCR-optimized image.

  2. associate_labels_to_rooms(texts, rooms) → (texts, rooms)
     Associates each text to its containing RoomPolygon via:
       Pass 1: point-in-polygon test (exact)
       Pass 2: nearest polygon boundary distance (fallback within tolerance)
       If no match → text left unassigned (with logged reason)

Design constraints:
  - OCR text is used ONLY to identify room labels.
  - Node position is determined by OCR label center + distanceTransform
    (in OcrNodeGenerator), NOT by room polygon geometry.
  - The AI never makes RBAC decisions — that is the admin's responsibility.

Coordinate System:
  PaddleOCR operates on the ocr_view image at AI analysis resolution.
  All returned coordinates are in AI space (not 800×600 canvas space).
  CoordinateTransformer converts them to canvas space after the full pipeline.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

from src.shared.models.v1.domain import Point, RoomPolygon, TextDetection
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Lazy PaddleOCR Initialization
# ─────────────────────────────────────────────────────────────────────────────

_ocr_engine    = None
_ocr_available = None  # None=unknown, True=ok, False=unavailable


def _get_ocr_engine():
    """Return the cached PaddleOCR engine, initializing it on first call."""
    global _ocr_engine, _ocr_available

    if _ocr_available is True:
        return _ocr_engine
    if _ocr_available is False:
        return None

    try:
        from paddleocr import PaddleOCR  # type: ignore
        logger.info("Initializing PaddleOCR engine (first use — may take a few seconds)...")
        _ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang="en",
            show_log=False,
            use_gpu=False,
        )
        _ocr_available = True
        logger.info("PaddleOCR engine ready")
        return _ocr_engine
    except ImportError:
        logger.warning(
            "PaddleOCR not installed — OCR disabled. "
            "Rooms will be labelled 'Unknown Room'."
        )
        _ocr_available = False
        return None
    except Exception as exc:
        logger.error("PaddleOCR initialization failed", error=str(exc))
        _ocr_available = False
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Default Parameters
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MIN_OCR_CONFIDENCE       = 0.60
DEFAULT_NEAREST_ROOM_TOLERANCE_PX = 200.0  # px in AI space; 200px handles large open rooms



class OcrDetector:
    """
    Stateless OCR detector for floorplan room labels.

    Detects text in the OCR-optimized image and associates each text region
    with its containing RoomPolygon.
    """

    def detect_text(
        self,
        ocr_view:       np.ndarray,
        min_confidence: float = DEFAULT_MIN_OCR_CONFIDENCE,
    ) -> List[TextDetection]:
        """
        Run PaddleOCR on the OCR-optimized view and return detected text regions.

        Args:
            ocr_view:        Grayscale image from preprocessor (sharpened+CLAHE).
                             At AI analysis resolution.
            min_confidence:  Minimum OCR confidence threshold. Default 0.60.

        Returns:
            List of TextDetection sorted by confidence descending.
            Returns empty list if PaddleOCR is unavailable.
        """
        ocr = _get_ocr_engine()
        if ocr is None:
            logger.warning("OCR engine unavailable — returning empty text detections")
            return []

        # PaddleOCR accepts both BGR and grayscale
        try:
            result = ocr.ocr(ocr_view, cls=True)
        except Exception as exc:
            logger.error("PaddleOCR inference failed", error=str(exc), exc_info=True)
            return []

        if not result or result[0] is None:
            logger.info("Stage 1D: PaddleOCR returned no detections")
            return []

        raw_detections = result[0]
        detections: List[TextDetection] = []
        filtered_count = 0

        for line in raw_detections:
            if line is None:
                continue

            bbox_raw, (text, conf) = line

            if conf < min_confidence:
                filtered_count += 1
                continue

            text_clean = text.strip()
            if len(text_clean) < 2:
                filtered_count += 1
                continue

            bbox_points = [Point(x=float(pt[0]), y=float(pt[1])) for pt in bbox_raw]
            cx = sum(pt.x for pt in bbox_points) / 4.0
            cy = sum(pt.y for pt in bbox_points) / 4.0

            detections.append(TextDetection(
                text=text_clean,
                bbox=bbox_points,
                center=Point(x=cx, y=cy),
                confidence=round(float(conf), 4),
            ))

        detections.sort(key=lambda d: d.confidence, reverse=True)

        logger.info(
            "Stage 1C: OCR detection completed",
            texts_found=len(detections),
            filtered_low_confidence=filtered_count,
        )

        return detections

    def associate_labels_to_rooms(
        self,
        texts:                     List[TextDetection],
        rooms:                     List[RoomPolygon],
        nearest_room_tolerance_px: float = DEFAULT_NEAREST_ROOM_TOLERANCE_PX,
    ) -> Tuple[List[TextDetection], List[RoomPolygon]]:
        """
        Associate detected text labels with their containing room polygons.

        Association algorithm:
          Pass 1 — Point-in-polygon test:
            If text center is inside a room polygon → assign to that room.
          Pass 2 — Nearest boundary fallback:
            If text is outside all polygons, compute distance from text center
            to each polygon using pointPolygonTest (returns signed distance).
            If nearest polygon is within nearest_room_tolerance_px → assign.
          No match → text is left unassigned, reason is logged.

        Each room receives only the highest-confidence text assigned to it.

        Args:
            texts:                     TextDetection list (AI space coordinates).
            rooms:                     RoomPolygon list (AI space coordinates).
            nearest_room_tolerance_px: Max signed distance for fallback assignment.

        Returns:
            Tuple of (updated_texts, updated_rooms) with associations set.
        """
        if not texts or not rooms:
            logger.info(
                "Stage 1F-b: association skipped (no texts or no rooms)",
                texts=len(texts), rooms=len(rooms),
            )
            return texts, rooms

        # Pre-build contour arrays for pointPolygonTest
        room_contours: List[np.ndarray] = []
        for room in rooms:
            pts = np.array(
                [[p.x, p.y] for p in room.polygon], dtype=np.float32
            ).reshape((-1, 1, 2))
            room_contours.append(pts)

        # Track best text per room (highest confidence wins)
        room_best_text: dict[str, TextDetection] = {}
        updated_texts = list(texts)

        for t_idx, text in enumerate(updated_texts):
            test_pt = (text.center.x, text.center.y)
            assigned_room_id: Optional[str] = None

            # Pass 1 — point-in-polygon
            for r_idx, room in enumerate(rooms):
                dist = cv2.pointPolygonTest(
                    room_contours[r_idx], test_pt, measureDist=False
                )
                if dist >= 0:
                    assigned_room_id = room.id
                    break

            # Pass 2 — nearest polygon boundary
            if assigned_room_id is None:
                best_dist = float("inf")
                for r_idx, room in enumerate(rooms):
                    # measureDist=True → negative value = distance outside polygon
                    signed_dist = cv2.pointPolygonTest(
                        room_contours[r_idx], test_pt, measureDist=True
                    )
                    dist_from_boundary = abs(signed_dist)
                    if dist_from_boundary < best_dist:
                        best_dist = dist_from_boundary
                        if dist_from_boundary <= nearest_room_tolerance_px:
                            assigned_room_id = room.id

                if assigned_room_id is None:
                    logger.debug(
                        "OCR text unassigned: outside all rooms and beyond tolerance",
                        text=text.text,
                        center=(round(text.center.x, 1), round(text.center.y, 1)),
                        nearest_dist=round(best_dist, 1),
                        tolerance=nearest_room_tolerance_px,
                    )

            if assigned_room_id is not None:
                updated_texts[t_idx] = text.model_copy(
                    update={"associated_room_id": assigned_room_id}
                )
                existing = room_best_text.get(assigned_room_id)
                if existing is None or text.confidence > existing.confidence:
                    room_best_text[assigned_room_id] = updated_texts[t_idx]

        # Apply best labels to rooms
        updated_rooms = list(rooms)
        for r_idx, room in enumerate(updated_rooms):
            best = room_best_text.get(room.id)
            if best is not None:
                updated_rooms[r_idx] = room.model_copy(update={
                    "label":            best.text,
                    "label_confidence": best.confidence,
                    "label_center":     best.center,
                })

        labeled_count   = sum(1 for r in updated_rooms if r.label is not None)
        assigned_count  = sum(1 for t in updated_texts if t.associated_room_id is not None)
        unassigned_count= len(updated_texts) - assigned_count

        logger.info(
            "Stage 1F-b: room-label association completed",
            rooms_with_labels=labeled_count,
            rooms_without_labels=len(updated_rooms) - labeled_count,
            texts_assigned=assigned_count,
            texts_unassigned=unassigned_count,
        )

        return updated_texts, updated_rooms
