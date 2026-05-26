"""Camera capture class for V4L2 with MJPG protection."""

from __future__ import annotations

import time
import cv2
from typing import Tuple


class CameraCapture:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480):
        self.index = index
        self.width = int(width)
        self.height = int(height)
        self.cap = None

    def open(self) -> None:
        self.cap = cv2.VideoCapture(self.index, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera at index {self.index}")

        # Set MJPG FOURCC before requesting high resolution
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        time.sleep(2.0)

    def read(self):
        if self.cap is None:
            raise RuntimeError("Camera not opened")
        ret, frame = self.cap.read()
        return ret, frame

    def release(self) -> None:
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
