"""OpenCV YuNet face detector adapter."""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter
from typing import List, Tuple

import cv2
import numpy as np

from .types import DetectedFace

logger = logging.getLogger(__name__)


class YuNetDetector:
    """OpenCV YuNet face detector adapter returning DetectedFace instances."""

    def __init__(
        self,
        model_path: str | Path,
        input_size: Tuple[int, int] = (640, 640),
        confidence_threshold: float = 0.6,
        nms_iou_threshold: float = 0.3,
        min_face_size: float = 16.0,
        max_box_size_ratio: float = 0.95,
        box_expansion_ratio: float = 0.0,
        log_empty_detections: bool = True,
        max_dim: int = 640,
    ) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(f"YuNet model file not found: {path}")

        self.model_path = path
        self._input_size = (int(input_size[0]), int(input_size[1]))
        self.confidence_threshold = float(confidence_threshold)
        self.nms_iou_threshold = float(nms_iou_threshold)
        self.min_face_size = float(min_face_size)
        self.max_box_size_ratio = float(max_box_size_ratio)
        self.box_expansion_ratio = float(box_expansion_ratio)
        self.log_empty_detections = log_empty_detections
        self.max_dim = int(max_dim) if max_dim is not None else 0
        self.last_inference_ms = 0.0

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

    def detect(self, frame: np.ndarray) -> List[DetectedFace]:
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        if self.max_dim > 0 and max(h, w) > self.max_dim:
            if w >= h:
                det_w = self.max_dim
                det_h = max(1, int(round(h * (self.max_dim / w))))
            else:
                det_h = self.max_dim
                det_w = max(1, int(round(w * (self.max_dim / h))))
            det_frame = cv2.resize(frame, (det_w, det_h), interpolation=cv2.INTER_LINEAR)
            scale_x = float(w) / float(det_w)
            scale_y = float(h) / float(det_h)
        else:
            det_frame = frame
            det_w, det_h = w, h
            scale_x, scale_y = 1.0, 1.0

        self.set_input_size(det_w, det_h)

        started = perf_counter()
        _, rows = self._detector.detect(det_frame)
        self.last_inference_ms = (perf_counter() - started) * 1000.0

        if rows is None:
            return []

        faces: List[DetectedFace] = []
        for row in np.asarray(rows):
            if row.size < 15 or not np.all(np.isfinite(row[:15])):
                continue

            score = float(row[14])
            if score < self.confidence_threshold:
                continue

            x, y, width, height = map(float, row[:4])
            x *= scale_x
            y *= scale_y
            width *= scale_x
            height *= scale_y
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
            landmarks[:, 0] = np.clip(landmarks[:, 0] * scale_x, 0.0, float(max(0, w - 1)))
            landmarks[:, 1] = np.clip(landmarks[:, 1] * scale_y, 0.0, float(max(0, h - 1)))

            faces.append(DetectedFace(
                bbox=[x1, y1, x2, y2],
                confidence=score,
                landmarks=landmarks,
            ))

        if not faces:
            return []

        # Select only the single face closest to the camera (largest bounding box area)
        closest_face = max(faces, key=lambda f: f.width() * f.height())
        return [closest_face]
