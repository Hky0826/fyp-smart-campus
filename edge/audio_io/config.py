"""Configuration for the edge audio I/O terminal."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_TEMP_DIR = PACKAGE_ROOT / "tmp"


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value else None


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _path_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def _optional_str_env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _audio_device_env(name: str) -> str | int | None:
    value = _optional_str_env(name)
    if value is None:
        return None
    return int(value) if value.isdigit() else value


def _cloud_audio_url() -> str:
    configured = _optional_str_env("EDGE_AUDIO_CLOUD_API_URL")
    if configured:
        return configured
    cloud_base_url = os.getenv("EDGE_SYNC_CLOUD_URL", "http://10.178.101.3:8000").rstrip("/")
    return f"{cloud_base_url}/api/chatbot/chat/audio"


@dataclass(frozen=True)
class AudioIOConfig:
    """Runtime settings for the edge audio I/O terminal (record, send, receive, play)."""

    temp_dir: Path = _path_env("EDGE_AUDIO_TEMP_DIR", DEFAULT_TEMP_DIR)
    log_level: str = os.getenv("EDGE_AUDIO_LOG_LEVEL", "INFO")

    microphone_device: str | int | None = _audio_device_env("EDGE_AUDIO_MICROPHONE_DEVICE")
    sample_rate: int = _int_env("EDGE_AUDIO_SAMPLE_RATE", 16000)
    channels: int = _int_env("EDGE_AUDIO_CHANNELS", 1)

    recording_block_ms: int = _int_env("EDGE_AUDIO_RECORDING_BLOCK_MS", 100)
    recording_backend: str = os.getenv("EDGE_AUDIO_RECORDING_BACKEND", "sounddevice").strip().lower()
    min_record_seconds: float = _float_env("EDGE_AUDIO_MIN_RECORD_SECONDS", 0.6)
    max_record_seconds: float = _float_env("EDGE_AUDIO_MAX_RECORD_SECONDS", 12.0)
    silence_duration_seconds: float = _float_env("EDGE_AUDIO_SILENCE_DURATION_SECONDS", 1.2)
    silence_rms_threshold: float = _float_env("EDGE_AUDIO_SILENCE_RMS_THRESHOLD", 500.0)

    cloud_api_url: str = _cloud_audio_url()
    cloud_bearer_token: str | None = _optional_str_env("EDGE_AUDIO_CLOUD_BEARER_TOKEN")
    cloud_device_id: str = os.getenv("EDGE_AUDIO_CLOUD_DEVICE_ID", os.getenv("EDGE_SYNC_DEVICE_ID", "entry-gate-01"))
    cloud_session_id: int | None = _optional_int_env("EDGE_AUDIO_CLOUD_SESSION_ID")
    cloud_connect_timeout_seconds: float = _float_env("EDGE_AUDIO_CLOUD_CONNECT_TIMEOUT_SECONDS", 5.0)
    cloud_read_timeout_seconds: float = _float_env("EDGE_AUDIO_CLOUD_READ_TIMEOUT_SECONDS", 90.0)
    cloud_retries: int = _int_env("EDGE_AUDIO_CLOUD_RETRIES", 2)
    cloud_retry_backoff_seconds: float = _float_env("EDGE_AUDIO_CLOUD_RETRY_BACKOFF_SECONDS", 1.0)

    output_sample_rate: int = _int_env("EDGE_AUDIO_OUTPUT_SAMPLE_RATE", 24000)
