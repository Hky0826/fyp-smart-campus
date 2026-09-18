"""Camera capture worker and QML image provider supporting CSI IMX219 and V4L2/USB."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

try:
    from PySide6.QtCore import QObject, Property, QThread, Signal, Slot
    from PySide6.QtGui import QImage
    from PySide6.QtQuick import QQuickImageProvider
except ImportError:  # pragma: no cover - headless/test environments
    class QObject:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def setParent(self, parent): pass
    class QThread:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def isRunning(self): return False
        def start(self): pass
        def stop(self): pass
        def wait(self, *args): pass
        def msleep(self, ms): time.sleep(ms / 1000.0)
    class QQuickImageProvider:  # type: ignore[no-redef]
        Image = None
        def __init__(self, *args, **kwargs): pass
    class QImage:  # type: ignore[no-redef]
        Format_RGB32 = None
        Format_RGB888 = None
        def __init__(self, *args, **kwargs): pass
        def fill(self, *args): pass
        def copy(self): return self
        def width(self): return 1280
        def height(self): return 720
    def Signal(*args, **kwargs):  # type: ignore[no-redef]
        class _Signal:
            def emit(self, *a, **kw): pass
            def connect(self, *a, **kw): pass
        return _Signal()
    def Slot(*args, **kwargs):  # type: ignore[no-redef]
        return lambda f: f
    def Property(*args, **kwargs):  # type: ignore[no-redef]
        return property(args[1] if len(args) > 1 else None)

logger = logging.getLogger(__name__)

try:
    import cv2
except Exception:  # pragma: no cover - depends on target image
    cv2 = None

try:
    from access_control.facial_recognition.src.camera.capture_backend import (
        Picamera2Capture,
        detect_available_cameras,
        detect_csi_cameras,
        get_camera_candidates,
        open_single_capture,
        parse_camera_source,
    )
except ImportError:  # pragma: no cover
    Picamera2Capture = None
    detect_available_cameras = None
    detect_csi_cameras = None
    get_camera_candidates = None
    open_single_capture = None
    parse_camera_source = None


DEFAULT_CAMERA = "auto"
JPEG_QUALITY = 82
DEFAULT_CAMERA_FALLBACKS = "csi,/dev/video4,/dev/video0,/dev/video1,/dev/video2,/dev/video3,0,1"
DEFAULT_CAMERA_WIDTH = 1280
DEFAULT_CAMERA_HEIGHT = 720
DEFAULT_CAMERA_FOURCC = "MJPG"


def _camera_source(value: str) -> str | int:
    if parse_camera_source is not None:
        return parse_camera_source(value)
    if value.startswith("/dev/video"):
        suffix = value.replace("/dev/video", "")
        if suffix.isdigit():
            return int(suffix)
    return int(value) if value.isdigit() else value


def _camera_candidates(camera: str) -> list[str | int]:
    configured = (camera or "").strip()
    allow_fallbacks = os.getenv("EDGE_GUI_CAMERA_NO_FALLBACK", "").strip().lower() not in {"1", "true", "yes", "on"}

    if get_camera_candidates is not None:
        return get_camera_candidates(configured, allow_fallbacks=allow_fallbacks)

    candidates: list[str | int] = [_camera_source(configured)] if configured and configured.lower() != "auto" else []
    if not allow_fallbacks:
        return candidates or [0]

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
    width = int(os.getenv("EDGE_GUI_CAMERA_WIDTH", str(DEFAULT_CAMERA_WIDTH)))
    height = int(os.getenv("EDGE_GUI_CAMERA_HEIGHT", str(DEFAULT_CAMERA_HEIGHT)))
    fourcc_name = os.getenv("EDGE_GUI_CAMERA_FOURCC", DEFAULT_CAMERA_FOURCC).strip()

    if open_single_capture is not None:
        return open_single_capture(source, width=width, height=height, fourcc=fourcc_name)

    # Local fallback if capture_backend is not imported
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
        _configure_capture(capture, source)
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return capture
    return None


def _configure_capture(capture: Any, source: str | int) -> None:
    if cv2 is None or not isinstance(source, int):
        return
    width = int(os.getenv("EDGE_GUI_CAMERA_WIDTH", str(DEFAULT_CAMERA_WIDTH)))
    height = int(os.getenv("EDGE_GUI_CAMERA_HEIGHT", str(DEFAULT_CAMERA_HEIGHT)))
    fourcc_name = os.getenv("EDGE_GUI_CAMERA_FOURCC", DEFAULT_CAMERA_FOURCC).strip().upper()
    if fourcc_name and fourcc_name not in {"NONE", "DEFAULT", "AUTO"}:
        if len(fourcc_name) != 4:
            raise RuntimeError("EDGE_GUI_CAMERA_FOURCC must be a 4-character code, or NONE")
        fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
        capture.set(cv2.CAP_PROP_FOURCC, fourcc)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    time.sleep(0.5)


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

        capture, active_camera = self._connect_camera()
        if capture is None:
            tried = ", ".join(str(camera) for camera in self._cameras)
            self.errorChanged.emit(
                "Camera is unavailable. Tried: "
                f"{tried}. Check EDGE_GUI_CAMERA, camera permissions, and whether another process is using the device."
            )
            self.readyChanged.emit(False)
            return

        logger.info("Camera capture started on active device: %s", active_camera)
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
