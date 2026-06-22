"""Preprocessing helpers for SCRFD and ArcFace Hailo models."""

from __future__ import annotations

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


def preprocess_scrfd(frame: np.ndarray, input_size: Tuple[int, int] = (640, 640)) -> np.ndarray:
    """BGR uint8 frame to NHWC RGB float32 tensor.

    Hailo SCRFD HEFs from the model zoo include input normalization in the
    network, so the runtime input should remain in the 0..255 image range.
    """
    resized = resize_bgr(frame, input_size)
    tensor = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
    return np.expand_dims(tensor, axis=0)


def preprocess_arcface(face_bgr: np.ndarray, input_size: Tuple[int, int] = (112, 112)) -> np.ndarray:
    """BGR face crop to NCHW normalized RGB tensor expected by ArcFace-like models."""
    if cv2 is None:
        raise RuntimeError("OpenCV is required for image preprocessing")
    img = cv2.resize(face_bgr, input_size, interpolation=cv2.INTER_LINEAR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0
    img = (img - 0.5) / 0.5
    img = np.transpose(img, (2, 0, 1))
    return np.expand_dims(img, axis=0).astype(np.float32, copy=False)
