"""Text-to-speech adapter for Piper."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)

_SENTENCE_END_RE = re.compile(r"[.!?](?:\s+|$)")


class PiperTTSError(RuntimeError):
    """Raised when Piper cannot synthesize speech."""


class SentenceChunker:
    """Buffer streamed text into natural sentence-sized chunks."""

    def __init__(self, min_chars: int, max_chars: int) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self._buffer = ""

    def push(self, text: str) -> list[str]:
        """Add text and return complete chunks ready for TTS."""
        self._buffer = " ".join(part for part in (self._buffer, text.strip()) if part).strip()
        chunks: list[str] = []

        while self._buffer:
            split_at = self._sentence_split_index(self._buffer)
            if split_at is None and len(self._buffer) > self.max_chars:
                split_at = self._word_split_index(self._buffer)
            if split_at is None:
                break

            chunk = self._buffer[:split_at].strip()
            if chunk:
                chunks.append(chunk)
            self._buffer = self._buffer[split_at:].strip()

        return chunks

    def flush(self) -> str | None:
        """Return the final buffered fragment, if any."""
        chunk = self._buffer.strip()
        self._buffer = ""
        return chunk or None

    def _sentence_split_index(self, text: str) -> int | None:
        for match in _SENTENCE_END_RE.finditer(text):
            if match.end() >= self.min_chars:
                return match.end()
        return None

    def _word_split_index(self, text: str) -> int:
        split_at = text.rfind(" ", 0, self.max_chars)
        return split_at if split_at > 0 else self.max_chars


class PiperTTS:
    """Synthesize speech from text using the configured Piper binary and voice."""

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()

    def synthesize(self, text: str, output_path: str | Path | None = None) -> Path:
        """Convert one text chunk into a WAV file and return its path."""
        clean_text = " ".join(text.split()).strip()
        if not clean_text:
            raise PiperTTSError("Cannot synthesize empty text")
        if not self.config.piper_binary_path.exists():
            raise PiperTTSError(f"Piper binary does not exist: {self.config.piper_binary_path}")
        if not self.config.piper_voice_model_path.exists():
            raise PiperTTSError(f"Piper voice model does not exist: {self.config.piper_voice_model_path}")
        if not self.config.piper_voice_config_path.exists():
            raise PiperTTSError(f"Piper voice config does not exist: {self.config.piper_voice_config_path}")

        path = Path(output_path) if output_path else self._temporary_wav_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.config.piper_binary_path),
            "--model",
            str(self.config.piper_voice_model_path),
            "--output_file",
            str(path),
        ]
        try:
            result = subprocess.run(
                command,
                input=clean_text,
                text=True,
                capture_output=True,
                check=False,
                timeout=self.config.piper_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise PiperTTSError(f"Piper timed out after {self.config.piper_timeout_seconds}s") from exc
        except OSError as exc:
            raise PiperTTSError(f"Failed to run Piper: {exc}") from exc

        if result.returncode != 0:
            raise PiperTTSError(f"Piper failed: {result.stderr.strip()}")
        logger.info("Synthesized speech chunk to %s", path)
        return path

    def synthesize_stream(self, text_chunks: Iterable[str]) -> Iterator[Path]:
        """Yield WAV files for streamed chatbot text chunks."""
        chunker = SentenceChunker(self.config.tts_min_chunk_chars, self.config.tts_max_chunk_chars)
        for text in text_chunks:
            for chunk in chunker.push(text):
                yield self.synthesize(chunk)
        final_chunk = chunker.flush()
        if final_chunk:
            yield self.synthesize(final_chunk)

    def _temporary_wav_path(self) -> Path:
        self.config.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".wav",
            prefix="edge_tts_",
            dir=str(self.config.temp_dir),
        ) as temp_file:
            return Path(temp_file.name)
