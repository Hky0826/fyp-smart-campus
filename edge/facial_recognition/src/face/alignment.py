"""Face crop and ArcFace alignment helpers."""

from __future__ import annotations

from typing import Tuple

import numpy as np

from .types import DetectedFace

try:
    import cv2
except Exception:  # pragma: no cover - handled on minimal test machines
    cv2 = None


ARCFACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


class FaceAligner:
    def __init__(self, output_size: Tuple[int, int] = (112, 112)) -> None:
        self.output_size = output_size

    def extract(self, frame: np.ndarray, face: DetectedFace) -> np.ndarray:
        if cv2 is not None and face.landmarks is not None and np.asarray(face.landmarks).shape == (5, 2):
            src = np.asarray(face.landmarks, dtype=np.float32)
            dst = ARCFACE_TEMPLATE.copy()
            if self.output_size != (112, 112):
                dst[:, 0] *= self.output_size[0] / 112.0
                dst[:, 1] *= self.output_size[1] / 112.0
            transform, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
            if transform is not None:
                return cv2.warpAffine(frame, transform, self.output_size, borderValue=0.0)

        x1, y1, x2, y2 = face.xyxy_int()
        h, w = frame.shape[:2]
        x1 = max(0, min(w, x1))
        x2 = max(0, min(w, x2))
        y1 = max(0, min(h, y1))
        y2 = max(0, min(h, y2))
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            raise ValueError("Detected face crop is empty")
        if cv2 is not None:
            crop = cv2.resize(crop, self.output_size, interpolation=cv2.INTER_LINEAR)
        return crop
