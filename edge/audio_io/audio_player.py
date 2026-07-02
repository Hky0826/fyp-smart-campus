"""Local WAV playback for the edge device."""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from pathlib import Path

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)


class AudioPlaybackError(RuntimeError):
    """Raised when local audio playback fails."""


class AudioPlayer:
    """Play generated WAV files using a simple Linux-compatible command."""

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()

    def play(self, audio_path: str | Path) -> None:
        """Play a WAV file through the configured command."""
        path = Path(audio_path)
        if not path.exists():
            raise AudioPlaybackError(f"Audio file does not exist: {path}")

        command = shlex.split(self.config.audio_player_command)
        if not command:
            raise AudioPlaybackError("EDGE_AUDIO_PLAYER_COMMAND is empty")
        executable = command[0]
        if shutil.which(executable) is None and not Path(executable).exists():
            raise AudioPlaybackError(f"Audio playback command is not available: {executable}")

        try:
            subprocess.run([*command, str(path)], check=True, timeout=self.config.piper_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise AudioPlaybackError("Audio playback timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise AudioPlaybackError(f"Audio playback failed with exit code {exc.returncode}") from exc
        logger.info("Played audio file: %s", path)

    def play_and_cleanup(self, audio_path: str | Path) -> None:
        """Play a temporary WAV file and delete it afterward."""
        path = Path(audio_path)
        try:
            self.play(path)
        finally:
            path.unlink(missing_ok=True)
