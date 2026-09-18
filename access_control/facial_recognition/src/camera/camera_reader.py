"""Configurable camera reader supporting Raspberry Pi 5 CSI (IMX219), V4L2/USB, RTSP, or files."""

from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

from .capture_backend import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    Picamera2Capture,
    detect_available_cameras,
    detect_csi_cameras,
    get_camera_candidates,
    is_picamera2_available,
    open_camera_capture,
    parse_camera_source,
)

logger = logging.getLogger(__name__)

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


class CameraReader:
    """Acquires video frames from CSI (IMX219), V4L2/USB webcams, RTSP streams, or files."""

    def __init__(
        self,
        source: str = "auto",
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
    ) -> None:
        self.source = source
        self.width = int(width)
        self.height = int(height)
        self.cap = None
        self.active_source: Optional[str | int] = None

    def open(self) -> None:
        logger.info("Opening camera with requested source '%s'", self.source)
        capture, active_src = open_camera_capture(
            source=self.source,
            width=self.width,
            height=self.height,
        )
        if capture is None:
            raise RuntimeError(f"Failed to open camera source: {self.source}")

        self.cap = capture
        self.active_source = active_src
        logger.info("Camera successfully active on source '%s'", self.active_source)

    def read(self) -> Tuple[bool, Optional[object]]:
        if self.cap is None:
            raise RuntimeError("Camera is not open")
        return self.cap.read()

    def release(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception as exc:
                logger.debug("Exception releasing camera capture: %s", exc)
            self.cap = None
            self.active_source = None

    @staticmethod
    def _opencv_source(source: str):
        """Legacy helper for backward-compatibility."""
        return parse_camera_source(source)
