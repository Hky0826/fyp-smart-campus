from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np


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


def extract_aligned_face(image_bgr: np.ndarray, face: dict, output_size: Tuple[int, int] = (112, 112)) -> np.ndarray:
    landmarks = face.get("landmarks")
    if landmarks is not None:
        src = np.asarray(landmarks, dtype=np.float32)
        if src.shape == (5, 2):
            dst = ARCFACE_TEMPLATE.copy()
            if output_size != (112, 112):
                dst[:, 0] *= output_size[0] / 112.0
                dst[:, 1] *= output_size[1] / 112.0
            transform, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
            if transform is not None:
                return cv2.warpAffine(image_bgr, transform, output_size, borderValue=0.0)

    x1, y1, x2, y2 = [int(v) for v in face["bbox"]]
    h, w = image_bgr.shape[:2]
    x1 = max(0, min(w, x1))
    x2 = max(0, min(w, x2))
    y1 = max(0, min(h, y1))
    y2 = max(0, min(h, y2))
    crop = image_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError("Detected face crop is empty")
    return cv2.resize(crop, output_size, interpolation=cv2.INTER_LINEAR)
