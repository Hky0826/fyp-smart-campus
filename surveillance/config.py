"""Configuration for surveillance module."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
MODEL_ROOT = PACKAGE_ROOT / "models"
DEFAULT_CAMERA = "/dev/video4"


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
    hailo8_path = MODEL_ROOT / "yolox_m_hailo8.hef"
    if hailo8_path.exists():
        return hailo8_path
    return MODEL_ROOT / "yolox_m.hef"


def _default_face_detector_path() -> Path:
    configured = os.getenv("SURVEILLANCE_FACE_DETECTOR_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    hailo8_path = MODEL_ROOT / "yunet_hailo8.hef"
    if hailo8_path.exists():
        return hailo8_path
    return MODEL_ROOT / "yunet.hef"


def _default_face_embedder_path() -> Path:
    configured = os.getenv("SURVEILLANCE_FACE_EMBEDDER_MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    for candidate_name in ("arcface_r50_hailo8.hef", "arcface_r50.hef", "glintr100_hailo8.hef", "auraface_hailo8.hef"):
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
    person_detection_threshold: float = float(os.getenv("SURVEILLANCE_PERSON_DETECTION_THRESHOLD", "0.70"))
    face_detection_threshold: float = float(os.getenv("SURVEILLANCE_FACE_DETECTION_THRESHOLD", "0.60"))
    recognition_threshold: float = float(os.getenv("SURVEILLANCE_RECOGNITION_THRESHOLD", "0.60"))

    # ByteTrack configuration
    track_high_thresh: float = float(os.getenv("SURVEILLANCE_TRACK_HIGH_THRESH", "0.50"))
    track_low_thresh: float = float(os.getenv("SURVEILLANCE_TRACK_LOW_THRESH", "0.10"))
    new_track_thresh: float = float(os.getenv("SURVEILLANCE_NEW_TRACK_THRESH", "0.60"))
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

    # Cloud Sync
    sync_enabled: bool = _bool_env("SURVEILLANCE_SYNC_ENABLED", True)
    sync_cloud_url: str = os.getenv(
        "SURVEILLANCE_SYNC_CLOUD_URL",
        os.getenv("EDGE_SYNC_CLOUD_URL", "http://10.251.80.49:8000"),
    )
    sync_device_id: str = os.getenv("SURVEILLANCE_SYNC_DEVICE_ID", "EDGE-EFA36BA9")
    sync_device_name: str = os.getenv("SURVEILLANCE_SYNC_DEVICE_NAME", "Main Surveillance Camera")
    sync_device_secret: str = os.getenv(
        "SURVEILLANCE_SYNC_DEVICE_SECRET",
        "sHJsbEQOYCUheNPQDT-wmltuK9l_QfGd1BlPAv9R_1_-7Aerp7xDxngS6HmyAWwd",
    )
    sync_local_ip: str = os.getenv("SURVEILLANCE_SYNC_LOCAL_IP", "127.0.0.1")
    sync_local_port: int = int(os.getenv("SURVEILLANCE_SYNC_LOCAL_PORT", "8002"))
    sync_downstream_poll_seconds: int = int(os.getenv("SURVEILLANCE_SYNC_DOWNSTREAM_POLL_SECONDS", "30"))
    sync_log_push_interval_seconds: int = int(os.getenv("SURVEILLANCE_SYNC_LOG_PUSH_INTERVAL_SECONDS", "60"))
