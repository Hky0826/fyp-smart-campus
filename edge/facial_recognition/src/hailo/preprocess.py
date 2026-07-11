"""Preprocessing helpers for SCRFD and ArcFace Hailo models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def resize_bgr(frame: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    if cv2 is None:
        raise RuntimeError("OpenCV is required for image preprocessing")
    return cv2.resize(frame, size, interpolation=cv2.INTER_LINEAR)


@dataclass(frozen=True)
class LetterboxMetadata:
    original_width: int
    original_height: int
    input_width: int
    input_height: int
    scale: float
    pad_x: float
    pad_y: float


def letterbox_preprocess(
    frame: np.ndarray,
    input_size: Tuple[int, int] = (640, 640),
    pad_value: int = 0,
) -> tuple[np.ndarray, LetterboxMetadata]:
    """Resize a BGR frame without distortion and return an exact-size BGR image."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for image preprocessing")
    if frame.ndim not in {2, 3} or frame.shape[0] <= 0 or frame.shape[1] <= 0:
        raise ValueError("frame must be a non-empty HxW or HxWxC array")
    input_width, input_height = (int(input_size[0]), int(input_size[1]))
    if input_width <= 0 or input_height <= 0:
        raise ValueError("input_size dimensions must be positive")

    original_height, original_width = frame.shape[:2]
    scale = min(input_width / original_width, input_height / original_height)
    resized_width = max(1, min(input_width, int(round(original_width * scale))))
    resized_height = max(1, min(input_height, int(round(original_height * scale))))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    pad_left = (input_width - resized_width) // 2
    pad_top = (input_height - resized_height) // 2
    pad_right = input_width - resized_width - pad_left
    pad_bottom = input_height - resized_height - pad_top
    padded = cv2.copyMakeBorder(
        resized, pad_top, pad_bottom, pad_left, pad_right,
        cv2.BORDER_CONSTANT, value=pad_value,
    )
    metadata = LetterboxMetadata(
        original_width=original_width,
        original_height=original_height,
        input_width=input_width,
        input_height=input_height,
        scale=float(scale),
        pad_x=float(pad_left),
        pad_y=float(pad_top),
    )
    return padded, metadata


def map_bbox_to_original(bbox: np.ndarray, metadata: LetterboxMetadata) -> np.ndarray:
    mapped = np.asarray(bbox, dtype=np.float32).reshape(4).copy()
    mapped[[0, 2]] = (mapped[[0, 2]] - metadata.pad_x) / metadata.scale
    mapped[[1, 3]] = (mapped[[1, 3]] - metadata.pad_y) / metadata.scale
    mapped[[0, 2]] = np.clip(mapped[[0, 2]], 0.0, float(metadata.original_width - 1))
    mapped[[1, 3]] = np.clip(mapped[[1, 3]], 0.0, float(metadata.original_height - 1))
    return mapped


def map_landmarks_to_original(landmarks: np.ndarray, metadata: LetterboxMetadata) -> np.ndarray:
    mapped = np.asarray(landmarks, dtype=np.float32).reshape(5, 2).copy()
    mapped[:, 0] = (mapped[:, 0] - metadata.pad_x) / metadata.scale
    mapped[:, 1] = (mapped[:, 1] - metadata.pad_y) / metadata.scale
    mapped[:, 0] = np.clip(mapped[:, 0], 0.0, float(metadata.original_width - 1))
    mapped[:, 1] = np.clip(mapped[:, 1], 0.0, float(metadata.original_height - 1))
    return mapped


def preprocess_scrfd(
    frame: np.ndarray,
    input_size: Tuple[int, int] = (640, 640),
    *,
    return_metadata: bool = False,
) -> np.ndarray | tuple[np.ndarray, LetterboxMetadata]:
    """Letterboxed BGR uint8 frame to NHWC RGB float32 tensor.

    Hailo SCRFD HEFs from the model zoo include input normalization in the
    network, so the runtime input should remain in the 0..255 image range.
    """
    letterboxed, metadata = letterbox_preprocess(frame, input_size)
    tensor = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB).astype(np.float32)
    batched = np.expand_dims(tensor, axis=0)
    return (batched, metadata) if return_metadata else batched


def preprocess_arcface(face_bgr: np.ndarray, input_size: Tuple[int, int] = (112, 112)) -> np.ndarray:
    """BGR face crop to NHWC RGB tensor expected by Hailo ArcFace HEFs."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for image preprocessing")
    img = cv2.resize(face_bgr, input_size, interpolation=cv2.INTER_LINEAR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32)
    return np.expand_dims(img, axis=0).astype(np.float32, copy=False)
