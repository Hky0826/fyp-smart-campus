"""Camera reader utility supporting V4L2, ADB Android Camera2 (scrcpy-server), RTSP/HTTP URLs, or video files."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

logger = logging.getLogger(__name__)

SCRCPY_VERSION = "3.1"
SCRCPY_REMOTE_JAR = "/data/local/tmp/scrcpy-server.jar"
SCRCPY_LOCAL_PORT = 27183
SCRCPY_DEFAULT_WIDTH = 640
SCRCPY_DEFAULT_HEIGHT = 480
SCRCPY_DEFAULT_FPS = 24
SCRCPY_DEFAULT_BITRATE = 1500000
SCRCPY_LOCAL_JAR = Path(__file__).resolve().parent / f"scrcpy-server-v{SCRCPY_VERSION}"
SCRCPY_FALLBACK_JAR = Path.home() / ".local" / "share" / "scrcpy" / f"scrcpy-server-v{SCRCPY_VERSION}"


def _default_adb_swap_rb() -> bool:
    val = os.getenv("SURVEILLANCE_ADB_SWAP_RB", "1").strip().lower()
    return val in {"1", "true", "yes", "on"}


class AdbCameraSession:
    """Manages an ADB scrcpy-server Camera2 raw H.264 stream over a forwarded TCP socket."""

    def __init__(
        self,
        camera_id: str = "0",
        width: int = SCRCPY_DEFAULT_WIDTH,
        height: int = SCRCPY_DEFAULT_HEIGHT,
        fps: int = SCRCPY_DEFAULT_FPS,
        bitrate: int = SCRCPY_DEFAULT_BITRATE,
        port: int = SCRCPY_LOCAL_PORT,
    ) -> None:
        self.camera_id = camera_id
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.bitrate = int(bitrate)
        self.port = int(port)
        self._proc: Optional[subprocess.Popen[str]] = None

    @property
    def stream_url(self) -> str:
        return f"tcp://127.0.0.1:{self.port}"

    @staticmethod
    def _resolve_server_jar() -> Optional[Path]:
        for candidate in (SCRCPY_LOCAL_JAR, SCRCPY_FALLBACK_JAR):
            if candidate.is_file():
                return candidate
        return None

    def start(self) -> bool:
        jar = self._resolve_server_jar()
        if jar is None:
            logger.error("scrcpy-server-v%s not found at %s", SCRCPY_VERSION, SCRCPY_LOCAL_JAR)
            return False

        try:
            devices = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            connected = any(
                line.strip().endswith("\tdevice")
                for line in devices.stdout.splitlines()[1:]
            )
            if not connected:
                logger.error("No authorized ADB Android device detected")
                return False

            subprocess.run(
                ["adb", "shell", "pkill -f com.genymobile.scrcpy.Server"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            push = subprocess.run(
                ["adb", "push", str(jar), SCRCPY_REMOTE_JAR],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if push.returncode != 0:
                logger.error("Failed to push scrcpy-server: %s", push.stderr.strip())
                return False

            subprocess.run(
                ["adb", "forward", "--remove", f"tcp:{self.port}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            fwd = subprocess.run(
                ["adb", "forward", f"tcp:{self.port}", "localabstract:scrcpy"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if fwd.returncode != 0:
                logger.error("ADB forward failed: %s", fwd.stderr.strip())
                return False

            cmd = (
                f"CLASSPATH={SCRCPY_REMOTE_JAR} app_process / com.genymobile.scrcpy.Server "
                f"{SCRCPY_VERSION} cleanup=false video_source=camera camera_id={self.camera_id} "
                f"camera_size={self.width}x{self.height} camera_fps={self.fps} "
                f"video_bit_rate={self.bitrate} video_codec_options=i-frame-interval=1,max-bframes=0 audio=false control=false "
                f"raw_stream=true tunnel_forward=true"
            )
            self._proc = subprocess.Popen(
                ["adb", "shell", cmd],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            time.sleep(1.2)
            if self._proc.poll() is not None:
                out = self._proc.stdout.read() if self._proc.stdout else ""
                logger.error("scrcpy-server exited early (code=%s): %s", self._proc.returncode, out.strip())
                self._proc = None
                return False

            logger.info(
                "ADB Camera2 session started (camera_id=%s, %dx%d@%dfps, %s)",
                self.camera_id,
                self.width,
                self.height,
                self.fps,
                self.stream_url,
            )
            return True
        except FileNotFoundError:
            logger.error("adb binary not found")
            return False
        except Exception as exc:
            logger.error("Failed to start ADB Camera2 session: %s", exc)
            self.stop()
            return False

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        try:
            subprocess.run(
                ["adb", "shell", "pkill -f com.genymobile.scrcpy.Server"],
                capture_output=True,
                timeout=3,
                check=False,
            )
            subprocess.run(
                ["adb", "forward", "--remove", f"tcp:{self.port}"],
                capture_output=True,
                timeout=3,
                check=False,
            )
        except Exception:
            pass


class CameraReader:
    """Camera frame acquisition supporting V4L2, ADB Android Camera2, RTSP/HTTP streams, and video files."""

    def __init__(
        self,
        src: str | int = 0,
        width: int = SCRCPY_DEFAULT_WIDTH,
        height: int = SCRCPY_DEFAULT_HEIGHT,
        swap_rb: Optional[bool] = None,
    ) -> None:
        self.src = src
        self.width = int(width)
        self.height = int(height)
        is_adb = self._parse_adb_camera_id(src) is not None
        self.swap_rb = _default_adb_swap_rb() if (swap_rb is None and is_adb) else bool(swap_rb)
        self.cap: Optional[Any] = None
        self._adb_session: Optional[AdbCameraSession] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_cond = threading.Condition()
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_seq: int = 0
        self._last_returned_seq: int = 0

    @staticmethod
    def _parse_adb_camera_id(src: str | int) -> Optional[str]:
        s = str(src).strip().lower()
        if s in {"adb", "adb:back", "adb:rear"}:
            return "0"
        if s == "adb:front":
            return "1"
        if s.startswith("adb:"):
            cam_id = s.split(":", 1)[1].strip()
            if cam_id.isdigit():
                return cam_id
        return None

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

    def _normalize_color(self, frame: np.ndarray) -> np.ndarray:
        if not self.swap_rb or frame is None:
            return frame
        if cv2 is not None and hasattr(cv2, "cvtColor") and hasattr(cv2, "COLOR_RGB2BGR"):
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        return np.ascontiguousarray(frame[:, :, ::-1])

    def _start_reader_thread(self) -> None:
        self._stop_event.clear()
        self._latest_frame = None
        self._frame_seq = 0
        self._last_returned_seq = 0

        def _loop() -> None:
            while not self._stop_event.is_set() and self.cap is not None:
                try:
                    ok, frame = self.cap.read()
                except Exception:
                    break
                if ok and frame is not None:
                    frame = self._normalize_color(frame)
                    with self._frame_cond:
                        self._latest_frame = frame
                        self._frame_seq += 1
                        self._frame_cond.notify_all()
                else:
                    time.sleep(0.005)

        self._thread = threading.Thread(target=_loop, name="adb-camera-reader", daemon=True)
        self._thread.start()

    def open(self) -> bool:
        if cv2 is None:
            logger.warning("OpenCV cv2 module not installed; camera cannot open physical capture device")
            return False

        adb_cam_id = self._parse_adb_camera_id(self.src)
        if adb_cam_id is not None:
            self._adb_session = AdbCameraSession(
                camera_id=adb_cam_id,
                width=self.width,
                height=self.height,
            )
            if not self._adb_session.start():
                self._adb_session = None
                return False
            source: str | int = self._adb_session.stream_url
        else:
            source = self._parse_source(self.src)

        logger.info("Initializing camera source %s (parsed=%r, swap_rb=%s)", self.src, source, self.swap_rb)

        try:
            if isinstance(source, int) and hasattr(cv2, "CAP_V4L2"):
                self.cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
                if not self.cap.isOpened():
                    logger.warning("V4L2 backend open failed for %s; retrying default backend", self.src)
                    self.cap.release()
                    self.cap = cv2.VideoCapture(source)
            elif self._adb_session is not None and hasattr(cv2, "CAP_FFMPEG"):
                os.environ.setdefault(
                    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
                    "fflags;nobuffer|flags;low_delay|probesize;32768|analyzeduration;0",
                )
                self.cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
            else:
                self.cap = cv2.VideoCapture(source)

            if not self.cap.isOpened():
                logger.error("Failed to open camera source: %s", self.src)
                self.release()
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
            else:
                try:
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                if self._adb_session is not None:
                    self._start_reader_thread()

            logger.info("Successfully opened camera source: %s", self.src)
            return True
        except Exception as exc:
            logger.error("Exception opening camera source %s: %s", self.src, exc)
            self.release()
            return False

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._thread is not None:
            return self.read_latest()
        if self.cap is None or cv2 is None:
            return False, None
        ok, frame = self.cap.read()
        if ok and frame is not None:
            frame = self._normalize_color(frame)
        return ok, frame

    def read_latest(self, timeout: float = 0.25) -> Tuple[bool, Optional[np.ndarray]]:
        """Return the most recent frame without blocking on stale buffered frames."""
        if self._thread is not None:
            with self._frame_cond:
                if self._frame_seq == self._last_returned_seq:
                    self._frame_cond.wait(timeout=timeout)
                if self._latest_frame is not None:
                    self._last_returned_seq = self._frame_seq
                    return True, self._latest_frame
            return False, None

        if self.cap is None or cv2 is None:
            return False, None
        self.cap.grab()
        ok, frame = self.cap.retrieve()
        if ok and frame is not None:
            frame = self._normalize_color(frame)
        return ok, frame

    def release(self) -> None:
        self._stop_event.set()
        with self._frame_cond:
            self._frame_cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        if self._adb_session is not None:
            self._adb_session.stop()
            self._adb_session = None
