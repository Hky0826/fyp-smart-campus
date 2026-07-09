"""Camera capture worker and QML image provider."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Property, QThread, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

try:
    import cv2
except Exception:  # pragma: no cover - depends on target image
    cv2 = None


DEFAULT_CAMERA = "/dev/video4"
JPEG_QUALITY = 82
DEFAULT_CAMERA_FALLBACKS = "/dev/video0,/dev/video1,/dev/video2,/dev/video3,/dev/video4,/dev/video5,0,1"


def _camera_source(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def _camera_candidates(camera: str) -> list[str | int]:
    configured = camera.strip()
    candidates: list[str | int] = [_camera_source(configured)]
    if os.getenv("EDGE_GUI_CAMERA_NO_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}:
        return candidates

    fallback_text = os.getenv("EDGE_GUI_CAMERA_FALLBACKS", DEFAULT_CAMERA_FALLBACKS)
    for item in fallback_text.split(","):
        value = item.strip()
        if not value:
            continue
        source = _camera_source(value)
        if source not in candidates:
            candidates.append(source)
    return candidates


def _open_capture(source: str | int) -> Any:
    if cv2 is None:
        return None

    backends: list[int | None] = []
    if isinstance(source, str) and "!" in source and hasattr(cv2, "CAP_GSTREAMER"):
        backends.append(cv2.CAP_GSTREAMER)
    if sys_platform_is_linux() and hasattr(cv2, "CAP_V4L2"):
        backends.append(cv2.CAP_V4L2)
    backends.append(None)

    for backend in backends:
        capture = cv2.VideoCapture(source) if backend is None else cv2.VideoCapture(source, backend)
        if not capture.isOpened():
            capture.release()
            continue
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return capture
    return None


def sys_platform_is_linux() -> bool:
    return os.name == "posix" and os.uname().sysname.lower() == "linux" if hasattr(os, "uname") else False


class CameraImageProvider(QQuickImageProvider):
    """Thread-safe provider for the latest camera frame."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.Image)
        self._lock = threading.Lock()
        self._image = QImage(1280, 720, QImage.Format_RGB32)
        self._image.fill(0x020617)

    def update_image(self, image: QImage) -> None:
        with self._lock:
            self._image = image.copy()

    def requestImage(self, _id: str, size: Any, requested_size: Any) -> QImage:  # noqa: N802 - Qt API
        with self._lock:
            image = self._image.copy()
        size.setWidth(image.width())
        size.setHeight(image.height())
        if requested_size.isValid():
            return image.scaled(requested_size)
        return image


class CameraCaptureThread(QThread):
    frameReady = Signal(int, int, int)
    readyChanged = Signal(bool)
    errorChanged = Signal(str)

    def __init__(self, provider: CameraImageProvider, cameras: list[str | int]) -> None:
        super().__init__()
        self._provider = provider
        self._cameras = cameras
        self._running = False
        self._latest_jpeg = b""
        self._jpeg_lock = threading.Lock()

    def run(self) -> None:
        if cv2 is None:
            self.errorChanged.emit("OpenCV is required for camera capture.")
            self.readyChanged.emit(False)
            return

        capture, _active_camera = self._connect_camera()
        if capture is None:
            tried = ", ".join(str(camera) for camera in self._cameras)
            self.errorChanged.emit(
                "Camera is unavailable. Tried: "
                f"{tried}. Check EDGE_GUI_CAMERA, camera permissions, and whether another process is using the device."
            )
            self.readyChanged.emit(False)
            return

        self._running = True
        self.readyChanged.emit(True)
        self.errorChanged.emit("")
        counter = 0
        try:
            while self._running:
                ok, frame = capture.read()
                if not ok or frame is None:
                    self.errorChanged.emit("Camera frame capture failed.")
                    time.sleep(0.1)
                    continue

                height, width = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                qimage = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format_RGB888).copy()
                self._provider.update_image(qimage)

                encoded_ok, encoded = cv2.imencode(
                    ".jpg",
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
                )
                if encoded_ok:
                    with self._jpeg_lock:
                        self._latest_jpeg = encoded.tobytes()

                counter += 1
                self.frameReady.emit(counter, width, height)
                self.msleep(16)
        finally:
            capture.release()
            self.readyChanged.emit(False)

    def stop(self) -> None:
        self._running = False

    def latest_jpeg(self) -> bytes:
        with self._jpeg_lock:
            return bytes(self._latest_jpeg)

    def _connect_camera(self) -> tuple[Any | None, str | int | None]:
        for camera in self._cameras:
            capture = _open_capture(camera)
            if capture is None:
                continue

            for _ in range(5):
                ok, frame = capture.read()
                if ok and frame is not None:
                    return capture, camera
                self.msleep(50)
            capture.release()
        return None, None


class CameraController(QObject):
    sourceUrlChanged = Signal()
    readyChanged = Signal()
    errorChanged = Signal()
    videoSizeChanged = Signal()

    def __init__(self, provider: CameraImageProvider) -> None:
        super().__init__()
        camera = os.getenv("EDGE_GUI_CAMERA") or os.getenv("EDGE_ACCESS_CAMERA") or os.getenv("EDGE_CAMERA") or DEFAULT_CAMERA
        self._provider = provider
        self._thread = CameraCaptureThread(provider, _camera_candidates(camera))
        self._source_url = "image://camera/frame?0"
        self._ready = False
        self._error = ""
        self._video_width = 0
        self._video_height = 0
        self._thread.frameReady.connect(self._on_frame_ready)
        self._thread.readyChanged.connect(self._set_ready)
        self._thread.errorChanged.connect(self._set_error)

    @Slot()
    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()

    @Slot()
    def stop(self) -> None:
        if self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(1500)

    def latest_jpeg(self) -> bytes:
        return self._thread.latest_jpeg()

    @Slot(int, int, int)
    def _on_frame_ready(self, counter: int, width: int, height: int) -> None:
        self._source_url = f"image://camera/frame?{counter}"
        self.sourceUrlChanged.emit()
        if width != self._video_width or height != self._video_height:
            self._video_width = width
            self._video_height = height
            self.videoSizeChanged.emit()

    @Slot(bool)
    def _set_ready(self, ready: bool) -> None:
        if ready == self._ready:
            return
        self._ready = ready
        self.readyChanged.emit()

    @Slot(str)
    def _set_error(self, error: str) -> None:
        if error == self._error:
            return
        self._error = error
        self.errorChanged.emit()

    def _get_source_url(self) -> str:
        return self._source_url

    def _get_ready(self) -> bool:
        return self._ready

    def _get_error(self) -> str:
        return self._error

    def _get_video_width(self) -> int:
        return self._video_width

    def _get_video_height(self) -> int:
        return self._video_height

    sourceUrl = Property(str, _get_source_url, notify=sourceUrlChanged)
    ready = Property(bool, _get_ready, notify=readyChanged)
    error = Property(str, _get_error, notify=errorChanged)
    videoWidth = Property(int, _get_video_width, notify=videoSizeChanged)
    videoHeight = Property(int, _get_video_height, notify=videoSizeChanged)
