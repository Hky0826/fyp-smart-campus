"""AuraFace face embedding adapter for Hailo HEF models."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

from .loader import HailoModelRunner, BaseHailoRunner

logger = logging.getLogger(__name__)


class AuraFaceEmbedder:
    """Extracts 512-dimensional face embeddings using AuraFace model."""

    def __init__(
        self,
        hef_path: str | Path,
        input_size: Tuple[int, int] = (112, 112),
        runner: Optional[BaseHailoRunner] = None,
    ) -> None:
        self.hef_path = Path(hef_path)
        self.input_size = input_size
        self.runner = runner or HailoModelRunner(self.hef_path, allow_mock=True)

    def preprocess(self, aligned_face_bgr: np.ndarray) -> np.ndarray:
        """Preprocess aligned face image to AuraFace float32 input tensor."""
        if cv2 is not None and aligned_face_bgr.shape[:2] != self.input_size:
            resized = cv2.resize(aligned_face_bgr, self.input_size, interpolation=cv2.INTER_LINEAR)
        else:
            resized = aligned_face_bgr

        if cv2 is not None and resized.shape[-1] == 3:
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        else:
            rgb = resized

        # Hailo HEFs from Hailo Model Zoo include normalization (mean/std 127.5) inside net graph
        tensor = rgb.astype(np.float32)

        # Check tensor format expected by runner (NCHW vs NHWC)
        if len(getattr(self.runner, "input_shape", ())) == 4 and self.runner.input_shape[1] == 3:
            tensor = tensor.transpose(2, 0, 1)  # NHWC -> NCHW

        return np.expand_dims(tensor, axis=0)

    def embed(self, aligned_face_bgr: np.ndarray) -> np.ndarray:
        """Runs AuraFace embedder and returns normalized 512-d float32 vector."""
        if aligned_face_bgr is None or aligned_face_bgr.size == 0:
            raise ValueError("Empty face image provided to AuraFace embedder")

        tensor = self.preprocess(aligned_face_bgr)
        outputs = self.runner.infer(tensor)

        if not outputs:
            raise RuntimeError("AuraFace HEF model returned no outputs")

        raw = next(iter(outputs.values()))
        embedding = np.asarray(raw, dtype=np.float32).reshape(-1)

        norm = float(np.linalg.norm(embedding))
        if norm <= 1e-12:
            return embedding
        return embedding / norm
