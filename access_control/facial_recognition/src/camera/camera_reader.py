"""Configurable OpenCV camera, RTSP, or video-file reader."""

from __future__ import annotations

import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = int(os.getenv("EDGE_CAMERA_WIDTH", "1280"))
DEFAULT_HEIGHT = int(os.getenv("EDGE_CAMERA_HEIGHT", "720"))

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


class CameraReader:
    def __init__(self, source: str = "/dev/video4", width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> None:
        self.source = source
        self.width = int(width)
        self.height = int(height)
        self.cap = None

    def open(self) -> None:
        if cv2 is None:
            raise RuntimeError("OpenCV is required for camera input")
        source = self._opencv_source(self.source)
        logger.info("Initializing camera source %s", self.source)
        if isinstance(source, int) and hasattr(cv2, "CAP_V4L2"):
            self.cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
            if not self.cap.isOpened():
                logger.warning("V4L2 camera open failed for %s; retrying with default backend", self.source)
                self.cap.release()
                self.cap = cv2.VideoCapture(source)
        else:
            self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera source: {self.source}")

        if isinstance(source, int):
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            time.sleep(1.0)

    def read(self) -> Tuple[bool, Optional[object]]:
        if self.cap is None:
            raise RuntimeError("Camera is not open")
        return self.cap.read()

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    @staticmethod
    def _opencv_source(source: str):
        if source.startswith("/dev/video"):
            suffix = source.replace("/dev/video", "")
            if suffix.isdigit():
                return int(suffix)
        if source.isdigit():
            return int(source)
        return source
