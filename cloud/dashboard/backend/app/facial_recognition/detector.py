"""YuNet face detector wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple, List, Dict, Any

import cv2
import numpy as np


class YuNetDetector:
    """OpenCV YuNet face detector adapter returning dict instances with bbox, confidence, and landmarks."""

    def __init__(
        self,
        model_path: str | Path,
        input_size: Tuple[int, int] = (640, 640),
        confidence_threshold: float = 0.6,
        nms_iou_threshold: float = 0.3,
        min_face_size: float = 16.0,
    ) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(f"YuNet model file not found: {path}")

        self.model_path = path
        self._input_size = (int(input_size[0]), int(input_size[1]))
        self.confidence_threshold = float(confidence_threshold)
        self.nms_iou_threshold = float(nms_iou_threshold)
        self.min_face_size = float(min_face_size)

        self._detector = cv2.FaceDetectorYN.create(
            str(self.model_path),
            "",
            self._input_size,
            self.confidence_threshold,
            self.nms_iou_threshold,
            5000,
        )

    def set_input_size(self, width: int, height: int) -> None:
        size = (int(width), int(height))
        if size != self._input_size and size[0] > 0 and size[1] > 0:
            self._detector.setInputSize(size)
            self._input_size = size

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Detect faces on a frame. Returns list of dicts with bbox, confidence, and landmarks."""
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        self.set_input_size(w, h)

        try:
            _, rows = self._detector.detect(frame)
        except Exception:
            return []

        if rows is None:
            return []

        faces: List[Dict[str, Any]] = []
        for row in np.asarray(rows):
            if row.size < 15 or not np.all(np.isfinite(row[:15])):
                continue

            score = float(row[14])
            if score < self.confidence_threshold:
                continue

            x, y, width, height = map(float, row[:4])
            if width < self.min_face_size or height < self.min_face_size:
                continue

            # Convert (x, y, w, h) -> (x1, y1, x2, y2)
            x1 = max(0.0, x)
            y1 = max(0.0, y)
            x2 = min(float(w), x + width)
            y2 = min(float(h), y + height)

            if (x2 - x1) < self.min_face_size or (y2 - y1) < self.min_face_size:
                continue

            # YuNet landmarks: (x_re, y_re), (x_le, y_le), (x_n, y_n), (x_rm, y_rm), (x_lm, y_lm)
            landmarks = np.asarray(row[4:14], dtype=np.float32).reshape(5, 2)
            landmarks[:, 0] = np.clip(landmarks[:, 0], 0.0, float(max(0, w - 1)))
            landmarks[:, 1] = np.clip(landmarks[:, 1], 0.0, float(max(0, h - 1)))

            faces.append({
                "bbox": [x1, y1, x2, y2],
                "confidence": score,
                "landmarks": landmarks,
            })

        return faces

