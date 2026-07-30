"""Camera reader utility supporting camera index, RTSP URL, or video files."""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

logger = logging.getLogger(__name__)


class CameraReader:
    """Thread-safe or basic camera frame acquisition supporting V4L2, RTSP, and video files."""

    def __init__(self, src: str | int = 0, width: int = 1920, height: int = 1080) -> None:
        self.src = src
        self.width = int(width)
        self.height = int(height)
        self.cap: Optional[Any] = None

    @staticmethod
    def _parse_source(src: str | int) -> str | int:
        s = str(src).strip()
        if s.startswith("/dev/video"):
            suffix = s.replace("/dev/video", "")
            if suffix.isdigit():
                return int(suffix)
        if s.isdigit():
            return int(s)
        return src

    def open(self) -> bool:
        if cv2 is None:
            logger.warning("OpenCV cv2 module not installed; camera cannot open physical capture device")
            return False

        source = self._parse_source(self.src)
        logger.info("Initializing camera source %s (parsed=%r)", self.src, source)

        try:
            if isinstance(source, int) and hasattr(cv2, "CAP_V4L2"):
                self.cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
                if not self.cap.isOpened():
                    logger.warning("V4L2 backend open failed for %s; retrying default backend", self.src)
                    self.cap.release()
                    self.cap = cv2.VideoCapture(source)
            else:
                self.cap = cv2.VideoCapture(source)

            if not self.cap.isOpened():
                logger.error("Failed to open camera source: %s", self.src)
                return False

            if isinstance(source, int):
                try:
                    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
                    self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception as prop_err:
                    logger.warning("Failed setting camera properties: %s", prop_err)

                time.sleep(0.5)

            logger.info("Successfully opened camera source: %s", self.src)
            return True
        except Exception as exc:
            logger.error("Exception opening camera source %s: %s", self.src, exc)
            return False

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or cv2 is None:
            return False, None
        return self.cap.read()

    def read_latest(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Flush stale buffered frames and retrieve the most recent frame."""
        if self.cap is None or cv2 is None:
            return False, None
        # Grab frames to empty buffer queue
        for _ in range(2):
            if not self.cap.grab():
                break
        return self.cap.retrieve()

    def release(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
