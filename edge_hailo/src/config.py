"""Configuration for access-control and surveillance Hailo pipelines."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PACKAGE_ROOT / "models"
DEFAULT_CAMERA = "/dev/video4"


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_database_path() -> Path:
    configured = os.getenv("EDGE_HAILO_DB_PATH")
    if configured:
        return Path(configured).expanduser()

    return PACKAGE_ROOT / "data" / "device_local.db"


@dataclass(frozen=True)
class RuntimeConfig:
    camera: str = os.getenv("EDGE_HAILO_CAMERA", DEFAULT_CAMERA)
    database_path: Path = default_database_path()
    recognition_enabled: bool = _bool_env("EDGE_HAILO_RECOGNITION_ENABLED", True)
    access_control_enabled: bool = _bool_env("EDGE_HAILO_ACCESS_CONTROL_ENABLED", True)
    surveillance_enabled: bool = _bool_env("EDGE_HAILO_SURVEILLANCE_ENABLED", True)
    log_level: str = os.getenv("EDGE_HAILO_LOG_LEVEL", "INFO")


@dataclass(frozen=True)
class AccessControlConfig(RuntimeConfig):
    detector_model_path: Path = MODEL_ROOT / "surveillance" / "scrfd_10g.hef"
    embedding_model_path: Path = MODEL_ROOT / "access_control" / "arcface_mobilefacenet.hef"
    camera: str = os.getenv("EDGE_HAILO_ACCESS_CAMERA", os.getenv("EDGE_HAILO_CAMERA", DEFAULT_CAMERA))
    detection_threshold: float = float(os.getenv("EDGE_HAILO_ACCESS_DETECTION_THRESHOLD", "0.60"))
    # Tune with real camera footage. A strict threshold is safer for access decisions.
    recognition_threshold: float = float(os.getenv("EDGE_HAILO_ACCESS_RECOGNITION_THRESHOLD", "0.75"))
    min_face_size: int = int(os.getenv("EDGE_HAILO_ACCESS_MIN_FACE_SIZE", "48"))
    require_liveness: bool = _bool_env("EDGE_HAILO_ACCESS_REQUIRE_LIVENESS", True)


@dataclass(frozen=True)
class SurveillanceConfig(RuntimeConfig):
    detector_model_path: Path = MODEL_ROOT / "surveillance" / "scrfd_10g.hef"
    embedding_model_path: Path = MODEL_ROOT / "surveillance" / "arcface_r50.hef"
    camera: str = os.getenv("EDGE_HAILO_SURVEILLANCE_CAMERA", os.getenv("EDGE_HAILO_CAMERA", DEFAULT_CAMERA))
    detection_threshold: float = float(os.getenv("EDGE_HAILO_SURVEILLANCE_DETECTION_THRESHOLD", "0.55"))
    # Tune with real camera footage, including angled, up/down, and low-light views.
    recognition_threshold: float = float(os.getenv("EDGE_HAILO_SURVEILLANCE_RECOGNITION_THRESHOLD", "0.62"))
    min_face_size: int = int(os.getenv("EDGE_HAILO_SURVEILLANCE_MIN_FACE_SIZE", "32"))
