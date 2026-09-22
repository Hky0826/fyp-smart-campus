"""Unified camera capture backend supporting Raspberry Pi 5 CSI (IMX219) and V4L2/USB."""

from __future__ import annotations

import glob
import logging
import os
import re
import time
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = int(os.getenv("EDGE_CAMERA_WIDTH", "1280"))
DEFAULT_HEIGHT = int(os.getenv("EDGE_CAMERA_HEIGHT", "720"))
DEFAULT_FPS = int(os.getenv("EDGE_CAMERA_FPS", "30"))
DEFAULT_PIXEL_FORMAT = os.getenv("EDGE_CAMERA_FORMAT", "RGB888").strip().upper()
DEFAULT_SWAP_RB = os.getenv("EDGE_CAMERA_SWAP_RB", "false").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_EXPOSURE_VALUE = float(os.getenv("EDGE_CAMERA_EV", "1.2"))
DEFAULT_BRIGHTNESS = float(os.getenv("EDGE_CAMERA_BRIGHTNESS", "0.1"))
DEFAULT_CONTRAST = float(os.getenv("EDGE_CAMERA_CONTRAST", "1.0"))

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


def sys_platform_is_linux() -> bool:
    """Check if current operating system is Linux."""
    return os.name == "posix" and hasattr(os, "uname") and os.uname().sysname.lower() == "linux"


def is_picamera2_available() -> bool:
    """Check if picamera2 library can be imported."""
    try:
        import picamera2  # noqa: F401
        return True
    except (ImportError, Exception):
        return False


def detect_csi_cameras() -> list[dict[str, Any]]:
    """Query libcamera via Picamera2 to detect connected CSI sensors (e.g. IMX219)."""
    if not is_picamera2_available():
        return []
    try:
        from picamera2 import Picamera2
        info = Picamera2.global_camera_info()
        if isinstance(info, list):
            logger.info("Picamera2 detected %d CSI camera(s): %s", len(info), info)
            return info
    except Exception as exc:
        logger.debug("Picamera2 camera detection query failed: %s", exc)
    return []


def detect_v4l2_devices() -> list[str]:
    """Scan and return available Linux /dev/video* capture device paths."""
    if not sys_platform_is_linux():
        return []

    devices = glob.glob("/dev/video*")
    # Sort naturally by video index: /dev/video0, /dev/video1, ..., /dev/video10
    def _video_idx(path: str) -> int:
        digits = re.findall(r"\d+", path)
        return int(digits[-1]) if digits else 999

    devices.sort(key=_video_idx)

    # Filter/prioritize UVC USB webcams over raw RP1 ISP nodes if sysfs is available
    uvc_devices: list[str] = []
    other_devices: list[str] = []

    for dev in devices:
        dev_name = os.path.basename(dev)
        driver_path = f"/sys/class/video4linux/{dev_name}/device/driver"
        name_path = f"/sys/class/video4linux/{dev_name}/name"
        is_uvc = False
        try:
            if os.path.islink(driver_path) and "uvcvideo" in os.readlink(driver_path):
                is_uvc = True
        except OSError:
            pass

        if not is_uvc:
            try:
                if os.path.isfile(name_path):
                    with open(name_path, "r", encoding="utf-8", errors="ignore") as f:
                        name_content = f.read().lower()
                        # RP1 raw CSI nodes on RPi 5 typically contain rp1-csi2 or pisp
                        if "rp1" in name_content or "pisp" in name_content:
                            continue  # Skip raw RP1 subnodes to avoid V4L2 format errors
            except OSError:
                pass

        if is_uvc:
            uvc_devices.append(dev)
        else:
            other_devices.append(dev)

    return uvc_devices + other_devices


class Picamera2Capture:
    """OpenCV VideoCapture-compatible wrapper around picamera2 for Raspberry Pi 5 CSI cameras."""

    def __init__(
        self,
        camera_idx: int = 0,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        fps: int = DEFAULT_FPS,
        pixel_format: str = DEFAULT_PIXEL_FORMAT,
        swap_rb: bool = DEFAULT_SWAP_RB,
        exposure_value: float = DEFAULT_EXPOSURE_VALUE,
        brightness: float = DEFAULT_BRIGHTNESS,
        contrast: float = DEFAULT_CONTRAST,
    ) -> None:
        self.camera_idx = int(camera_idx)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.pixel_format = str(pixel_format).strip().upper()
        self.swap_rb = bool(swap_rb)
        self.exposure_value = float(exposure_value)
        self.brightness = float(brightness)
        self.contrast = float(contrast)
        self._picam2 = None
        self._opened = False
        self._camera_model = "unknown"
        self._open()

    def _open(self) -> None:
        try:
            from picamera2 import Picamera2
            self._picam2 = Picamera2(camera_num=self.camera_idx)
            # Query detected model name if available
            try:
                info = Picamera2.global_camera_info()
                if info and len(info) > self.camera_idx:
                    self._camera_model = info[self.camera_idx].get("Model", "CSI Camera")
            except Exception:
                pass

            # In Picamera2 / libcamera:
            # - 'RGB888' outputs memory byte order [B, G, R], which directly matches OpenCV's native BGR format.
            # - 'BGR888' outputs memory byte order [R, G, B].
            controls: dict[str, Any] = {}
            if self.fps:
                controls["FrameRate"] = self.fps
            if self.exposure_value != 0.0:
                controls["ExposureValue"] = self.exposure_value
            if self.brightness != 0.0:
                controls["Brightness"] = self.brightness
            if self.contrast != 1.0:
                controls["Contrast"] = self.contrast

            video_config = self._picam2.create_video_configuration(
                main={"format": self.pixel_format, "size": (self.width, self.height)},
                controls=controls,
            )
            self._picam2.configure(video_config)
            self._picam2.start()
            if controls:
                try:
                    self._picam2.set_controls(controls)
                except Exception as exc:
                    logger.debug("set_controls failed: %s", exc)
            # Allow AEC (auto-exposure) and AWB (auto-white-balance) to converge
            time.sleep(0.5)
            self._opened = True
            logger.info(
                "Picamera2 CSI camera %d (%s) initialized at %dx%d @ %dfps (format=%s, swap_rb=%s, ev=%.1f, brightness=%.2f)",
                self.camera_idx,
                self._camera_model,
                self.width,
                self.height,
                self.fps,
                self.pixel_format,
                self.swap_rb,
                self.exposure_value,
                self.brightness,
            )
        except Exception as exc:
            logger.warning("Failed to open Picamera2 CSI camera %d: %s", self.camera_idx, exc)
            self.release()

    def isOpened(self) -> bool:  # noqa: N802 - OpenCV API compliance
        return self._opened and self._picam2 is not None

    def read(self) -> Tuple[bool, Optional[Any]]:
        if not self.isOpened():
            return False, None
        try:
            frame = self._picam2.capture_array("main")
            if frame is None or frame.size == 0:
                return False, None
            if self.swap_rb:
                frame = frame[:, :, ::-1]
            return True, frame
        except Exception as exc:
            logger.error("Picamera2 frame capture failed: %s", exc)
            return False, None

    def release(self) -> None:
        if self._picam2 is not None:
            try:
                self._picam2.stop()
            except Exception:
                pass
            try:
                self._picam2.close()
            except Exception:
                pass
            self._picam2 = None
        self._opened = False

    def get(self, prop_id: int) -> float:
        if cv2 is not None:
            if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
                return float(self.width)
            if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
                return float(self.height)
            if prop_id == cv2.CAP_PROP_FPS:
                return float(self.fps)
        return 0.0

    def set(self, prop_id: int, value: float) -> bool:
        # Accept width/height/fps property changes gracefully
        return True

    @property
    def camera_model(self) -> str:
        return self._camera_model


def parse_camera_source(source: str | int) -> str | int:
    """Normalize camera string identifiers (e.g. '/dev/video4' -> 4, '0' -> 0)."""
    s = str(source).strip()
    if s.startswith("/dev/video"):
        suffix = s.replace("/dev/video", "")
        if suffix.isdigit():
            return int(suffix)
    if s.isdigit():
        return int(s)
    return source


def get_camera_candidates(
    primary_source: str | int | None = None,
    allow_fallbacks: bool = True,
) -> list[str | int]:
    """Build an ordered list of camera candidates for auto-detection and fallback.

    Priority order when source is 'auto' (or unspecified):
      1. Detected CSI cameras via Picamera2 (e.g. 'csi:0' or 'csi')
      2. Detected V4L2 USB devices (e.g. /dev/video4, /dev/video0)
      3. Standard numeric indices (0, 1)

    When an explicit source is configured (e.g. '/dev/video4', 'csi', 0):
      1. Explicit source is always tested first
      2. If allow_fallbacks is True, other detected/fallback devices are appended
    """
    candidates: list[str | int] = []

    def _add(item: str | int) -> None:
        norm = parse_camera_source(item)
        if norm not in candidates and item not in candidates:
            candidates.append(norm)

    configured_raw = str(primary_source or "").strip()
    is_auto = not configured_raw or configured_raw.lower() in {"auto", "default", "none", "detect"}

    # Probe CSI cameras
    csi_detected = detect_csi_cameras()
    csi_candidates: list[str] = []
    if csi_detected:
        for idx in range(len(csi_detected)):
            csi_candidates.append(f"csi:{idx}")
    elif is_picamera2_available() and sys_platform_is_linux():
        csi_candidates.append("csi:0")

    # If explicit non-auto source was specified, prioritize it
    if not is_auto:
        if configured_raw.lower() in {"csi", "picam", "picamera", "picamera2", "imx219"}:
            _add("csi:0")
        else:
            _add(configured_raw)

    # When auto-detecting, CSI is preferred on Raspberry Pi 5
    if is_auto:
        for csi_dev in csi_candidates:
            _add(csi_dev)

    if not allow_fallbacks and not is_auto:
        return candidates

    # Add discovered V4L2 devices
    for vdev in detect_v4l2_devices():
        _add(vdev)

    # If explicit source was given, add CSI as fallback if not already in list
    for csi_dev in csi_candidates:
        _add(csi_dev)

    # Standard fallback devices
    standard_fallbacks = os.getenv(
        "EDGE_CAMERA_FALLBACKS",
        "/dev/video4,/dev/video0,/dev/video1,/dev/video2,/dev/video3,0,1",
    )
    for item in standard_fallbacks.split(","):
        val = item.strip()
        if val:
            _add(val)

    return candidates


detect_available_cameras = get_camera_candidates


def open_single_capture(
    source: str | int,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    fourcc: str = "MJPG",
    pixel_format: str = DEFAULT_PIXEL_FORMAT,
    swap_rb: bool = DEFAULT_SWAP_RB,
    exposure_value: float = DEFAULT_EXPOSURE_VALUE,
    brightness: float = DEFAULT_BRIGHTNESS,
    contrast: float = DEFAULT_CONTRAST,
) -> Optional[Any]:
    """Attempt to open a single camera source (either CSI or OpenCV V4L2/stream)."""
    src_str = str(source).strip().lower()

    # 1. CSI / Picamera2 backend
    if src_str.startswith("csi") or src_str in {"picam", "picamera", "picamera2", "imx219"}:
        camera_idx = 0
        if ":" in src_str:
            parts = src_str.split(":", 1)
            if parts[1].isdigit():
                camera_idx = int(parts[1])
        capture = Picamera2Capture(
            camera_idx=camera_idx,
            width=width,
            height=height,
            fps=fps,
            pixel_format=pixel_format,
            swap_rb=swap_rb,
            exposure_value=exposure_value,
            brightness=brightness,
            contrast=contrast,
        )
        if capture.isOpened():
            return capture
        capture.release()
        return None

    # 2. OpenCV VideoCapture backend (V4L2, USB, RTSP, Video File)
    if cv2 is None:
        logger.error("OpenCV (cv2) is not installed; cannot open V4L2/USB camera source %s", source)
        return None

    parsed_src = parse_camera_source(source)
    backends: list[Optional[int]] = []

    if isinstance(parsed_src, str) and "!" in parsed_src and hasattr(cv2, "CAP_GSTREAMER"):
        backends.append(cv2.CAP_GSTREAMER)
    if sys_platform_is_linux() and isinstance(parsed_src, int) and hasattr(cv2, "CAP_V4L2"):
        backends.append(cv2.CAP_V4L2)
    backends.append(None)

    for backend in backends:
        try:
            cap = cv2.VideoCapture(parsed_src) if backend is None else cv2.VideoCapture(parsed_src, backend)
        except Exception as exc:
            logger.debug("VideoCapture open exception with backend %s for %s: %s", backend, source, exc)
            continue

        if not cap.isOpened():
            cap.release()
            continue

        if isinstance(parsed_src, int):
            try:
                if fourcc and fourcc.upper() not in {"NONE", "AUTO", "DEFAULT"} and len(fourcc) == 4:
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc.upper()))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                cap.set(cv2.CAP_PROP_FPS, fps)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception as prop_err:
                logger.debug("Failed to set camera properties on %s: %s", source, prop_err)
            time.sleep(0.5)

        return cap

    return None


def open_camera_capture(
    source: str | int | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    allow_fallbacks: bool = True,
    test_frames: int = 3,
) -> Tuple[Optional[Any], Optional[str | int]]:
    """Open a camera using auto-detection and graceful fallback.

    Tests candidate sources by reading test frames to ensure working streaming.
    Returns:
      (active_capture_object, active_source_identifier) or (None, None)
    """
    candidates = get_camera_candidates(source, allow_fallbacks=allow_fallbacks)
    logger.info("Probing camera candidates in order: %s", candidates)

    for candidate in candidates:
        capture = open_single_capture(candidate, width=width, height=height, fps=fps)
        if capture is None:
            continue

        # Test frame reading to verify sensor actively returns frames
        verified = False
        for _ in range(max(1, test_frames)):
            ok, frame = capture.read()
            if ok and frame is not None:
                verified = True
                break
            time.sleep(0.05)

        if verified:
            source_desc = f"CSI (index {getattr(capture, 'camera_idx', 0)}, model: {getattr(capture, 'camera_model', 'IMX219')})" if isinstance(capture, Picamera2Capture) else f"OpenCV source: {candidate}"
            logger.info("Successfully connected to active camera: %s", source_desc)
            return capture, candidate

        logger.warning("Camera candidate %s opened but failed frame verification; releasing", candidate)
        capture.release()

    return None, None
