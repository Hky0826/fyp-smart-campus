"""OpenCV SFace embedding adapter."""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter
from typing import Optional

import cv2
import numpy as np

from .types import DetectedFace

logger = logging.getLogger(__name__)


class IncompatibleEmbeddingError(ValueError):
    pass


class SFaceEmbedder:
    """OpenCV SFace facial recognition model adapter."""

    def __init__(
        self,
        model_path: str | Path,
        model_name: str = "openvc_sface",
        model_version: str = "2021dec",
    ) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(f"SFace model file not found: {path}")

        self.model_path = path
        self.model_name = model_name
        self.model_version = model_version
        self.last_inference_ms = 0.0

        self._recognizer = cv2.FaceRecognizerSF.create(str(self.model_path), "")

    def embed(self, face_bgr_or_frame: np.ndarray, face: Optional[DetectedFace] = None) -> np.ndarray:
        if face_bgr_or_frame is None or face_bgr_or_frame.size == 0:
            raise ValueError("Empty image provided to SFaceEmbedder.embed()")

        started = perf_counter()

        if face is not None and face.landmarks is not None and face.landmarks.shape == (5, 2):
            # Crop & align using OpenCV SFace alignCrop with 15-element YuNet row
            x1, y1, x2, y2 = face.bbox
            width = max(1.0, float(x2 - x1))
            height = max(1.0, float(y2 - y1))
            row = np.concatenate((
                np.asarray([x1, y1, width, height], dtype=np.float32),
                np.asarray(face.landmarks, dtype=np.float32).reshape(-1),
                np.asarray([face.confidence], dtype=np.float32),
            ))
            aligned = self._recognizer.alignCrop(face_bgr_or_frame, row)
            feat = self._recognizer.feature(aligned)
        else:
            # Direct feature extraction on pre-aligned or cropped 112x112 face image
            feat = self._recognizer.feature(face_bgr_or_frame)

        self.last_inference_ms = (perf_counter() - started) * 1000.0

        if feat is None:
            raise RuntimeError("SFace feature extraction failed")

        vector = np.asarray(feat, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 1e-12:
            return vector

        return vector / norm

    @staticmethod
    def similarity(first: np.ndarray, second: np.ndarray) -> float:
        """Compute cosine similarity score between two normalized feature vectors."""
        v1 = np.asarray(first, dtype=np.float32).reshape(-1)
        v2 = np.asarray(second, dtype=np.float32).reshape(-1)
        norm1 = float(np.linalg.norm(v1))
        norm2 = float(np.linalg.norm(v2))
        denominator = max(norm1 * norm2, 1e-12)
        return float(np.dot(v1, v2) / denominator)
