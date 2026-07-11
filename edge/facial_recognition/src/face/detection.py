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
        log_empty_detections: bool = True,
        nms_iou_threshold: float = 0.4,
        min_box_size: float = 16.0,
        max_box_size_ratio: float = 0.95,
        box_expansion_ratio: float = 0.0,
        runner: HailoModelRunner | None = None,
    ) -> None:
        self.runner = runner or HailoModelRunner(hef_path)
        self.input_size = input_size
        self.confidence_threshold = float(confidence_threshold)
        self.log_empty_detections = log_empty_detections
        self.nms_iou_threshold = float(nms_iou_threshold)
        self.min_box_size = float(min_box_size)
        self.max_box_size_ratio = float(max_box_size_ratio)
        self.box_expansion_ratio = float(box_expansion_ratio)
        self._empty_detection_warnings = 0

    def detect(self, frame: np.ndarray) -> List[DetectedFace]:
        tensor, metadata = preprocess_scrfd(frame, self.input_size, return_metadata=True)
        outputs = self.runner.infer(tensor)
        faces = postprocess_scrfd(
            outputs,
            original_shape=frame.shape[:2],
            input_size=self.input_size,
            confidence_threshold=self.confidence_threshold,
            nms_iou_threshold=self.nms_iou_threshold,
            metadata=metadata,
            min_box_size=self.min_box_size,
            max_box_size_ratio=self.max_box_size_ratio,
            box_expansion_ratio=self.box_expansion_ratio,
        )
        if self.log_empty_detections and not faces and self._empty_detection_warnings < 3:
            self._empty_detection_warnings += 1
            logger.warning(
                "SCRFD found no faces above threshold %.2f. Hailo output summary: %s",
                self.confidence_threshold,
                summarize_outputs(outputs),
            )
        return faces
