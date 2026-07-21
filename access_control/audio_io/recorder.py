"""Audio recording with silence detection using sounddevice."""

from __future__ import annotations

import logging
import math
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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

    Uses ALSA on Linux by default and sounddevice (PortAudio) elsewhere.
    Records 16 kHz mono int16 PCM and applies RMS-based silence detection
    to automatically stop when the user stops speaking.
    """

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()

    def record(self, cancel_requested: Callable[[], bool] | None = None) -> RecordingResult:
        """Record 16 kHz mono WAV with silence detection.

        Returns:
            RecordingResult with path to the recorded WAV file and duration.
        """
        if self.config.recording_backend == "alsa":
            return self._record_alsa(cancel_requested)
        if self.config.recording_backend != "sounddevice":
            raise RuntimeError(
                f"Unsupported recording backend: {self.config.recording_backend}. "
                "Use 'alsa' or 'sounddevice'."
            )
        return self._record_sounddevice(cancel_requested)

    def _record_sounddevice(self, cancel_requested: Callable[[], bool] | None = None) -> RecordingResult:
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
                "sudo apt update && sudo apt install -y libportaudio2 portaudio19-dev"
            ) from exc

        with sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype="int16",
            blocksize=blocksize,
            device=self.config.microphone_device,
        ) as stream:
            for block_index in range(max_blocks):
                if cancel_requested and cancel_requested():
                    break
                samples, overflowed = stream.read(blocksize)
                if overflowed:
                    logger.warning("Audio recorder input overflowed")
                if cancel_requested and cancel_requested():
                    break

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

    def _record_alsa(self, cancel_requested: Callable[[], bool] | None = None) -> RecordingResult:
        blocksize = max(1, int(self.config.sample_rate * self.config.recording_block_ms / 1000))
        block_seconds = blocksize / self.config.sample_rate
        max_blocks = max(1, math.ceil(self.config.max_record_seconds / block_seconds))
        min_blocks = max(1, math.ceil(self.config.min_record_seconds / block_seconds))
        silence_blocks = max(1, math.ceil(self.config.silence_duration_seconds / block_seconds))
        channels = max(1, int(self.config.channels))
        block_bytes = blocksize * channels * 2

        command = [
            "arecord",
            "-q",
            "-f",
            "S16_LE",
            "-r",
            str(self.config.sample_rate),
            "-c",
            str(channels),
            "-t",
            "raw",
            "-d",
            str(max(1, math.ceil(self.config.max_record_seconds))),
        ]
        if self.config.microphone_device is not None:
            command.extend(["-D", _alsa_device_name(self.config.microphone_device)])

        frames: list[np.ndarray] = []
        silent_count = 0
        started_at = time.monotonic()
        logger.info("Recording speech after activation with ALSA")

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "ALSA recording backend requires arecord. Install it on the edge device with: "
                "sudo apt update && sudo apt install -y alsa-utils"
            ) from exc

        try:
            assert process.stdout is not None
            for block_index in range(max_blocks):
                if cancel_requested and cancel_requested():
                    break
                raw = process.stdout.read(block_bytes)
                if not raw:
                    break
                if cancel_requested and cancel_requested():
                    break

                frame = np.frombuffer(raw, dtype="<i2").copy()
                frames.append(frame)
                rms = self._rms(frame)

                if block_index >= min_blocks and rms < self.config.silence_rms_threshold:
                    silent_count += 1
                    if silent_count >= silence_blocks:
                        break
                else:
                    silent_count = 0
        finally:
            stderr = _stop_process(process)

        if not frames and process.returncode not in (0, None):
            raise RuntimeError(f"ALSA recording failed: {stderr or 'arecord exited without audio'}")

        audio = np.concatenate(frames) if frames else np.array([], dtype=np.int16)
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
            wav_file.setnchannels(self.config.channels)
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


def _alsa_device_name(device: str | int) -> str:
    if isinstance(device, int):
        return f"hw:{device}"
    return str(device)


def _stop_process(process: subprocess.Popen) -> str:
    if process.poll() is None:
        process.terminate()
        try:
            _, stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate(timeout=1.0)
    else:
        _, stderr = process.communicate(timeout=1.0)
    return stderr.decode(errors="ignore").strip() if stderr else ""
