"""Configuration for surveillance module."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
MODEL_ROOT = PACKAGE_ROOT / "models"
DEFAULT_CAMERA = "adb"
RUNTIME_CONFIG_PATH = Path(
    os.getenv("SURVEILLANCE_RUNTIME_CONFIG_PATH", str(Path.home() / ".smart_campus_surveillance.env"))
)
SETUP_MARKER_PATH = Path(
    os.getenv("SURVEILLANCE_SETUP_MARKER_PATH", str(Path.home() / ".smart_campus_surveillance.provisioned"))
)


def load_runtime_configuration() -> None:
    """Load persisted surveillance pairing settings and optional provision.json seed."""
    path = RUNTIME_CONFIG_PATH.expanduser()
    if path.is_file():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                os.environ.setdefault(key, value.strip().strip("'\""))

    seed_path = Path(os.getenv("SURVEILLANCE_PROVISION_FILE", str(PACKAGE_ROOT / "provision.json"))).expanduser()
    if seed_path.is_file() and not os.getenv("SURVEILLANCE_SYNC_DEVICE_SECRET"):
        try:
            data = json.loads(seed_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                mapping = {
                    "cloud_url": "SURVEILLANCE_SYNC_CLOUD_URL",
                    "device_id": "SURVEILLANCE_SYNC_DEVICE_ID",
                    "device_secret": "SURVEILLANCE_SYNC_DEVICE_SECRET",
                    "device_name": "SURVEILLANCE_SYNC_DEVICE_NAME",
                }
                for src, dst in mapping.items():
                    val = str(data.get(src) or "").strip()
                    if val:
                        os.environ.setdefault(dst, val)
        except Exception:
            pass


def persist_runtime_configuration(
    *,
    cloud_url: str,
    device_id: str,
    device_secret: str,
    device_name: str = "Surveillance Camera",
    local_ip: str = "127.0.0.1",
) -> Path:
    values = {
        "SURVEILLANCE_SYNC_CLOUD_URL": cloud_url.strip().rstrip("/"),
        "SURVEILLANCE_SYNC_DEVICE_ID": device_id.strip(),
        "SURVEILLANCE_SYNC_DEVICE_SECRET": device_secret.strip(),
        "SURVEILLANCE_SYNC_DEVICE_NAME": device_name.strip() or "Surveillance Camera",
        "SURVEILLANCE_SYNC_LOCAL_IP": local_ip.strip() or "127.0.0.1",
    }
    if not values["SURVEILLANCE_SYNC_CLOUD_URL"] or not values["SURVEILLANCE_SYNC_DEVICE_ID"] or not values["SURVEILLANCE_SYNC_DEVICE_SECRET"]:
        raise ValueError("Cloud URL, device ID, and device secret are required")

    path = RUNTIME_CONFIG_PATH.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "# Created by surveillance device provisioning.\n"
        + "".join(f"{k}={v}\n" for k, v in values.items()),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    for k, v in values.items():
        os.environ[k] = v
    return path


def clear_runtime_configuration() -> None:
    for path in (RUNTIME_CONFIG_PATH.expanduser(), SETUP_MARKER_PATH.expanduser()):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    for key in (
        "SURVEILLANCE_SYNC_DEVICE_SECRET",
        "SURVEILLANCE_SYNC_DEVICE_ID",
        "SURVEILLANCE_SYNC_LOCAL_IP",
    ):
        os.environ.pop(key, None)


load_runtime_configuration()


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_database_path() -> Path:
    configured = os.getenv("SURVEILLANCE_DB_PATH") or os.getenv("EDGE_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return PACKAGE_ROOT / "surveillance.db"


def _default_person_detector_path() -> Path:
    configured = os.getenv("SURVEILLANCE_PERSON_DETECTOR_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    for candidate_name in ("yolov8s.hef", "yolov8m.hef", "yolox_m_hailo8.hef", "yolox_m.hef"):
        candidate = MODEL_ROOT / candidate_name
        if candidate.exists():
            return candidate
    return MODEL_ROOT / "yolov8s.hef"


def _default_face_detector_path() -> Path:
    configured = os.getenv("SURVEILLANCE_FACE_DETECTOR_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    for candidate_name in ("scrfd_10g.hef", "scrfd_2.5g.hef", "yunet_hailo8.hef", "yunet.hef"):
        candidate = MODEL_ROOT / candidate_name
        if candidate.exists():
            return candidate
    return MODEL_ROOT / "scrfd_10g.hef"


def _default_face_embedder_path() -> Path:
    configured = os.getenv("SURVEILLANCE_FACE_EMBEDDER_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    for candidate_name in ("arcface_r50.hef", "arcface_r50_hailo8.hef", "glintr100_hailo8.hef", "auraface_hailo8.hef"):
        candidate = MODEL_ROOT / candidate_name
        if candidate.exists():
            return candidate
    return MODEL_ROOT / "arcface_r50.hef"


@dataclass(frozen=True)
class SurveillanceConfig:
    """Configuration options for the surveillance module pipeline, tracking, and sync."""

    # Model paths (configurable, defaults to HEF files in surveillance/models)
    person_detector_model_path: Path = field(default_factory=_default_person_detector_path)
    face_detector_model_path: Path = field(default_factory=_default_face_detector_path)
    face_embedder_model_path: Path = field(default_factory=_default_face_embedder_path)

    # Input & Camera
    camera: str = os.getenv("SURVEILLANCE_CAMERA", os.getenv("EDGE_CAMERA", DEFAULT_CAMERA))
    database_path: Path = default_database_path()

    # Detection & Recognition thresholds
    person_detection_threshold: float = float(os.getenv("SURVEILLANCE_PERSON_DETECTION_THRESHOLD", "0.45"))
    face_detection_threshold: float = float(os.getenv("SURVEILLANCE_FACE_DETECTION_THRESHOLD", "0.50"))
    recognition_threshold: float = float(os.getenv("SURVEILLANCE_RECOGNITION_THRESHOLD", "0.60"))

    # ByteTrack configuration
    track_high_thresh: float = float(os.getenv("SURVEILLANCE_TRACK_HIGH_THRESH", "0.45"))
    track_low_thresh: float = float(os.getenv("SURVEILLANCE_TRACK_LOW_THRESH", "0.10"))
    new_track_thresh: float = float(os.getenv("SURVEILLANCE_NEW_TRACK_THRESH", "0.50"))
    track_buffer: int = int(os.getenv("SURVEILLANCE_TRACK_BUFFER", "30"))
    match_thresh: float = float(os.getenv("SURVEILLANCE_MATCH_THRESH", "0.80"))

    # Snapshots & Logging
    snapshot_enabled: bool = _bool_env("SURVEILLANCE_SNAPSHOT_ENABLED", True)
    snapshot_dir: Path = Path(
        os.getenv(
            "SURVEILLANCE_SNAPSHOT_DIR",
            str(PACKAGE_ROOT / "snapshots"),
        )
    ).expanduser()
    log_level: str = os.getenv("SURVEILLANCE_LOG_LEVEL", "INFO")

    # Cloud Sync (populated via QR scan, /setup claim, provision.json, or environment)
    sync_enabled: bool = field(default_factory=lambda: _bool_env("SURVEILLANCE_SYNC_ENABLED", True))
    sync_cloud_url: str = field(
        default_factory=lambda: os.getenv(
            "SURVEILLANCE_SYNC_CLOUD_URL",
            os.getenv("EDGE_SYNC_CLOUD_URL", ""),
        )
    )
    sync_device_id: str = field(default_factory=lambda: os.getenv("SURVEILLANCE_SYNC_DEVICE_ID", ""))
    sync_device_name: str = field(
        default_factory=lambda: os.getenv("SURVEILLANCE_SYNC_DEVICE_NAME", "Surveillance Camera")
    )
    sync_device_secret: str = field(default_factory=lambda: os.getenv("SURVEILLANCE_SYNC_DEVICE_SECRET", ""))
    sync_local_ip: str = field(default_factory=lambda: os.getenv("SURVEILLANCE_SYNC_LOCAL_IP", "127.0.0.1"))
    sync_local_port: int = field(default_factory=lambda: int(os.getenv("SURVEILLANCE_SYNC_LOCAL_PORT", "8002")))
    sync_downstream_poll_seconds: int = field(
        default_factory=lambda: int(os.getenv("SURVEILLANCE_SYNC_DOWNSTREAM_POLL_SECONDS", "30"))
    )
    sync_log_push_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("SURVEILLANCE_SYNC_LOG_PUSH_INTERVAL_SECONDS", "60"))
    )
    setup_marker_path: Path = field(default_factory=lambda: SETUP_MARKER_PATH.expanduser())
