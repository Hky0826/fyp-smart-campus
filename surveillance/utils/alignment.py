"""Face alignment utility using 5 facial landmarks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

logger = logging.getLogger(__name__)

# Standard 112x112 reference landmarks (InsightFace / ArcFace / AuraFace standard)
REFERENCE_LANDMARKS = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


@dataclass
class AlignmentResult:
    aligned_face: Optional[np.ndarray]
    success: bool
    failure_reason: Optional[str] = None


class FaceAligner:
    """Aligns detected faces to 112x112 standard input size using 5 facial landmarks."""

    def __init__(self, target_size: Tuple[int, int] = (112, 112)) -> None:
        self.target_size = target_size

    def align(self, image: np.ndarray, bbox: Tuple[float, float, float, float], landmarks: Optional[np.ndarray] = None) -> AlignmentResult:
        if image is None or image.size == 0:
            return AlignmentResult(None, False, "empty_image")

        h, w = image.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return AlignmentResult(None, False, "invalid_bbox")

        # If 5 landmarks are available and cv2 is installed, perform affine similarity transformation
        if landmarks is not None and len(landmarks) == 5 and cv2 is not None:
            try:
                src_pts = np.asarray(landmarks, dtype=np.float32)
                M, _ = cv2.estimateAffinePartial2D(src_pts, REFERENCE_LANDMARKS)
                if M is not None:
                    aligned = cv2.warpAffine(image, M, self.target_size, borderValue=0)
                    return AlignmentResult(aligned, True)
            except Exception as exc:
                logger.warning("Landmark affine alignment failed: %s", exc)

        # Fallback: simple bounding box crop & resize
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return AlignmentResult(None, False, "crop_empty")

        if cv2 is not None:
            aligned = cv2.resize(crop, self.target_size, interpolation=cv2.INTER_LINEAR)
        else:
            aligned = crop

        return AlignmentResult(aligned, True)
