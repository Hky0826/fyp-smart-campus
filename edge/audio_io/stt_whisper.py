"""Speech-to-text adapter for whisper.cpp."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)

_TIMESTAMP_RE = re.compile(r"\[[0-9:.\s\-]+\]")


class WhisperCppTranscriber:
    """Run whisper.cpp with the tiny multilingual model."""

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()

    def transcribe(self, audio_path: str | Path) -> str:
        """Return clean transcribed text, or an empty string on failure."""
        path = Path(audio_path)
        if not path.exists():
            logger.error("Audio file does not exist: %s", path)
            return ""
        if not self.config.whisper_binary_path.exists():
            logger.error("whisper.cpp binary does not exist: %s", self.config.whisper_binary_path)
            return ""
        if not self.config.whisper_model_path.exists():
            logger.error("Whisper model does not exist: %s", self.config.whisper_model_path)
            return ""

        self.config.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="edge_whisper_", dir=str(self.config.temp_dir)) as temp_dir:
            output_base = Path(temp_dir) / "transcript"
            command = self._build_command(path, output_base)
            logger.info("Running whisper.cpp transcription")
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.config.whisper_timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                logger.error("whisper.cpp transcription timed out after %ss", self.config.whisper_timeout_seconds)
                return ""
            except OSError as exc:
                logger.error("Failed to run whisper.cpp: %s", exc)
                return ""

            if result.returncode != 0:
                logger.error("whisper.cpp failed: %s", result.stderr.strip())
                return ""

            output_file = output_base.with_suffix(".txt")
            if output_file.exists():
                raw_text = output_file.read_text(encoding="utf-8", errors="ignore")
            else:
                raw_text = result.stdout

        text = clean_transcription(raw_text)
        if not text:
            logger.info("whisper.cpp returned an empty transcription")
        return text

    def _build_command(self, audio_path: Path, output_base: Path) -> list[str]:
        command = [
            str(self.config.whisper_binary_path),
            "-m",
            str(self.config.whisper_model_path),
            "-f",
            str(audio_path),
            "-l",
            "auto",
            "-nt",
            "-otxt",
            "-of",
            str(output_base),
        ]
        if self.config.whisper_threads:
            command.extend(["-t", str(self.config.whisper_threads)])
        return command


def clean_transcription(raw_text: str) -> str:
    """Normalize whisper.cpp output into a single user text string."""
    without_timestamps = _TIMESTAMP_RE.sub(" ", raw_text)
    lines = [line.strip() for line in without_timestamps.splitlines() if line.strip()]
    text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()
