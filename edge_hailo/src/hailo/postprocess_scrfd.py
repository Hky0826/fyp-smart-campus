"""Best-effort SCRFD postprocessing for common Hailo output layouts."""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import numpy as np

from ..face.types import DetectedFace


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    denom = area_a + area_b - inter
    return 0.0 if denom <= 0 else float(inter / denom)


def nms(faces: Iterable[DetectedFace], iou_threshold: float = 0.4) -> List[DetectedFace]:
    sorted_faces = sorted(faces, key=lambda f: f.confidence, reverse=True)
    kept: List[DetectedFace] = []
    for face in sorted_faces:
        bbox = np.asarray(face.bbox, dtype=np.float32)
        if all(_iou(bbox, np.asarray(existing.bbox, dtype=np.float32)) < iou_threshold for existing in kept):
            kept.append(face)
    return kept


def postprocess_scrfd(
    outputs: Dict[str, np.ndarray],
    original_shape: Tuple[int, int],
    input_size: Tuple[int, int] = (640, 640),
    confidence_threshold: float = 0.6,
    nms_iou_threshold: float = 0.4,
) -> List[DetectedFace]:
    """Parse SCRFD-like output tensors into `DetectedFace` objects.

    Hailo model-zoo releases can expose model-specific stream names. This parser
    handles common final-detection tensors and should be adjusted if a deployed
    HEF exposes raw feature maps.
    """

    faces: List[DetectedFace] = []
    for value in outputs.values():
        arr = np.asarray(value)
        if arr.size == 0:
            continue
        arr = np.squeeze(arr)
        if arr.ndim == 1 and arr.shape[0] >= 5:
            arr = arr.reshape(1, -1)
        if arr.ndim != 2 or arr.shape[1] < 5:
            continue
        faces.extend(_rows_to_faces(arr, original_shape, input_size, confidence_threshold))
    return nms(faces, nms_iou_threshold)


def _rows_to_faces(
    rows: np.ndarray,
    original_shape: Tuple[int, int],
    input_size: Tuple[int, int],
    confidence_threshold: float,
) -> List[DetectedFace]:
    original_h, original_w = original_shape[:2]
    input_w, input_h = input_size
    scale_x = original_w / float(input_w)
    scale_y = original_h / float(input_h)
    faces: List[DetectedFace] = []

    for row in rows:
        row = row.astype(np.float32, copy=False).reshape(-1)
        score_index = 4 if 0.0 <= float(row[4]) <= 1.0 else row.shape[0] - 1
        score = float(row[score_index])
        if score < confidence_threshold:
            continue

        x1, y1, x2, y2 = [float(v) for v in row[:4]]
        if x2 <= x1 or y2 <= y1:
            x2 = x1 + max(0.0, x2)
            y2 = y1 + max(0.0, y2)
        bbox = [x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y]

        landmarks = None
        landmark_start = 5 if score_index == 4 else 4
        if row.shape[0] >= landmark_start + 10:
            landmarks = row[landmark_start:landmark_start + 10].reshape(5, 2).astype(np.float32)
            landmarks[:, 0] *= scale_x
            landmarks[:, 1] *= scale_y

        faces.append(DetectedFace(bbox=bbox, confidence=score, landmarks=landmarks))
    return faces
