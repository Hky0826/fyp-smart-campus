"""Speech recording with simple silence detection."""

from __future__ import annotations

import logging
import math
import shlex
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

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


class SpeechRecorder:
    """Record microphone audio until speech ends or a maximum duration is reached."""

    def __init__(self, config: AudioIOConfig | None = None) -> None:
        self.config = config or AudioIOConfig()

    def record(self) -> RecordingResult:
        """Record a 16 kHz mono WAV file suitable for whisper.cpp."""
        backend = self.config.recording_backend.strip().lower()
        if backend in {"arecord", "alsa"}:
            return self._record_arecord()
        if backend == "sounddevice":
            return self._record_sounddevice()
        raise RuntimeError(f"Unsupported EDGE_AUDIO_RECORDING_BACKEND: {self.config.recording_backend}")

    def _record_arecord(self) -> RecordingResult:
        command = shlex.split(self.config.audio_recorder_command)
        if not command:
            raise RuntimeError("EDGE_AUDIO_RECORDER_COMMAND is empty")
        executable = command[0]
        if shutil.which(executable) is None and not Path(executable).exists():
            raise RuntimeError(f"Audio recording command is not available: {executable}")

        path = self._temporary_wav_path()
        duration_seconds = max(1, math.ceil(self.config.max_record_seconds))
        capture_command = [
            *command,
            "-q",
            "-f",
            "S16_LE",
            "-r",
            str(self.config.sample_rate),
            "-c",
            str(self.config.channels),
            "-d",
            str(duration_seconds),
        ]
        if self.config.alsa_capture_device:
            capture_command.extend(["-D", self.config.alsa_capture_device])
        capture_command.append(str(path))

        started_at = time.monotonic()
        logger.info("Recording speech after activation with arecord")
        try:
            result = subprocess.run(
                capture_command,
                check=False,
                capture_output=True,
                text=True,
                timeout=duration_seconds + 5,
            )
        except subprocess.TimeoutExpired as exc:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"arecord timed out after {duration_seconds + 5}s") from exc
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"Failed to run arecord: {exc}") from exc

        if result.returncode != 0:
            path.unlink(missing_ok=True)
            stderr = result.stderr.strip() or result.stdout.strip() or "no details"
            raise RuntimeError(f"arecord failed with exit code {result.returncode}: {stderr}")
        if not path.exists() or path.stat().st_size <= 44:
            path.unlink(missing_ok=True)
            raise RuntimeError("arecord completed but produced an empty WAV file")

        elapsed_seconds = time.monotonic() - started_at
        logger.info("Recorded %.2fs of speech to %s", elapsed_seconds, path)
        return RecordingResult(path=path, duration_seconds=elapsed_seconds)

    def _record_sounddevice(self) -> RecordingResult:
        """Record with in-process PortAudio. Prefer arecord on Linux edge devices."""
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("sounddevice and numpy are required for recording.") from exc
        except OSError as exc:
            raise RuntimeError(
                "PortAudio is required for microphone recording. Install it on the edge device with: "
                "sudo apt update && sudo apt install -y libportaudio2 portaudio19-dev alsa-utils"
            ) from exc

        blocksize = max(1, int(self.config.sample_rate * self.config.recording_block_ms / 1000))
        block_seconds = blocksize / self.config.sample_rate
        max_blocks = max(1, math.ceil(self.config.max_record_seconds / block_seconds))
        min_blocks = max(1, math.ceil(self.config.min_record_seconds / block_seconds))
        silence_blocks = max(1, math.ceil(self.config.silence_duration_seconds / block_seconds))

        frames: list = []
        silent_count = 0
        started_at = time.monotonic()
        logger.info("Recording speech after activation")

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
                    logger.warning("Speech recorder audio input overflowed")

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
    def _rms(frame) -> float:
        import numpy as np

        if frame.size == 0:
            return 0.0
        samples = frame.astype(np.float32)
        return float(np.sqrt(np.mean(samples * samples)))

    def _write_wav(self, audio) -> Path:
        path = self._temporary_wav_path()

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.config.sample_rate)
            wav_file.writeframes(audio.astype("<i2").tobytes())
        return path

    def _temporary_wav_path(self) -> Path:
        self.config.temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".wav",
            prefix="edge_recording_",
            dir=str(self.config.temp_dir),
        ) as temp_file:
            return Path(temp_file.name)
