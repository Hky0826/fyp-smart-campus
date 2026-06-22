"""Hailo SCRFD detector adapter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import numpy as np

from ..hailo.hailo_runner import HailoModelRunner
from ..hailo.postprocess_scrfd import postprocess_scrfd, summarize_outputs
from ..hailo.preprocess import preprocess_scrfd
from .types import DetectedFace


logger = logging.getLogger(__name__)


class HailoSCRFDDetector:
    def __init__(
        self,
        hef_path: str | Path,
        input_size: Tuple[int, int] = (640, 640),
        confidence_threshold: float = 0.6,
        runner: HailoModelRunner | None = None,
    ) -> None:
        self.runner = runner or HailoModelRunner(hef_path)
        self.input_size = input_size
        self.confidence_threshold = float(confidence_threshold)
        self._empty_detection_warnings = 0

    def detect(self, frame: np.ndarray) -> List[DetectedFace]:
        tensor = preprocess_scrfd(frame, self.input_size)
        outputs = self.runner.infer(tensor)
        faces = postprocess_scrfd(
            outputs,
            original_shape=frame.shape[:2],
            input_size=self.input_size,
            confidence_threshold=self.confidence_threshold,
        )
        if not faces and self._empty_detection_warnings < 3:
            self._empty_detection_warnings += 1
            logger.warning(
                "SCRFD found no faces above threshold %.2f. Hailo output summary: %s",
                self.confidence_threshold,
                summarize_outputs(outputs),
            )
        return faces
