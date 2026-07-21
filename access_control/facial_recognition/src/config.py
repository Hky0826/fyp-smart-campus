"""Configuration for access-control pipeline with YuNet and SFace models."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Load .env file automatically on import
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = PACKAGE_ROOT.parent  # access_control/
MODEL_ROOT = PACKAGE_ROOT / "models"
DEFAULT_CAMERA = "0"


def load_dotenv() -> None:
    """Load .env files automatically from module root and current working directory."""
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(MODULE_ROOT / ".env", override=False)
        _load_dotenv(Path.cwd() / ".env", override=False)
    except ImportError:
        # Fallback manual env parser if python-dotenv is not installed
        for env_path in (MODULE_ROOT / ".env", Path.cwd() / ".env"):
            if env_path.is_file():
                for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    if line.startswith("export "):
                        line = line[7:].lstrip()
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key:
                        val = value.strip().strip("'\"")
                        os.environ.setdefault(key, val)


load_dotenv()


def _env_str(name: str, fallback_name: str | None = None, default: str = "") -> str:
    val = os.getenv(name)
    if val is not None:
        return val
    if fallback_name is not None:
        val = os.getenv(fallback_name)
        if val is not None:
            return val
    return default


def _bool_env(name: str, default: bool, fallback_name: str | None = None) -> bool:
    value = os.getenv(name)
    if value is None and fallback_name:
        value = os.getenv(fallback_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float, fallback_name: str | None = None) -> float:
    value = os.getenv(name)
    if value is None and fallback_name:
        value = os.getenv(fallback_name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_env(name: str, default: int, fallback_name: str | None = None) -> int:
    value = os.getenv(name)
    if value is None and fallback_name:
        value = os.getenv(fallback_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _optional_int_env(name: str, fallback_name: str | None = None) -> int | None:
    value = os.getenv(name)
    if value is None and fallback_name:
        value = os.getenv(fallback_name)
    return int(value) if value else None


def default_database_path() -> Path:
    configured = os.getenv("EDGE_DB_PATH") or os.getenv("ACCESS_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return PACKAGE_ROOT / "data" / "device_local.db"


@dataclass(frozen=True)
class RuntimeConfig:
    camera: str = _env_str("EDGE_CAMERA", "ACCESS_CAMERA", DEFAULT_CAMERA)
    database_path: Path = default_database_path()
    recognition_enabled: bool = _bool_env("EDGE_RECOGNITION_ENABLED", True)
    access_control_enabled: bool = _bool_env("EDGE_ACCESS_CONTROL_ENABLED", True)
    log_level: str = _env_str("EDGE_LOG_LEVEL", "ACCESS_LOG_LEVEL", "INFO")
    sync_enabled: bool = _bool_env("EDGE_SYNC_ENABLED", True)
    sync_cloud_url: str = _env_str("EDGE_SYNC_CLOUD_URL", "ACCESS_CLOUD_URL", "http://127.0.0.1:8000")
    sync_device_id: str = _env_str("EDGE_SYNC_DEVICE_ID", "ACCESS_DEVICE_ID", "entry-gate-01")
    sync_device_name: str = _env_str("EDGE_SYNC_DEVICE_NAME", "ACCESS_DEVICE_NAME", "North Entry Gate Kiosk")
    sync_local_ip: str = _env_str("EDGE_SYNC_LOCAL_IP", "ACCESS_LOCAL_IP", "127.0.0.1")
    sync_local_port: int = _int_env("EDGE_SYNC_LOCAL_PORT", 8001, "ACCESS_SYNC_LOCAL_PORT")
    sync_downstream_poll_seconds: int = _int_env("EDGE_SYNC_DOWNSTREAM_POLL_SECONDS", 30, "ACCESS_SYNC_INTERVAL_SECONDS")
    sync_log_push_interval_seconds: int = _int_env("EDGE_SYNC_LOG_PUSH_INTERVAL_SECONDS", 60)


def _resolve_model_path(path_str: str, default_path: Path) -> Path:
    p = Path(path_str)
    if p.is_file():
        return p.resolve()
    if (MODULE_ROOT / p).is_file():
        return (MODULE_ROOT / p).resolve()
    if (PACKAGE_ROOT / p).is_file():
        return (PACKAGE_ROOT / p).resolve()
    return default_path.resolve() if default_path.is_file() else p


@dataclass(frozen=True)
class AccessControlConfig(RuntimeConfig):
    detector_model_path: Path = _resolve_model_path(
        _env_str("EDGE_ACCESS_DETECTOR_MODEL_PATH", "ACCESS_YUNET_MODEL", str(MODEL_ROOT / "access_control" / "face_detection_yunet_2023mar_int8bq.onnx")),
        MODEL_ROOT / "access_control" / "face_detection_yunet_2023mar_int8bq.onnx"
    )
    embedding_model_path: Path = _resolve_model_path(
        _env_str("EDGE_ACCESS_EMBEDDING_MODEL_PATH", "ACCESS_SFACE_MODEL", str(MODEL_ROOT / "access_control" / "face_recognition_sface_2021dec.onnx")),
        MODEL_ROOT / "access_control" / "face_recognition_sface_2021dec.onnx"
    )
    detector_type: str = _env_str("EDGE_ACCESS_DETECTOR_TYPE", None, "yunet")
    embedder_type: str = _env_str("EDGE_ACCESS_EMBEDDER_TYPE", None, "sface")
    recognition_model_name: str = _env_str("EDGE_ACCESS_RECOGNITION_MODEL_NAME", None, "openvc_sface")
    camera: str = _env_str("EDGE_ACCESS_CAMERA", "EDGE_CAMERA", DEFAULT_CAMERA)
    detection_threshold: float = _float_env("EDGE_ACCESS_DETECTION_THRESHOLD", 0.60, "ACCESS_YUNET_CONFIDENCE")
    recognition_threshold: float = _float_env("EDGE_ACCESS_RECOGNITION_THRESHOLD", 0.363, "ACCESS_SFACE_THRESHOLD")
    recognition_delay_seconds: float = _float_env("EDGE_ACCESS_RECOGNITION_DELAY_SECONDS", 1.0)
    min_face_size: int = _int_env("EDGE_ACCESS_MIN_FACE_SIZE", 48, "ACCESS_MIN_FACE_SIZE")
    min_inter_eye_distance: float = _float_env("EDGE_ACCESS_MIN_INTER_EYE_DISTANCE", 18.0)
    min_embedding_samples: int = _int_env("EDGE_ACCESS_MIN_EMBEDDING_SAMPLES", 3, "ACCESS_MIN_EMBEDDING_SAMPLES")
    max_embedding_samples: int = _int_env("EDGE_ACCESS_MAX_EMBEDDING_SAMPLES", 15, "ACCESS_MAX_EMBEDDING_SAMPLES")
    embedding_outlier_threshold: float = _float_env("EDGE_ACCESS_EMBEDDING_OUTLIER_THRESHOLD", 0.25, "ACCESS_EMBEDDING_OUTLIER_THRESHOLD")
    candidate_consistency_ratio: float = _float_env("EDGE_ACCESS_CANDIDATE_CONSISTENCY_RATIO", 0.65, "ACCESS_CANDIDATE_CONSISTENCY_RATIO")
    min_stable_frames: int = _int_env("EDGE_ACCESS_MIN_STABLE_FRAMES", 5, "ACCESS_MIN_STABLE_FRAMES")
    min_stable_duration_ms: int = _int_env("EDGE_ACCESS_MIN_STABLE_DURATION_MS", 250, "ACCESS_MIN_STABLE_DURATION_MS")
    max_missed_frames: int = _int_env("EDGE_ACCESS_MAX_MISSED_FRAMES", 3, "ACCESS_MAX_MISSED_FRAMES")
    track_timeout_ms: int = _int_env("EDGE_ACCESS_TRACK_TIMEOUT_MS", 1000, "ACCESS_TRACK_TIMEOUT_MS")
    min_iou_for_match: float = _float_env("EDGE_ACCESS_MIN_IOU_FOR_MATCH", 0.30, "ACCESS_MIN_IOU_FOR_MATCH")
    max_landmark_jump_ratio: float = _float_env("EDGE_ACCESS_MAX_LANDMARK_JUMP_RATIO", 0.50, "ACCESS_MAX_LANDMARK_JUMP_RATIO")
    detector_nms_iou_threshold: float = _float_env("EDGE_ACCESS_NMS_IOU_THRESHOLD", 0.30, "ACCESS_YUNET_NMS")
    detector_min_box_size: float = _float_env("EDGE_ACCESS_DETECTOR_MIN_BOX_SIZE", 16.0)
    detector_max_box_size_ratio: float = _float_env("EDGE_ACCESS_DETECTOR_MAX_BOX_SIZE_RATIO", 0.95)
    detector_box_expansion_ratio: float = _float_env("EDGE_ACCESS_BOX_EXPANSION_RATIO", 0.0)
    require_liveness: bool = _bool_env("EDGE_ACCESS_REQUIRE_LIVENESS", True, "ACCESS_REQUIRE_LIVENESS")
    audio_enabled: bool = _bool_env("EDGE_ACCESS_AUDIO_ENABLED", True, "ACCESS_AUDIO_ENABLED")
    audio_skip_model_setup: bool = _bool_env("EDGE_ACCESS_AUDIO_SKIP_MODEL_SETUP", False)
    audio_auth_timeout_seconds: float = _float_env("EDGE_ACCESS_AUDIO_AUTH_TIMEOUT_SECONDS", 45.0, "ACCESS_AUDIO_AUTH_TIMEOUT_SECONDS")
    audio_token_refresh_seconds: float = _float_env("EDGE_ACCESS_AUDIO_TOKEN_REFRESH_SECONDS", 600.0, "ACCESS_AUDIO_TOKEN_REFRESH_SECONDS")
    audio_token_retry_seconds: float = _float_env("EDGE_ACCESS_AUDIO_TOKEN_RETRY_SECONDS", 10.0, "ACCESS_AUDIO_TOKEN_RETRY_SECONDS")
    audio_auto_visitor_token: bool = _bool_env("EDGE_ACCESS_CHATBOT_AUTO_VISITOR_TOKEN", False, "ACCESS_AUDIO_AUTO_VISITOR_TOKEN")
    audio_visitor_user_id: int | None = _optional_int_env("EDGE_ACCESS_CHATBOT_VISITOR_USER_ID", "ACCESS_AUDIO_VISITOR_USER_ID")
    snapshot_enabled: bool = _bool_env("EDGE_ACCESS_SNAPSHOT_ENABLED", True)
    snapshot_dir: Path = Path(_env_str("EDGE_ACCESS_SNAPSHOT_DIR", None, str(PACKAGE_ROOT / "data" / "snapshots")))
