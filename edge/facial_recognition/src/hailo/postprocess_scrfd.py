"""SCRFD postprocessing for common Hailo output layouts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import numpy as np

from ..face.types import DetectedFace
from .preprocess import LetterboxMetadata, map_bbox_to_original, map_landmarks_to_original


logger = logging.getLogger(__name__)
SCRFD_STRIDES = (8, 16, 32, 64, 4)


@dataclass(frozen=True)
class _RawHead:
    kind: str
    name: str
    values: np.ndarray
    row_count: int
    stride: int
    grid_shape: Tuple[int, int]
    anchors: int


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
    metadata: LetterboxMetadata | None = None,
    min_box_size: float = 1.0,
    max_box_size_ratio: float = 1.0,
    box_expansion_ratio: float = 0.0,
) -> List[DetectedFace]:
    """Parse SCRFD output tensors into `DetectedFace` objects.

    Hailo HEFs may expose either already-decoded NMS tensors, final detection
    rows, or raw SCRFD heads. Raw heads are decoded with the SCRFD anchor grid for
    strides 8/16/32 and then filtered with NMS.
    """

    original_h, original_w = original_shape[:2]
    input_w, input_h = input_size
    metadata = metadata or LetterboxMetadata(
        original_width=original_w,
        original_height=original_h,
        input_width=input_w,
        input_height=input_h,
        scale=min(input_w / original_w, input_h / original_h),
        pad_x=(input_w - original_w * min(input_w / original_w, input_h / original_h)) / 2.0,
        pad_y=(input_h - original_h * min(input_w / original_w, input_h / original_h)) / 2.0,
    )
    detector_shape = (input_h, input_w)
    faces = _parse_named_detection_outputs(outputs, detector_shape, confidence_threshold)
    if not faces:
        faces = _parse_final_detection_rows(outputs, detector_shape, input_size, confidence_threshold)
    if not faces:
        faces = _parse_raw_scrfd_heads(outputs, detector_shape, input_size, confidence_threshold)

    faces = _map_validate_and_expand_faces(
        faces, metadata, min_box_size, max_box_size_ratio, box_expansion_ratio
    )
    if not faces:
        logger.debug("SCRFD postprocess produced no faces. Output summary: %s", summarize_outputs(outputs))
    return nms(faces, nms_iou_threshold)


def summarize_outputs(outputs: Dict[str, np.ndarray]) -> str:
    summary = []
    for name, value in outputs.items():
        arr = np.asarray(value)
        if arr.size == 0:
            summary.append(f"{name}: shape={tuple(arr.shape)} empty")
            continue
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            summary.append(f"{name}: shape={tuple(arr.shape)} no-finite-values")
            continue
        summary.append(
            f"{name}: shape={tuple(arr.shape)} min={float(np.min(finite)):.4f} "
            f"max={float(np.max(finite)):.4f} mean={float(np.mean(finite)):.4f}"
        )
    return "; ".join(summary)


def _parse_named_detection_outputs(
    outputs: Dict[str, np.ndarray],
    original_shape: Tuple[int, int],
    confidence_threshold: float,
) -> List[DetectedFace]:
    boxes = _find_output(outputs, ("detection_boxes", "boxes"))
    scores = _find_output(outputs, ("detection_scores", "scores"))
    if boxes is None or scores is None:
        return []

    original_h, original_w = original_shape[:2]
    boxes_arr = _drop_batch(np.asarray(boxes, dtype=np.float32))
    scores_arr = _drop_batch(np.asarray(scores, dtype=np.float32)).reshape(-1)
    if boxes_arr.ndim != 2 or boxes_arr.shape[1] < 4:
        return []

    count_arr = _find_output(outputs, ("num_detections",))
    if count_arr is not None and np.asarray(count_arr).size:
        count = int(np.asarray(count_arr).reshape(-1)[0])
    else:
        count = len(scores_arr)
    count = min(count, len(scores_arr), boxes_arr.shape[0])

    landmarks_arr = None
    landmarks = _find_output(outputs, ("face_landmarks", "landmarks"))
    if landmarks is not None:
        landmarks_arr = _drop_batch(np.asarray(landmarks, dtype=np.float32))

    faces: List[DetectedFace] = []
    for index in range(count):
        score = float(scores_arr[index])
        if score < confidence_threshold:
            continue

        y1, x1, y2, x2 = [float(value) for value in boxes_arr[index, :4]]
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 2.0:
            x1, x2 = x1 * original_w, x2 * original_w
            y1, y2 = y1 * original_h, y2 * original_h

        face_landmarks = None
        if (
            landmarks_arr is not None
            and landmarks_arr.ndim == 2
            and index < landmarks_arr.shape[0]
            and landmarks_arr.shape[1] >= 10
        ):
            face_landmarks = landmarks_arr[index, :10].reshape(5, 2).astype(np.float32)
            if float(np.max(np.abs(face_landmarks))) <= 2.0:
                face_landmarks[:, 0] *= original_w
                face_landmarks[:, 1] *= original_h

        faces.append(DetectedFace(bbox=[x1, y1, x2, y2], confidence=score, landmarks=face_landmarks))
    return faces


def _parse_final_detection_rows(
    outputs: Dict[str, np.ndarray],
    original_shape: Tuple[int, int],
    input_size: Tuple[int, int],
    confidence_threshold: float,
) -> List[DetectedFace]:
    faces: List[DetectedFace] = []
    for name, value in outputs.items():
        arr = _drop_batch(np.asarray(value, dtype=np.float32))
        if arr.size == 0:
            continue
        if arr.ndim == 1 and arr.shape[0] in {5, 6, 15, 16}:
            arr = arr.reshape(1, -1)
        if arr.ndim != 2 or arr.shape[1] not in {5, 6, 15, 16}:
            continue
        faces.extend(_rows_to_faces(arr, original_shape, input_size, confidence_threshold))
    return faces


def _parse_raw_scrfd_heads(
    outputs: Dict[str, np.ndarray],
    original_shape: Tuple[int, int],
    input_size: Tuple[int, int],
    confidence_threshold: float,
) -> List[DetectedFace]:
    heads: List[_RawHead] = []
    for name, value in outputs.items():
        heads.extend(_raw_head_candidates(name, value, input_size))

    scores_by_count = _heads_by_count(heads, "score")
    boxes_by_count = _heads_by_count(heads, "box")
    landmarks_by_count = _heads_by_count(heads, "landmark")
    faces: List[DetectedFace] = []

    for row_count, score_heads in scores_by_count.items():
        box_heads = boxes_by_count.get(row_count)
        if not box_heads:
            continue
        score_head = score_heads[0]
        box_head = box_heads[0]
        landmark_head = (landmarks_by_count.get(row_count) or [None])[0]
        faces.extend(
            _decode_raw_heads(score_head, box_head, landmark_head, original_shape, input_size, confidence_threshold)
        )
    return faces


def _heads_by_count(heads: List[_RawHead], kind: str) -> Dict[int, List[_RawHead]]:
    grouped: Dict[int, List[_RawHead]] = {}
    for head in heads:
        if head.kind == kind:
            grouped.setdefault(head.row_count, []).append(head)
    return grouped


def _decode_raw_heads(
    scores: _RawHead,
    boxes: _RawHead,
    landmarks: _RawHead | None,
    original_shape: Tuple[int, int],
    input_size: Tuple[int, int],
    confidence_threshold: float,
) -> List[DetectedFace]:
    original_h, original_w = original_shape[:2]
    input_w, input_h = input_size
    scale_x = original_w / float(input_w)
    scale_y = original_h / float(input_h)
    grid_h, grid_w = boxes.grid_shape
    stride = float(boxes.stride)
    anchors = boxes.anchors

    score_values = _score_values(scores.values)
    box_values = boxes.values.reshape(-1, 4)
    if score_values.shape[0] != box_values.shape[0]:
        return []

    centers = np.stack(np.mgrid[:grid_h, :grid_w][::-1], axis=-1).astype(np.float32)
    centers = (centers * stride).reshape((-1, 2))
    if anchors > 1:
        centers = np.stack([centers] * anchors, axis=1).reshape((-1, 2))

    landmark_values = landmarks.values.reshape(-1, 10) if landmarks is not None and landmarks.values.size else None
    faces: List[DetectedFace] = []
    for index, score in enumerate(score_values):
        confidence = float(score)
        if confidence < confidence_threshold:
            continue

        center_x, center_y = centers[index]
        left, top, right, bottom = box_values[index] * stride
        bbox = [
            (center_x - left) * scale_x,
            (center_y - top) * scale_y,
            (center_x + right) * scale_x,
            (center_y + bottom) * scale_y,
        ]

        face_landmarks = None
        if landmark_values is not None and index < landmark_values.shape[0]:
            decoded = []
            for landmark_index in range(0, 10, 2):
                x = (center_x + landmark_values[index, landmark_index] * stride) * scale_x
                y = (center_y + landmark_values[index, landmark_index + 1] * stride) * scale_y
                decoded.append([x, y])
            face_landmarks = np.asarray(decoded, dtype=np.float32)

        faces.append(DetectedFace(bbox=bbox, confidence=confidence, landmarks=face_landmarks))
    return faces


def _raw_head_candidates(name: str, value: np.ndarray, input_size: Tuple[int, int]) -> List[_RawHead]:
    arr = _drop_batch(np.asarray(value, dtype=np.float32))
    if arr.size == 0:
        return []
    kind = _infer_kind(name, arr)
    if kind is None:
        return []

    if arr.ndim == 3:
        return _raw_hwc_candidates(kind, name, arr, input_size)
    if arr.ndim == 2:
        return _raw_2d_candidates(kind, name, arr, input_size)
    return []


def _raw_hwc_candidates(kind: str, name: str, arr: np.ndarray, input_size: Tuple[int, int]) -> List[_RawHead]:
    grid_h, grid_w, channels = arr.shape
    stride_info = _infer_grid_from_shape(grid_h, grid_w, input_size)
    if stride_info is None:
        return []
    stride, grid_shape = stride_info

    values = _reshape_head_values(kind, arr.reshape(-1, channels), grid_h * grid_w)
    if values is None:
        return []
    anchors = max(1, values.shape[0] // (grid_h * grid_w))
    return [_RawHead(kind, name, values, values.shape[0], stride, grid_shape, anchors)]


def _raw_2d_candidates(kind: str, name: str, arr: np.ndarray, input_size: Tuple[int, int]) -> List[_RawHead]:
    row_count, channels = arr.shape
    candidates: List[_RawHead] = []

    direct_grid = _infer_grid_from_count(row_count, input_size)
    if direct_grid is not None:
        stride, grid_shape, anchors = direct_grid
        direct_values = _reshape_flat_values(kind, arr)
        if direct_values is not None and direct_values.shape[0] == row_count:
            candidates.append(_RawHead(kind, name, direct_values, row_count, stride, grid_shape, anchors))

    expanded_rows = row_count * _channel_anchor_count(kind, channels)
    expanded_grid = _infer_grid_from_count(expanded_rows, input_size)
    if expanded_grid is not None and expanded_rows != row_count:
        stride, grid_shape, anchors = expanded_grid
        expanded_values = _reshape_head_values(kind, arr, row_count)
        if expanded_values is not None and expanded_values.shape[0] == expanded_rows:
            candidates.append(_RawHead(kind, name, expanded_values, expanded_rows, stride, grid_shape, anchors))
    return candidates


def _reshape_head_values(kind: str, arr: np.ndarray, location_count: int) -> np.ndarray | None:
    channels = arr.shape[1]
    if kind == "score":
        if channels in {1, 2}:
            return arr.reshape(-1, 1)
        if channels % 2 == 0:
            return arr.reshape(location_count, channels // 2, 2).reshape(-1, 2)
    if kind == "box" and channels % 4 == 0:
        return arr.reshape(location_count, channels // 4, 4).reshape(-1, 4)
    if kind == "landmark" and channels % 10 == 0:
        return arr.reshape(location_count, channels // 10, 10).reshape(-1, 10)
    return None


def _reshape_flat_values(kind: str, arr: np.ndarray) -> np.ndarray | None:
    channels = arr.shape[1]
    if kind == "score" and channels in {1, 2}:
        return arr
    if kind == "box" and channels == 4:
        return arr
    if kind == "landmark" and channels == 10:
        return arr
    return None


def _channel_anchor_count(kind: str, channels: int) -> int:
    if kind == "score":
        return channels if channels in {1, 2} else max(1, channels // 2)
    if kind == "box":
        return max(1, channels // 4)
    if kind == "landmark":
        return max(1, channels // 10)
    return 1


def _score_values(values: np.ndarray) -> np.ndarray:
    if values.ndim == 1:
        scores = values
    elif values.shape[1] == 1:
        scores = values[:, 0]
    else:
        scores = values[:, -1]
    if np.nanmin(scores) < 0.0 or np.nanmax(scores) > 1.0:
        scores = 1.0 / (1.0 + np.exp(-scores))
    return scores.astype(np.float32, copy=False)


def _infer_kind(name: str, arr: np.ndarray) -> str | None:
    lowered = name.lower()
    if any(token in lowered for token in ("landmark", "kps", "keypoint")):
        return "landmark"
    if any(token in lowered for token in ("bbox", "box", "reg")):
        return "box"
    if any(token in lowered for token in ("score", "class", "cls", "conf")):
        return "score"

    if arr.ndim not in {2, 3}:
        return None
    channels = arr.shape[-1]
    if channels in {1, 2}:
        return "score"
    if channels in {4, 8}:
        return "box"
    if channels in {10, 20}:
        return "landmark"
    return None


def _infer_grid_from_shape(grid_h: int, grid_w: int, input_size: Tuple[int, int]) -> Tuple[int, Tuple[int, int]] | None:
    input_w, input_h = input_size
    if grid_h <= 0 or grid_w <= 0 or input_h % grid_h != 0 or input_w % grid_w != 0:
        return None
    stride_h = input_h // grid_h
    stride_w = input_w // grid_w
    if stride_h != stride_w:
        return None
    return stride_h, (grid_h, grid_w)


def _infer_grid_from_count(row_count: int, input_size: Tuple[int, int]) -> Tuple[int, Tuple[int, int], int] | None:
    input_w, input_h = input_size
    for stride in SCRFD_STRIDES:
        grid_h = input_h // stride
        grid_w = input_w // stride
        locations = grid_h * grid_w
        if locations <= 0 or row_count % locations != 0:
            continue
        anchors = row_count // locations
        if anchors in {1, 2}:
            return stride, (grid_h, grid_w), anchors
    return None


def _find_output(outputs: Dict[str, np.ndarray], tokens: Tuple[str, ...]) -> np.ndarray | None:
    for name, value in outputs.items():
        lowered = name.lower()
        if any(token in lowered for token in tokens):
            return value
    return None


def _drop_batch(arr: np.ndarray) -> np.ndarray:
    while arr.ndim > 2 and arr.shape[0] == 1:
        arr = arr[0]
    return arr


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


def _clip_faces(faces: List[DetectedFace], original_shape: Tuple[int, int]) -> List[DetectedFace]:
    original_h, original_w = original_shape[:2]
    clipped: List[DetectedFace] = []
    for face in faces:
        x1, y1, x2, y2 = [float(value) for value in face.bbox[:4]]
        x1 = max(0.0, min(float(original_w - 1), x1))
        x2 = max(0.0, min(float(original_w - 1), x2))
        y1 = max(0.0, min(float(original_h - 1), y1))
        y2 = max(0.0, min(float(original_h - 1), y2))
        if x2 <= x1 or y2 <= y1:
            continue
        clipped.append(
            DetectedFace(bbox=[x1, y1, x2, y2], confidence=face.confidence, landmarks=face.landmarks)
        )
    return clipped


def _map_validate_and_expand_faces(
    faces: List[DetectedFace],
    metadata: LetterboxMetadata,
    min_box_size: float,
    max_box_size_ratio: float,
    expansion_ratio: float,
) -> List[DetectedFace]:
    validated: List[DetectedFace] = []
    max_width = metadata.original_width * max_box_size_ratio
    max_height = metadata.original_height * max_box_size_ratio
    for face in faces:
        detector_bbox = np.asarray(face.bbox, dtype=np.float32)
        if detector_bbox.shape != (4,) or not np.all(np.isfinite(detector_bbox)):
            continue
        if not np.isfinite(face.confidence) or detector_bbox[2] <= detector_bbox[0] or detector_bbox[3] <= detector_bbox[1]:
            continue
        landmarks = None
        if face.landmarks is not None:
            detector_landmarks = np.asarray(face.landmarks, dtype=np.float32)
            if detector_landmarks.shape != (5, 2) or not np.all(np.isfinite(detector_landmarks)):
                continue
            input_margin = max(metadata.input_width, metadata.input_height) * 0.25
            if (
                np.any(detector_landmarks[:, 0] < -input_margin)
                or np.any(detector_landmarks[:, 0] > metadata.input_width + input_margin)
                or np.any(detector_landmarks[:, 1] < -input_margin)
                or np.any(detector_landmarks[:, 1] > metadata.input_height + input_margin)
            ):
                continue
            landmarks = map_landmarks_to_original(detector_landmarks, metadata)
        bbox = map_bbox_to_original(detector_bbox, metadata)
        if expansion_ratio > 0:
            center = (bbox[:2] + bbox[2:]) * 0.5
            half = (bbox[2:] - bbox[:2]) * 0.5 * (1.0 + expansion_ratio)
            bbox = np.concatenate((center - half, center + half))
            bbox[[0, 2]] = np.clip(bbox[[0, 2]], 0, metadata.original_width - 1)
            bbox[[1, 3]] = np.clip(bbox[[1, 3]], 0, metadata.original_height - 1)
        width, height = float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])
        if width < min_box_size or height < min_box_size or width > max_width or height > max_height:
            continue
        validated.append(DetectedFace(bbox, float(face.confidence), landmarks, face.track_id))
    return validated
