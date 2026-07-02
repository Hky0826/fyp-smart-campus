"""Hailo ArcFace embedding adapter."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..hailo.hailo_runner import HailoModelRunner
from ..hailo.preprocess import preprocess_arcface


class HailoArcFaceEmbedder:
    def __init__(self, hef_path: str | Path, runner: HailoModelRunner | None = None) -> None:
        self.runner = runner or HailoModelRunner(hef_path)

    def embed(self, face_bgr: np.ndarray) -> np.ndarray:
        tensor = preprocess_arcface(face_bgr)
        outputs = self.runner.infer(tensor)
        if not outputs:
            raise RuntimeError("ArcFace HEF returned no outputs")
        embedding = np.asarray(next(iter(outputs.values())), dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(embedding))
        if norm <= 1e-12:
            return embedding
        return embedding / norm
