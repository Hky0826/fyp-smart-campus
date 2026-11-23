"""Play received PCM audio through the speaker using sounddevice."""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

import numpy as np

try:
    from .config import AudioIOConfig
except ImportError:  # Allows direct script-style imports during local smoke checks.
    from config import AudioIOConfig


logger = logging.getLogger(__name__)


class AudioPlaybackError(RuntimeError):
    """Raised when audio playback fails."""


class AudioPlayer:
    """Play PCM audio data through the configured output device.

    Supports raw PCM bytes (24 kHz mono int16) and WAV file playback.
    Uses ALSA on Linux by default and sounddevice elsewhere.
    """

    def __init__(self, config: Optional[AudioIOConfig] = None, sample_rate: int = 24000) -> None:
        self.config = config or AudioIOConfig()
        self.sample_rate = sample_rate or getattr(self.config, "output_sample_rate", 24000)
        self._stop_requested = threading.Event()
        self._active_stream = None
        self._active_process: subprocess.Popen | None = None
        self._state_lock = threading.Lock()

    def stop(self) -> None:
        """Interrupt any active playback immediately."""
        self._stop_requested.set()
        with self._state_lock:
            stream = self._active_stream
            process = self._active_process
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def play_pcm(self, pcm_bytes: bytes) -> None:
        """Play raw PCM bytes as 24 kHz mono int16 audio.

        Args:
            pcm_bytes: Raw PCM audio data (int16, 24 kHz, mono).

        Raises:
            AudioPlaybackError: If playback fails.
        """
        self._stop_requested.clear()
        if not pcm_bytes:
            logger.warning("No audio data to play")
            return

        if self.config.playback_backend == "alsa":
            self._play_pcm_alsa(pcm_bytes)
            return
        if self.config.playback_backend != "sounddevice":
            raise AudioPlaybackError(
                f"Unsupported playback backend: {self.config.playback_backend}. "
                "Use 'alsa' or 'sounddevice'."
            )
        self._play_pcm_sounddevice(pcm_bytes)

    def _play_pcm_sounddevice(self, pcm_bytes: bytes) -> None:
        try:
            import sounddevice as sd

            audio_array: np.ndarray = np.frombuffer(pcm_bytes, dtype=np.int16)
            if audio_array.size == 0:
                logger.warning("Empty audio array, skipping playback")
                return

            sd.play(audio_array, samplerate=self.sample_rate)
            sd.wait()  # Block until playback is finished
            logger.info("Played %d PCM samples at %d Hz", audio_array.size, self.sample_rate)
        except Exception as exc:
            raise AudioPlaybackError(f"Failed to play PCM audio: {exc}") from exc

    def _play_pcm_alsa(self, pcm_bytes: bytes) -> None:
        if len(pcm_bytes) % 2 != 0:
            raise AudioPlaybackError("PCM audio byte length is not aligned to int16 samples")

        command = [
            "aplay",
            "-q",
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            "1",
            "-t",
            "raw",
        ]
        if self.config.speaker_device is not None:
            command.extend(["-D", _alsa_device_name(self.config.speaker_device)])

        try:
            result = subprocess.run(
                command,
                input=pcm_bytes,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AudioPlaybackError(
                "ALSA playback backend requires aplay. Install it on the edge device with: "
                "sudo apt update && sudo apt install -y alsa-utils"
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="ignore").strip()
            raise AudioPlaybackError(f"ALSA playback failed: {stderr or 'aplay exited with an error'}")

        samples = len(pcm_bytes) // 2
        logger.info("Played %d PCM samples at %d Hz with ALSA", samples, self.sample_rate)

    def play_pcm_stream(self, pcm_chunks: Iterable[bytes]) -> None:
        """Play a stream of raw PCM chunks as one continuous audio output."""
        self._stop_requested.clear()
        if self.config.playback_backend == "alsa":
            self._play_pcm_stream_alsa(pcm_chunks)
            return
        if self.config.playback_backend != "sounddevice":
            raise AudioPlaybackError(
                f"Unsupported playback backend: {self.config.playback_backend}. "
                "Use 'alsa' or 'sounddevice'."
            )
        self._play_pcm_stream_sounddevice(pcm_chunks)

    def _play_pcm_stream_sounddevice(self, pcm_chunks: Iterable[bytes]) -> None:
        try:
            import sounddevice as sd

            samples = 0
            with sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
            ) as stream:
                with self._state_lock:
                    self._active_stream = stream
                for chunk in pcm_chunks:
                    if self._stop_requested.is_set():
                        break
                    if not chunk:
                        continue
                    audio_array: np.ndarray = np.frombuffer(chunk, dtype=np.int16)
                    if audio_array.size == 0:
                        continue
                    block_samples = max(1, self.sample_rate * 20 // 1000)
                    for offset in range(0, audio_array.size, block_samples):
                        if self._stop_requested.is_set():
                            break
                        block = audio_array[offset : offset + block_samples]
                        stream.write(block.reshape(-1, 1))
                        samples += block.size
            logger.info("Streamed %d PCM samples at %d Hz", samples, self.sample_rate)
        except Exception as exc:
            raise AudioPlaybackError(f"Failed to stream PCM audio: {exc}") from exc
        finally:
            with self._state_lock:
                self._active_stream = None

    def _play_pcm_stream_alsa(self, pcm_chunks: Iterable[bytes]) -> None:
        command = [
            "aplay",
            "-q",
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            "1",
            "-t",
            "raw",
        ]
        if self.config.speaker_device is not None:
            command.extend(["-D", _alsa_device_name(self.config.speaker_device)])

        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            with self._state_lock:
                self._active_process = process
        except FileNotFoundError as exc:
            raise AudioPlaybackError(
                "ALSA playback backend requires aplay. Install it on the edge device with: "
                "sudo apt update && sudo apt install -y alsa-utils"
            ) from exc

        total_bytes = 0
        stderr = b""
        try:
            assert process.stdin is not None
            for chunk in pcm_chunks:
                if self._stop_requested.is_set():
                    break
                if not chunk:
                    continue
                if len(chunk) % 2 != 0:
                    raise AudioPlaybackError("PCM audio byte length is not aligned to int16 samples")
                block_bytes = max(2, self.sample_rate * 2 * 20 // 1000)
                block_bytes -= block_bytes % 2
                for offset in range(0, len(chunk), block_bytes):
                    if self._stop_requested.is_set():
                        break
                    block = chunk[offset : offset + block_bytes]
                    process.stdin.write(block)
                    process.stdin.flush()
                    total_bytes += len(block)
            process.stdin.close()
            stderr = process.stderr.read() if process.stderr is not None else b""
            return_code = process.wait()
        except Exception:
            process.kill()
            process.wait()
            raise
        finally:
            with self._state_lock:
                self._active_process = None

        if return_code != 0:
            message = stderr.decode(errors="ignore").strip()
            raise AudioPlaybackError(f"ALSA streaming playback failed: {message or 'aplay exited with an error'}")

        samples = total_bytes // 2
        logger.info("Streamed %d PCM samples at %d Hz with ALSA", samples, self.sample_rate)

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

        if self.config.playback_backend == "alsa":
            self._play_wav_alsa(path)
            return
        if self.config.playback_backend != "sounddevice":
            raise AudioPlaybackError(
                f"Unsupported playback backend: {self.config.playback_backend}. "
                "Use 'alsa' or 'sounddevice'."
            )

        try:
            import soundfile as sf
            import sounddevice as sd
        except ImportError:
            # Fallback: read WAV with wave module and play raw PCM
            try:
                import wave
                import sounddevice as sd

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

    def _play_wav_alsa(self, path: Path) -> None:
        command = ["aplay", "-q"]
        if self.config.speaker_device is not None:
            command.extend(["-D", _alsa_device_name(self.config.speaker_device)])
        command.append(str(path))

        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AudioPlaybackError(
                "ALSA playback backend requires aplay. Install it on the edge device with: "
                "sudo apt update && sudo apt install -y alsa-utils"
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="ignore").strip()
            raise AudioPlaybackError(f"ALSA WAV playback failed: {stderr or 'aplay exited with an error'}")

        logger.info("Played WAV file with ALSA: %s", path)


def _alsa_device_name(device: str | int) -> str:
    if isinstance(device, int):
        return f"hw:{device}"
    return str(device)
