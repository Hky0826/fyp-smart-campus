"""Play received PCM audio through the speaker using sounddevice."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)


class AudioPlaybackError(RuntimeError):
    """Raised when audio playback fails."""


class AudioPlayer:
    """Play PCM audio data through the default output device using sounddevice.

    Supports raw PCM bytes (24 kHz mono int16) and WAV file playback.
    Uses ``sounddevice.play()`` for simple blocking playback.
    """

    def __init__(self, config: Optional[AudioIOConfig] = None, sample_rate: int = 24000) -> None:
        self.config = config or AudioIOConfig()
        self.sample_rate = sample_rate or getattr(self.config, "output_sample_rate", 24000)

    def play_pcm(self, pcm_bytes: bytes) -> None:
        """Play raw PCM bytes as 24 kHz mono int16 audio.

        Args:
            pcm_bytes: Raw PCM audio data (int16, 24 kHz, mono).

        Raises:
            AudioPlaybackError: If playback fails.
        """
        if not pcm_bytes:
            logger.warning("No audio data to play")
            return

        try:
            audio_array: np.ndarray = np.frombuffer(pcm_bytes, dtype=np.int16)
            if audio_array.size == 0:
                logger.warning("Empty audio array, skipping playback")
                return

            sd.play(audio_array, samplerate=self.sample_rate)
            sd.wait()  # Block until playback is finished
            logger.info("Played %d PCM samples at %d Hz", audio_array.size, self.sample_rate)
        except Exception as exc:
            raise AudioPlaybackError(f"Failed to play PCM audio: {exc}") from exc

    def play_wav(self, wav_path: str | Path) -> None:
        """Play a WAV file through the default output device.

        Args:
            wav_path: Path to the WAV file.

        Raises:
            AudioPlaybackError: If the file is missing or playback fails.
        """
        path = Path(wav_path)
        if not path.exists():
            raise AudioPlaybackError(f"Audio file does not exist: {path}")

        try:
            import soundfile as sf
        except ImportError:
            # Fallback: read WAV with wave module and play raw PCM
            try:
                import wave

                with wave.open(str(path), "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    rate = wf.getframerate()
                    audio_array = np.frombuffer(frames, dtype=np.int16)
                sd.play(audio_array, samplerate=rate)
                sd.wait()
                logger.info("Played WAV file: %s", path)
            except Exception as exc:
                raise AudioPlaybackError(f"Failed to play WAV file {path}: {exc}") from exc
        else:
            try:
                data, samplerate = sf.read(str(path), dtype="int16")
                sd.play(data, samplerate=samplerate)
                sd.wait()
                logger.info("Played WAV file: %s", path)
            except Exception as exc:
                raise AudioPlaybackError(f"Failed to play WAV file {path}: {exc}") from exc

    def play_and_cleanup(self, audio_path: str | Path) -> None:
        """Play a temporary WAV file and delete it afterward.

        Args:
            audio_path: Path to the WAV file to play and remove.
        """
        path = Path(audio_path)
        try:
            self.play_wav(path)
        finally:
            path.unlink(missing_ok=True)
