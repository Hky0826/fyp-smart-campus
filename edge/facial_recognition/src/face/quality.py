"""Basic face quality gates for access-control decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .types import DetectedFace

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    reason: str = "ok"
    score: Optional[float] = None


class FaceQualityChecker:
    def __init__(self, min_face_size: int = 48, blur_threshold: float = 15.0) -> None:
        self.min_face_size = int(min_face_size)
        self.blur_threshold = float(blur_threshold)

    def check(self, frame: np.ndarray, face: DetectedFace) -> QualityResult:
        if face.width() < self.min_face_size or face.height() < self.min_face_size:
            return QualityResult(False, "face_too_small", min(face.width(), face.height()))

        if cv2 is None:
            return QualityResult(True)

        x1, y1, x2, y2 = face.xyxy_int()
        h, w = frame.shape[:2]
        crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        if crop.size == 0:
            return QualityResult(False, "empty_face_crop", 0.0)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if sharpness < self.blur_threshold:
            return QualityResult(False, "face_too_blurry", sharpness)
        return QualityResult(True, "ok", sharpness)
