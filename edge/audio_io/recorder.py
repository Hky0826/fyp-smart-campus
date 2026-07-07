"""Audio recording with silence detection using sounddevice."""

from __future__ import annotations

import logging
import math
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordingResult:
    """Recorded speech WAV file metadata."""

    path: Path
    duration_seconds: float


class AudioRecorder:
    """Record microphone audio until speech ends or max duration reached.

    Uses sounddevice (PortAudio) for cross-platform microphone input.
    Records 16 kHz mono int16 PCM and applies RMS-based silence detection
    to automatically stop when the user stops speaking.
    """

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()

    def record(self) -> RecordingResult:
        """Record 16 kHz mono WAV with silence detection using sounddevice.

        Returns:
            RecordingResult with path to the recorded WAV file and duration.
        """
        blocksize = max(1, int(self.config.sample_rate * self.config.recording_block_ms / 1000))
        block_seconds = blocksize / self.config.sample_rate
        max_blocks = max(1, math.ceil(self.config.max_record_seconds / block_seconds))
        min_blocks = max(1, math.ceil(self.config.min_record_seconds / block_seconds))
        silence_blocks = max(1, math.ceil(self.config.silence_duration_seconds / block_seconds))

        frames: list = []
        silent_count = 0
        started_at = time.monotonic()
        logger.info("Recording speech after activation")

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice is required for recording.") from exc
        except OSError as exc:
            raise RuntimeError(
                "PortAudio is required for microphone recording. Install it on the edge device with: "
                "sudo apt update && sudo apt install -y libportaudio2 portaudio19-dev alsa-utils"
            ) from exc

        with sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=blocksize,
            device=self.config.microphone_device,
        ) as stream:
            for block_index in range(max_blocks):
                samples, overflowed = stream.read(blocksize)
                if overflowed:
                    logger.warning("Audio recorder input overflowed")

                frame = np.asarray(samples, dtype=np.int16).reshape(-1)
                frames.append(frame.copy())
                rms = self._rms(frame)

                if block_index >= min_blocks and rms < self.config.silence_rms_threshold:
                    silent_count += 1
                    if silent_count >= silence_blocks:
                        break
                else:
                    silent_count = 0

        if frames:
            audio = np.concatenate(frames)
        else:
            audio = np.array([], dtype=np.int16)

        path = self._write_wav(audio)
        duration_seconds = time.monotonic() - started_at
        logger.info("Recorded %.2fs of speech to %s", duration_seconds, path)
        return RecordingResult(path=path, duration_seconds=duration_seconds)

    @staticmethod
    def _rms(frame: np.ndarray) -> float:
        """Compute the root-mean-square amplitude of a frame."""
        if frame.size == 0:
            return 0.0
        samples = frame.astype(np.float32)
        return float(np.sqrt(np.mean(samples * samples)))

    def _write_wav(self, audio: np.ndarray) -> Path:
        """Write int16 PCM audio data to a temporary WAV file."""
        path = self._temporary_wav_path()

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.config.sample_rate)
            wav_file.writeframes(audio.astype("<i2").tobytes())
        return path

    def _temporary_wav_path(self) -> Path:
        """Create a unique temporary WAV path in the configured temp directory."""
        self.config.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".wav",
            prefix="edge_recording_",
            dir=str(self.config.temp_dir),
        ) as temp_file:
            return Path(temp_file.name)
