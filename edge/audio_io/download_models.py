"""Download and prepare local audio I/O models and binaries."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from .config import AudioIOConfig
except ImportError:  # Allows `python edge/audio_io/download_models.py` from repo root.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)


class ModelSetupError(RuntimeError):
    """Raised when a required model or binary cannot be prepared."""


@dataclass(frozen=True)
class SetupResult:
    """Outcome for one downloaded or prepared asset."""

    name: str
    path: Path | None
    ready: bool
    message: str


def configure_logging(level: str) -> None:
    """Configure process logging for the setup CLI."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def file_sha256(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_sha256: str | None = None, min_size_bytes: int = 1) -> None:
    """Validate that a file exists, is not empty, and optionally matches SHA-256."""
    if not path.exists() or not path.is_file():
        raise ModelSetupError(f"Missing file: {path}")
    if path.stat().st_size < min_size_bytes:
        raise ModelSetupError(f"File is too small to be valid: {path}")
    if expected_sha256:
        actual = file_sha256(path)
        if actual.lower() != expected_sha256.lower():
            raise ModelSetupError(f"SHA-256 mismatch for {path}: expected {expected_sha256}, got {actual}")


def download_file(url: str, destination: Path, expected_sha256: str | None = None, min_size_bytes: int = 1) -> bool:
    """Download a URL to a destination unless a valid file already exists."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        try:
            verify_file(destination, expected_sha256, min_size_bytes)
            logger.info("Already present: %s", destination)
            return False
        except ModelSetupError as exc:
            logger.warning("Existing file failed verification and will be re-downloaded: %s", exc)
            destination.unlink(missing_ok=True)

    logger.info("Downloading %s", url)
    request = urllib.request.Request(url, headers={"User-Agent": "edge-audio-io/1.0"})
    with tempfile.NamedTemporaryFile(delete=False, dir=str(destination.parent), suffix=".download") as temp_file:
        temp_path = Path(temp_file.name)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                shutil.copyfileobj(response, temp_file)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    try:
        verify_file(temp_path, expected_sha256, min_size_bytes)
        temp_path.replace(destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    logger.info("Saved %s", destination)
    return True


def _safe_extract_tar(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            member_path = (destination / member.name).resolve()
            if destination_root not in member_path.parents and member_path != destination_root:
                raise ModelSetupError(f"Unsafe archive path: {member.name}")
        archive.extractall(destination)


def _safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member_name in archive.namelist():
            member_path = (destination / member_name).resolve()
            if destination_root not in member_path.parents and member_path != destination_root:
                raise ModelSetupError(f"Unsafe archive path: {member_name}")
        archive.extractall(destination)


def extract_archive(archive_path: Path, destination: Path) -> None:
    """Extract a tar or zip archive into a destination directory safely."""
    logger.info("Extracting %s to %s", archive_path, destination)
    if archive_path.suffix == ".zip":
        _safe_extract_zip(archive_path, destination)
        return
    if archive_path.name.endswith((".tar.gz", ".tgz", ".tar")):
        _safe_extract_tar(archive_path, destination)
        return
    raise ModelSetupError(f"Unsupported archive format: {archive_path}")


def make_executable(path: Path) -> None:
    """Add executable bits to a local binary or wrapper script."""
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def find_binary(root: Path, names: Iterable[str]) -> Path | None:
    """Find a binary by filename under a directory."""
    for name in names:
        for path in root.rglob(name):
            if path.is_file():
                return path
    return None


def install_binary_reference(source: Path, target: Path) -> None:
    """Expose an extracted binary at the configured target path."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        make_executable(target)
        return

    try:
        target.symlink_to(source.resolve())
    except OSError:
        shutil.copy2(source, target)
    make_executable(target)


def is_deprecated_whisper_wrapper(path: Path) -> bool:
    """Return True when a whisper binary is only the upstream deprecation stub."""
    try:
        result = subprocess.run(
            [str(path), "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False

    output = f"{result.stdout}\n{result.stderr}".lower()
    return "is deprecated" in output and "please use" in output


def ensure_openwakeword_model(config: AudioIOConfig) -> SetupResult:
    """Prepare the configured openWakeWord model."""
    if config.wake_word_model_path.exists():
        verify_file(config.wake_word_model_path, config.openwakeword_model_sha256)
        return SetupResult("openWakeWord model", config.wake_word_model_path, True, "already present")

    if config.openwakeword_model_url:
        download_file(
            config.openwakeword_model_url,
            config.wake_word_model_path,
            config.openwakeword_model_sha256,
            min_size_bytes=1024,
        )
        return SetupResult("openWakeWord model", config.wake_word_model_path, True, "downloaded")

    try:
        from openwakeword.utils import download_models
    except ImportError as exc:
        raise ModelSetupError(
            "openwakeword is not installed. Install edge/audio_io/requirements.txt first."
        ) from exc

    logger.info("Downloading openWakeWord package model: %s", config.wake_word_name)
    download_models(model_names=[config.wake_word_name])
    return SetupResult(
        "openWakeWord model",
        None,
        True,
        "prepared via openwakeword package downloader",
    )


def ensure_whisper_model(config: AudioIOConfig) -> SetupResult:
    """Download the whisper.cpp tiny multilingual model."""
    download_file(
        config.whisper_model_url,
        config.whisper_model_path,
        config.whisper_model_sha256,
        min_size_bytes=1024 * 1024,
    )
    return SetupResult("Whisper tiny multilingual model", config.whisper_model_path, True, "ready")


def ensure_whisper_binary(config: AudioIOConfig) -> SetupResult:
    """Download and expose the whisper.cpp CLI binary."""
    if config.whisper_binary_path.exists():
        make_executable(config.whisper_binary_path)
        if not is_deprecated_whisper_wrapper(config.whisper_binary_path):
            return SetupResult("whisper.cpp binary", config.whisper_binary_path, True, "already present")
        logger.warning(
            "Existing whisper.cpp binary is a deprecated wrapper and will be replaced: %s",
            config.whisper_binary_path,
        )
        config.whisper_binary_path.unlink(missing_ok=True)

    if not config.whisper_binary_url:
        raise ModelSetupError(
            "No whisper.cpp binary URL is configured for this platform. Set EDGE_AUDIO_WHISPER_BINARY_URL."
        )

    archive_name = Path(config.whisper_binary_url.split("?")[0]).name
    archive_path = config.models_dir / "downloads" / archive_name
    download_file(config.whisper_binary_url, archive_path, config.whisper_binary_sha256, min_size_bytes=1024 * 1024)

    extract_dir = config.models_dir / "whisper"
    extract_archive(archive_path, extract_dir)
    binary = find_binary(
        extract_dir,
        (
            "whisper-cli",
            "whisper-cli.exe",
            "main",
            "main.exe",
        ),
    )
    if binary is None:
        raise ModelSetupError(f"Could not find whisper.cpp CLI binary after extracting {archive_path}")

    install_binary_reference(binary, config.whisper_binary_path)
    return SetupResult("whisper.cpp binary", config.whisper_binary_path, True, "ready")


def ensure_piper_binary(config: AudioIOConfig) -> SetupResult:
    """Download and expose the Piper TTS binary."""
    if config.piper_binary_path.exists():
        make_executable(config.piper_binary_path)
        return SetupResult("Piper binary", config.piper_binary_path, True, "already present")
    if not config.piper_binary_url:
        raise ModelSetupError("No Piper binary URL is configured for this platform. Set EDGE_AUDIO_PIPER_BINARY_URL.")

    archive_name = Path(config.piper_binary_url.split("?")[0]).name
    archive_path = config.models_dir / "downloads" / archive_name
    download_file(config.piper_binary_url, archive_path, config.piper_binary_sha256, min_size_bytes=1024 * 1024)

    extract_dir = config.models_dir / "piper"
    extract_archive(archive_path, extract_dir)
    binary = find_binary(extract_dir, ("piper", "piper.exe"))
    if binary is None:
        raise ModelSetupError(f"Could not find Piper binary after extracting {archive_path}")

    install_binary_reference(binary, config.piper_binary_path)
    return SetupResult("Piper binary", config.piper_binary_path, True, "ready")


def ensure_piper_voice(config: AudioIOConfig) -> list[SetupResult]:
    """Download the Piper voice ONNX file and matching JSON config."""
    download_file(
        config.piper_voice_model_url,
        config.piper_voice_model_path,
        config.piper_voice_model_sha256,
        min_size_bytes=1024 * 1024,
    )
    download_file(
        config.piper_voice_config_url,
        config.piper_voice_config_path,
        config.piper_voice_config_sha256,
        min_size_bytes=128,
    )
    return [
        SetupResult("Piper voice model", config.piper_voice_model_path, True, "ready"),
        SetupResult("Piper voice config", config.piper_voice_config_path, True, "ready"),
    ]


def ensure_assets(config: AudioIOConfig | None = None, include_wake_word: bool = False) -> list[SetupResult]:
    """Ensure all required local audio assets are available."""
    resolved_config = config or AudioIOConfig()
    resolved_config.models_dir.mkdir(parents=True, exist_ok=True)
    resolved_config.temp_dir.mkdir(parents=True, exist_ok=True)

    results = [
        ensure_whisper_binary(resolved_config),
        ensure_whisper_model(resolved_config),
        ensure_piper_binary(resolved_config),
    ]
    if include_wake_word:
        results.insert(0, ensure_openwakeword_model(resolved_config))
    results.extend(ensure_piper_voice(resolved_config))
    return results


def main() -> None:
    """CLI entry point for preparing audio I/O assets."""
    parser = argparse.ArgumentParser(description="Download edge audio I/O models and local binaries")
    parser.add_argument(
        "--include-wake-word",
        action="store_true",
        help="Also prepare the legacy openWakeWord model used by local hardware tests",
    )
    parser.add_argument("--log-level", default=None, help="Override EDGE_AUDIO_LOG_LEVEL for this setup run")
    args = parser.parse_args()

    config = AudioIOConfig()
    configure_logging(args.log_level or config.log_level)
    results = ensure_assets(config, include_wake_word=args.include_wake_word)
    for result in results:
        path = str(result.path) if result.path else "package-managed"
        logger.info("%s: %s (%s)", result.name, result.message, path)


if __name__ == "__main__":
    main()
