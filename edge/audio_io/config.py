"""Configuration for the edge local audio I/O pipeline."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_MODELS_DIR = PACKAGE_ROOT / "models"
DEFAULT_TEMP_DIR = PACKAGE_ROOT / "tmp"

WHISPER_CPP_RELEASE = "v1.9.1"
PIPER_RELEASE = "2023.11.14-2"

WHISPER_BINARY_URLS = {
    "aarch64": f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_CPP_RELEASE}/whisper-bin-ubuntu-arm64.tar.gz",
    "arm64": f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_CPP_RELEASE}/whisper-bin-ubuntu-arm64.tar.gz",
    "x86_64": f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_CPP_RELEASE}/whisper-bin-ubuntu-x64.tar.gz",
    "amd64": f"https://github.com/ggml-org/whisper.cpp/releases/download/{WHISPER_CPP_RELEASE}/whisper-bin-ubuntu-x64.tar.gz",
}

WHISPER_BINARY_SHA256 = {
    "aarch64": "e0b66cd551ff6f2a28fabe3c6e89691eea037bb76833493abb9a71ca788994b3",
    "arm64": "e0b66cd551ff6f2a28fabe3c6e89691eea037bb76833493abb9a71ca788994b3",
    "x86_64": "f3bf3b4369a99b54665b0f19b88483b30de27f25963b0414235dea03198515c5",
    "amd64": "f3bf3b4369a99b54665b0f19b88483b30de27f25963b0414235dea03198515c5",
}

PIPER_BINARY_URLS = {
    "aarch64": f"https://github.com/rhasspy/piper/releases/download/{PIPER_RELEASE}/piper_linux_aarch64.tar.gz",
    "arm64": f"https://github.com/rhasspy/piper/releases/download/{PIPER_RELEASE}/piper_linux_aarch64.tar.gz",
    "armv7l": f"https://github.com/rhasspy/piper/releases/download/{PIPER_RELEASE}/piper_linux_armv7l.tar.gz",
    "x86_64": f"https://github.com/rhasspy/piper/releases/download/{PIPER_RELEASE}/piper_linux_x86_64.tar.gz",
    "amd64": f"https://github.com/rhasspy/piper/releases/download/{PIPER_RELEASE}/piper_linux_x86_64.tar.gz",
}

WHISPER_TINY_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin?download=true"
PIPER_VOICE_MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true"
PIPER_VOICE_CONFIG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true"


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


def _models_dir() -> Path:
    return _path_env("EDGE_AUDIO_MODELS_DIR", DEFAULT_MODELS_DIR)


def _model_path_env(name: str, *parts: str) -> Path:
    return _path_env(name, _models_dir().joinpath(*parts))


def _optional_str_env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _cloud_stream_url() -> str:
    configured = _optional_str_env("EDGE_AUDIO_CLOUD_API_URL")
    if configured:
        return configured
    cloud_base_url = os.getenv("EDGE_SYNC_CLOUD_URL", "http://10.178.101.3:8000").rstrip("/")
    return f"{cloud_base_url}/api/chatbot/chat/stream"


def _audio_device_env(name: str) -> str | int | None:
    value = _optional_str_env(name)
    if value is None:
        return None
    return int(value) if value.isdigit() else value


def _machine_key() -> str:
    return platform.machine().lower()


def _default_whisper_binary_url() -> str | None:
    return WHISPER_BINARY_URLS.get(_machine_key())


def _default_whisper_binary_sha256() -> str | None:
    return WHISPER_BINARY_SHA256.get(_machine_key())


def _default_piper_binary_url() -> str | None:
    return PIPER_BINARY_URLS.get(_machine_key())


@dataclass(frozen=True)
class AudioIOConfig:
    """Runtime settings for local wake word, STT, cloud chat, and TTS."""

    models_dir: Path = _models_dir()
    temp_dir: Path = _path_env("EDGE_AUDIO_TEMP_DIR", DEFAULT_TEMP_DIR)
    log_level: str = os.getenv("EDGE_AUDIO_LOG_LEVEL", "INFO")

    microphone_device: str | int | None = _audio_device_env("EDGE_AUDIO_MICROPHONE_DEVICE")
    sample_rate: int = _int_env("EDGE_AUDIO_SAMPLE_RATE", 16000)
    channels: int = _int_env("EDGE_AUDIO_CHANNELS", 1)

    wake_word_name: str = os.getenv("EDGE_AUDIO_WAKE_WORD_NAME", "hey_jarvis_v0.1")
    wake_word_model_path: Path = _model_path_env(
        "EDGE_AUDIO_WAKE_WORD_MODEL_PATH",
        "openwakeword",
        "hey_jarvis_v0.1.onnx",
    )
    wake_word_threshold: float = _float_env("EDGE_AUDIO_WAKE_WORD_THRESHOLD", 0.5)
    wake_word_frame_ms: int = _int_env("EDGE_AUDIO_WAKE_WORD_FRAME_MS", 80)
    wake_word_cooldown_seconds: float = _float_env("EDGE_AUDIO_WAKE_WORD_COOLDOWN_SECONDS", 1.5)

    recording_block_ms: int = _int_env("EDGE_AUDIO_RECORDING_BLOCK_MS", 100)
    min_record_seconds: float = _float_env("EDGE_AUDIO_MIN_RECORD_SECONDS", 0.6)
    max_record_seconds: float = _float_env("EDGE_AUDIO_MAX_RECORD_SECONDS", 12.0)
    silence_duration_seconds: float = _float_env("EDGE_AUDIO_SILENCE_DURATION_SECONDS", 1.2)
    silence_rms_threshold: float = _float_env("EDGE_AUDIO_SILENCE_RMS_THRESHOLD", 500.0)

    whisper_binary_path: Path = _model_path_env(
        "EDGE_AUDIO_WHISPER_BINARY_PATH",
        "whisper",
        "whisper-whisper-cli",
    )
    whisper_model_path: Path = _model_path_env(
        "EDGE_AUDIO_WHISPER_MODEL_PATH",
        "whisper",
        "ggml-tiny.bin",
    )
    whisper_threads: int | None = _optional_int_env("EDGE_AUDIO_WHISPER_THREADS")
    whisper_timeout_seconds: int = _int_env("EDGE_AUDIO_WHISPER_TIMEOUT_SECONDS", 120)

    cloud_api_url: str = _cloud_stream_url()
    cloud_bearer_token: str | None = _optional_str_env("EDGE_AUDIO_CLOUD_BEARER_TOKEN")
    cloud_device_id: str = os.getenv("EDGE_AUDIO_CLOUD_DEVICE_ID", os.getenv("EDGE_SYNC_DEVICE_ID", "entry-gate-01"))
    cloud_session_id: int | None = _optional_int_env("EDGE_AUDIO_CLOUD_SESSION_ID")
    cloud_connect_timeout_seconds: float = _float_env("EDGE_AUDIO_CLOUD_CONNECT_TIMEOUT_SECONDS", 5.0)
    cloud_read_timeout_seconds: float = _float_env("EDGE_AUDIO_CLOUD_READ_TIMEOUT_SECONDS", 90.0)
    cloud_retries: int = _int_env("EDGE_AUDIO_CLOUD_RETRIES", 2)
    cloud_retry_backoff_seconds: float = _float_env("EDGE_AUDIO_CLOUD_RETRY_BACKOFF_SECONDS", 1.0)

    piper_binary_path: Path = _model_path_env(
        "EDGE_AUDIO_PIPER_BINARY_PATH",
        "piper",
        "piper",
        "piper",
    )
    piper_voice_model_path: Path = _model_path_env(
        "EDGE_AUDIO_PIPER_VOICE_MODEL_PATH",
        "piper",
        "voices",
        "en_US-lessac-medium.onnx",
    )
    piper_timeout_seconds: int = _int_env("EDGE_AUDIO_PIPER_TIMEOUT_SECONDS", 60)
    tts_min_chunk_chars: int = _int_env("EDGE_AUDIO_TTS_MIN_CHUNK_CHARS", 40)
    tts_max_chunk_chars: int = _int_env("EDGE_AUDIO_TTS_MAX_CHUNK_CHARS", 240)
    audio_player_command: str = os.getenv("EDGE_AUDIO_PLAYER_COMMAND", "aplay")

    skip_model_setup: bool = _bool_env("EDGE_AUDIO_SKIP_MODEL_SETUP", False)

    openwakeword_model_url: str | None = _optional_str_env("EDGE_AUDIO_OPENWAKEWORD_MODEL_URL")
    openwakeword_model_sha256: str | None = _optional_str_env("EDGE_AUDIO_OPENWAKEWORD_MODEL_SHA256")
    whisper_binary_url: str | None = _optional_str_env("EDGE_AUDIO_WHISPER_BINARY_URL") or _default_whisper_binary_url()
    whisper_binary_sha256: str | None = _optional_str_env("EDGE_AUDIO_WHISPER_BINARY_SHA256") or _default_whisper_binary_sha256()
    whisper_model_url: str = os.getenv("EDGE_AUDIO_WHISPER_MODEL_URL", WHISPER_TINY_MODEL_URL)
    whisper_model_sha256: str | None = _optional_str_env("EDGE_AUDIO_WHISPER_MODEL_SHA256")
    piper_binary_url: str | None = _optional_str_env("EDGE_AUDIO_PIPER_BINARY_URL") or _default_piper_binary_url()
    piper_binary_sha256: str | None = _optional_str_env("EDGE_AUDIO_PIPER_BINARY_SHA256")
    piper_voice_model_url: str = os.getenv("EDGE_AUDIO_PIPER_VOICE_MODEL_URL", PIPER_VOICE_MODEL_URL)
    piper_voice_model_sha256: str | None = _optional_str_env("EDGE_AUDIO_PIPER_VOICE_MODEL_SHA256")
    piper_voice_config_url: str = os.getenv("EDGE_AUDIO_PIPER_VOICE_CONFIG_URL", PIPER_VOICE_CONFIG_URL)
    piper_voice_config_sha256: str | None = _optional_str_env("EDGE_AUDIO_PIPER_VOICE_CONFIG_SHA256")

    @property
    def piper_voice_config_path(self) -> Path:
        """Return the Piper JSON config path matching the configured voice model."""
        return self.piper_voice_model_path.with_suffix(".onnx.json")
