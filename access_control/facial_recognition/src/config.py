"""Configuration for access-control pipeline with YuNet and SFace models."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# Load .env file automatically on import
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = PACKAGE_ROOT.parent  # access_control/
MODEL_ROOT = PACKAGE_ROOT / "models"
DEFAULT_CAMERA = "0"


def default_cloud_url() -> str:
    """Use a TLS loopback endpoint until deployment provisions the cloud URL."""
    return "https://127.0.0.1:8000"


def detect_local_ip(target_url: str = "") -> str:
    """Detect the LAN address used to reach a cloud host without sending data."""
    parsed = urlsplit(target_url) if target_url else None
    target_host = (parsed.hostname if parsed else None) or "8.8.8.8"
    target_port = (parsed.port if parsed else None) or 443
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((target_host, target_port))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
                return address
    except OSError:
        pass
    try:
        address = socket.gethostbyname(socket.gethostname())
        if address:
            return address
    except OSError:
        pass
    return "127.0.0.1"


def default_sync_local_ip() -> str:
    """Use a LAN address only for explicitly enabled remote edge mode."""
    if os.getenv("EDGE_REMOTE_API_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
        return detect_local_ip(os.getenv("EDGE_SYNC_CLOUD_URL", default_cloud_url()))
    return "127.0.0.1"


def default_runtime_config_path() -> Path:
    configured = os.getenv("EDGE_RUNTIME_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".smart-campus-edge" / "device_runtime.env"


RUNTIME_CONFIG_PATH = default_runtime_config_path()


def load_dotenv() -> None:
    """Load .env files automatically from module root and current working directory."""
    try:
        from dotenv import load_dotenv as _load_dotenv
        # The UI-managed runtime file is loaded first so its values take
        # precedence over the optional developer .env fallback below.
        _load_dotenv(RUNTIME_CONFIG_PATH, override=False)
        _load_dotenv(MODULE_ROOT / ".env", override=False)
        _load_dotenv(Path.cwd() / ".env", override=False)
    except ImportError:
        # Fallback manual env parser if python-dotenv is not installed
        for env_path in (RUNTIME_CONFIG_PATH, MODULE_ROOT / ".env", Path.cwd() / ".env"):
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


def persist_runtime_configuration(
    *,
    cloud_url: str,
    device_id: str,
    device_secret: str,
    local_ip: str = "127.0.0.1",
    remote_api_enabled: bool = False,
) -> Path:
    """Persist UI-provisioned edge settings outside the repository.

    This is the development/laptop secret-provider fallback. Production
    deployments should map these values from an OS/deployment secret store.
    """
    values = {
        "EDGE_SYNC_CLOUD_URL": cloud_url.strip(),
        "EDGE_SYNC_DEVICE_ID": device_id.strip(),
        "EDGE_SYNC_DEVICE_SECRET": device_secret.strip(),
        "EDGE_SYNC_LOCAL_IP": local_ip.strip(),
        "EDGE_REMOTE_API_ENABLED": "true" if remote_api_enabled else "false",
    }
    if any(not value or "\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Cloud URL, device ID, and device secret are required")

    path = RUNTIME_CONFIG_PATH.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        "# Created by the access-control setup screen. Do not edit while the service is running.\n"
        + "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)
    try:
        path.chmod(0o600)
    except OSError:
        # Windows ACLs are managed by the user profile; chmod is best effort.
        pass
    return path


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
    return Path.home() / ".smart-campus-edge" / "device_local.db"


@dataclass(frozen=True)
class RuntimeConfig:
    camera: str = _env_str("EDGE_CAMERA", "ACCESS_CAMERA", DEFAULT_CAMERA)
    database_path: Path = default_database_path()
    recognition_enabled: bool = _bool_env("EDGE_RECOGNITION_ENABLED", True)
    access_control_enabled: bool = _bool_env("EDGE_ACCESS_CONTROL_ENABLED", True)
    log_level: str = _env_str("EDGE_LOG_LEVEL", "ACCESS_LOG_LEVEL", "INFO")
    sync_enabled: bool = _bool_env("EDGE_SYNC_ENABLED", True)
    sync_cloud_url: str = _env_str("EDGE_SYNC_CLOUD_URL", "ACCESS_CLOUD_URL", default_cloud_url())
    sync_device_id: str = _env_str("EDGE_SYNC_DEVICE_ID", "ACCESS_DEVICE_ID", "entry-gate-01")
    sync_device_secret: str = _env_str("EDGE_SYNC_DEVICE_SECRET", "ACCESS_DEVICE_SECRET", "")
    sync_device_name: str = _env_str("EDGE_SYNC_DEVICE_NAME", "ACCESS_DEVICE_NAME", "North Entry Gate Kiosk")
    sync_local_ip: str = _env_str("EDGE_SYNC_LOCAL_IP", "ACCESS_LOCAL_IP", default_sync_local_ip())
    sync_local_port: int = _int_env("EDGE_SYNC_LOCAL_PORT", 8001, "ACCESS_SYNC_LOCAL_PORT")
    sync_downstream_poll_seconds: int = _int_env("EDGE_SYNC_DOWNSTREAM_POLL_SECONDS", 30, "ACCESS_SYNC_INTERVAL_SECONDS")
    sync_log_push_interval_seconds: int = _int_env("EDGE_SYNC_LOG_PUSH_INTERVAL_SECONDS", 60)
    allow_insecure_loopback: bool = _bool_env(
        "EDGE_ALLOW_INSECURE_LOOPBACK",
        os.getenv("APP_ENV", "development").lower() != "production",
    )
    api_host: str = _env_str("ACCESS_API_HOST", None, "127.0.0.1")
    api_port: int = _int_env("ACCESS_API_PORT", 8080)
    remote_api_enabled: bool = _bool_env("EDGE_REMOTE_API_ENABLED", False)
    installation_credential: str = _env_str("EDGE_INSTALLATION_CREDENTIAL", None, "")
    database_encryption_key: str = _env_str("EDGE_DB_ENCRYPTION_KEY", "ACCESS_DB_ENCRYPTION_KEY", "")


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
    node_id: int | None = _optional_int_env("EDGE_ACCESS_NODE_ID", "ACCESS_NODE_ID")
    policy_max_age_seconds: int = _int_env("EDGE_ACCESS_POLICY_MAX_AGE_SECONDS", 300)
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
    detector_max_dim: int = _int_env("EDGE_ACCESS_DETECTOR_MAX_DIM", 640)
    min_face_size: int = _int_env("EDGE_ACCESS_MIN_FACE_SIZE", 48, "ACCESS_MIN_FACE_SIZE")
    min_inter_eye_distance: float = _float_env("EDGE_ACCESS_MIN_INTER_EYE_DISTANCE", 18.0)
    min_embedding_samples: int = _int_env("EDGE_ACCESS_MIN_EMBEDDING_SAMPLES", 2, "ACCESS_MIN_EMBEDDING_SAMPLES")
    max_embedding_samples: int = _int_env("EDGE_ACCESS_MAX_EMBEDDING_SAMPLES", 15, "ACCESS_MAX_EMBEDDING_SAMPLES")
    embedding_outlier_threshold: float = _float_env("EDGE_ACCESS_EMBEDDING_OUTLIER_THRESHOLD", 0.25, "ACCESS_EMBEDDING_OUTLIER_THRESHOLD")
    candidate_consistency_ratio: float = _float_env("EDGE_ACCESS_CANDIDATE_CONSISTENCY_RATIO", 0.65, "ACCESS_CANDIDATE_CONSISTENCY_RATIO")
    min_stable_frames: int = _int_env("EDGE_ACCESS_MIN_STABLE_FRAMES", 2, "ACCESS_MIN_STABLE_FRAMES")
    min_stable_duration_ms: int = _int_env("EDGE_ACCESS_MIN_STABLE_DURATION_MS", 100, "ACCESS_MIN_STABLE_DURATION_MS")
    spoof_history_size: int = _int_env("EDGE_ACCESS_SPOOF_HISTORY_SIZE", 4)
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
    snapshot_enabled: bool = _bool_env("EDGE_ACCESS_SNAPSHOT_ENABLED", False)
    snapshot_dir: Path = Path(_env_str("EDGE_ACCESS_SNAPSHOT_DIR", None, str(Path.home() / ".smart-campus-edge" / "snapshots")))
    snapshot_retention_days: int = _int_env("EDGE_ACCESS_SNAPSHOT_RETENTION_DAYS", 7)
    pad_model_path: Path = Path(_env_str("EDGE_ACCESS_PAD_MODEL_PATH", None, ""))
    pad_model_version: str = _env_str("EDGE_ACCESS_PAD_MODEL_VERSION", None, "")
    pad_required: bool = _bool_env("EDGE_ACCESS_PAD_REQUIRED", os.getenv("APP_ENV", "development").lower() == "production")

    @property
    def setup_marker_path(self) -> Path:
        """Persistent marker proving that the local first-run screen was acknowledged."""
        return self.database_path.expanduser().resolve().with_name(".setup_complete")

    def validate_security(self) -> None:
        from urllib.parse import urlparse
        import ipaddress
        parsed = urlparse(self.sync_cloud_url)
        if parsed.scheme != "https":
            is_allowed = False
            if self.allow_insecure_loopback and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
                is_allowed = True
            elif os.getenv("EDGE_ALLOW_INSECURE_HTTP", "false").lower() in {"1", "true", "yes", "on"} or (
                self.allow_insecure_loopback and os.getenv("APP_ENV", "development").lower() != "production"
            ):
                try:
                    ip = ipaddress.ip_address(parsed.hostname)
                    if ip.is_private or ip.is_loopback:
                        is_allowed = True
                except (ValueError, TypeError):
                    pass
            if not is_allowed:
                raise ValueError("Cloud URL must use HTTPS; insecure HTTP is allowed only for explicit loopback or private LAN development")
        if self.remote_api_enabled and not (self.installation_credential or self.sync_device_secret):
            raise ValueError("A device secret or installation credential is required when remote edge API exposure is enabled")
        if os.getenv("APP_ENV", "development").lower() == "production" and not self.sync_device_secret:
            raise ValueError("EDGE_SYNC_DEVICE_SECRET is required in production")
        if self.pad_required and os.getenv("APP_ENV", "development").lower() == "production" and (str(self.pad_model_path) in {"", "."} or not self.pad_model_path.is_file()):
            raise ValueError("A configured PAD model is required in production")
        if os.getenv("APP_ENV", "development").lower() == "production" and not self.database_encryption_key:
            raise ValueError("EDGE_DB_ENCRYPTION_KEY is required in production")
