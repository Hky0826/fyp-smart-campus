"""YuNet face detector wrapper."""

from __future__ import annotations

import cv2
import numpy as np
from typing import Tuple, Optional


class YuNetDetector:
    def __init__(self, model_path: str, input_size: Tuple[int, int] = (640, 480)):
        self.model_path = model_path
        self.input_size = (int(input_size[0]), int(input_size[1]))
        self.detector = cv2.FaceDetectorYN.create(model_path, '', self.input_size, 0.6, 0.4, 1)

    def set_input_size(self, size: Tuple[int, int]) -> None:
        self.input_size = (int(size[0]), int(size[1]))
        self.detector.setInputSize(self.input_size)

    def detect(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Detect faces on a downsampled frame. Returns faces array or None."""
        # Caller should provide a frame matching input_size
        try:
            retval, faces = self.detector.detect(frame)
            return faces
        except Exception:
            return None
