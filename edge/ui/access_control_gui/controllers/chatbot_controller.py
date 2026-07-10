"""Chatbot audio worker for the native kiosk UI."""

from __future__ import annotations

import base64
import logging
import math
import os
import threading
import time
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Property, QThread, Signal, Slot

from edge.audio_io.audio_player import AudioPlayer
from edge.audio_io.config import AudioIOConfig
from edge.audio_io.recorder import AudioRecorder

from .api_client import KioskApiClient


logger = logging.getLogger(__name__)
VOICE_RECORDING_MS = int(os.getenv("EDGE_GUI_VOICE_RECORDING_MS", "4000"))
VOICE_RESTART_DELAY_MS = int(os.getenv("EDGE_GUI_VOICE_RESTART_DELAY_MS", "250"))
TTS_OUTPUT_SAMPLE_RATE = int(os.getenv("EDGE_GUI_TTS_OUTPUT_SAMPLE_RATE", "24000"))
VOICE_MIN_RECORD_SECONDS = float(os.getenv("EDGE_GUI_VOICE_MIN_RECORD_SECONDS", "0.35"))
VOICE_SILENCE_SECONDS = float(os.getenv("EDGE_GUI_VOICE_SILENCE_SECONDS", "0.55"))
VOICE_SILENCE_RMS = float(os.getenv("EDGE_GUI_VOICE_SILENCE_RMS", "700"))
MIN_AUDIO_RMS = float(os.getenv("EDGE_GUI_AUDIO_MIN_RMS", "500"))
MIN_AUDIO_PEAK = float(os.getenv("EDGE_GUI_AUDIO_MIN_PEAK", "1500"))
MIN_VOICED_RATIO = float(os.getenv("EDGE_GUI_AUDIO_MIN_VOICED_RATIO", "0.03"))
VOICE_BLOCK_MS = int(os.getenv("EDGE_GUI_AUDIO_VOICE_BLOCK_MS", "100"))


class _AudioLoopWorker(QThread):
    listeningChanged = Signal(bool)
    busyChanged = Signal(bool)
    responseReceived = Signal(dict)
    errorOccurred = Signal(str)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._running = False
        self._stop_requested = threading.Event()

    def run(self) -> None:
        self._running = True
        self._stop_requested.clear()
        config = AudioIOConfig()
        config = replace(
            config,
            max_record_seconds=max(0.5, VOICE_RECORDING_MS / 1000.0),
            min_record_seconds=max(0.1, VOICE_MIN_RECORD_SECONDS),
            silence_duration_seconds=max(0.1, VOICE_SILENCE_SECONDS),
            silence_rms_threshold=VOICE_SILENCE_RMS,
            recording_block_ms=max(20, VOICE_BLOCK_MS),
        )
        recorder = AudioRecorder(config)
        player = AudioPlayer(config, sample_rate=TTS_OUTPUT_SAMPLE_RATE)

        while self._running:
            recording_path: Path | None = None
            try:
                self.listeningChanged.emit(True)
                result = recorder.record(cancel_requested=self._stop_requested.is_set)
                recording_path = result.path
                self.listeningChanged.emit(False)
                if not self._running:
                    break

                if recording_path.stat().st_size < 1024:
                    self.msleep(VOICE_RESTART_DELAY_MS)
                    continue

                voice_stats = _wav_voice_stats(recording_path)
                if not _has_voice(voice_stats):
                    self.msleep(VOICE_RESTART_DELAY_MS)
                    continue

                self.busyChanged.emit(True)
                response = self._api.send_chat_audio_file(recording_path, "audio/wav")
                self.responseReceived.emit(response)
                audio_response = response.get("audio_response")
                if audio_response and self._running:
                    audio_pcm = base64.b64decode(str(audio_response))
                    logger.info(
                        "GUI audio chat TTS received. base64_chars=%d pcm_bytes=%d",
                        len(str(audio_response)),
                        len(audio_pcm),
                    )
                    player.play_pcm(audio_pcm)
            except Exception as exc:  # pragma: no cover - hardware/network runtime
                self.errorOccurred.emit(str(exc))
                time.sleep(max(0.25, VOICE_RESTART_DELAY_MS / 1000.0))
            finally:
                self.listeningChanged.emit(False)
                self.busyChanged.emit(False)
                if recording_path is not None:
                    recording_path.unlink(missing_ok=True)

            self.msleep(VOICE_RESTART_DELAY_MS)

    def stop(self) -> None:
        self._running = False
        self._stop_requested.set()


class ChatbotController(QObject):
    listeningChanged = Signal()
    busyChanged = Signal()
    errorChanged = Signal()
    mutedChanged = Signal()
    responseReceived = Signal(dict)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._worker: _AudioLoopWorker | None = None
        self._stopping_workers: list[_AudioLoopWorker] = []
        self._start_requested = False
        self._listening = False
        self._busy = False
        self._error = ""
        self._muted = False

    @Slot()
    def startVoiceLoop(self) -> None:
        if self._muted or self._stopping_workers:
            self._start_requested = bool(self._stopping_workers and not self._muted)
            self._set_listening(False)
            self._set_busy(False)
            return
        if self._worker and self._worker.isRunning():
            return
        self._start_requested = False
        worker = _AudioLoopWorker(self._api)
        worker.listeningChanged.connect(self._set_listening)
        worker.busyChanged.connect(self._set_busy)
        worker.errorOccurred.connect(self._set_error)
        worker.responseReceived.connect(self.responseReceived)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._worker = worker
        worker.start()

    @Slot()
    def stopVoiceLoop(self) -> None:
        self._start_requested = False
        if not self._worker:
            self._set_listening(False)
            self._set_busy(False)
            return
        worker = self._worker
        self._worker = None
        worker.stop()
        if worker.isRunning():
            self._stopping_workers.append(worker)
        else:
            self._cleanup_worker(worker)
        self._set_listening(False)
        self._set_busy(False)

    @Slot()
    def toggleMute(self) -> None:
        self.setMuted(not self._muted)

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        if muted == self._muted:
            return
        self._muted = muted
        if self._muted:
            self.stopVoiceLoop()
        self.mutedChanged.emit()

    def shutdown(self) -> None:
        self.stopVoiceLoop()
        workers = list(self._stopping_workers)
        if self._worker is not None:
            workers.append(self._worker)
        for worker in workers:
            worker.stop()
            worker.wait(3000)

    def _cleanup_worker(self, worker: _AudioLoopWorker) -> None:
        if self._worker is worker:
            self._worker = None
        if worker in self._stopping_workers:
            self._stopping_workers.remove(worker)
        worker.deleteLater()
        if self._start_requested and not self._stopping_workers and not self._muted:
            self._start_requested = False
            self.startVoiceLoop()

    @Slot(bool)
    def _set_listening(self, value: bool) -> None:
        if value == self._listening:
            return
        self._listening = value
        self.listeningChanged.emit()

    @Slot(bool)
    def _set_busy(self, value: bool) -> None:
        if value == self._busy:
            return
        self._busy = value
        self.busyChanged.emit()

    @Slot(str)
    def _set_error(self, message: str) -> None:
        self._error = message
        self.errorChanged.emit()

    def _get_listening(self) -> bool:
        return self._listening

    def _get_busy(self) -> bool:
        return self._busy

    def _get_error(self) -> str:
        return self._error

    def _get_muted(self) -> bool:
        return self._muted

    listening = Property(bool, _get_listening, notify=listeningChanged)
    busy = Property(bool, _get_busy, notify=busyChanged)
    error = Property(str, _get_error, notify=errorChanged)
    muted = Property(bool, _get_muted, notify=mutedChanged)


def _has_voice(stats: dict[str, float]) -> bool:
    return (
        stats["rms"] >= MIN_AUDIO_RMS
        and stats["peak"] >= MIN_AUDIO_PEAK
        and stats["voiced_ratio"] >= MIN_VOICED_RATIO
    )


def _wav_voice_stats(path: Path) -> dict[str, float]:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = max(1, wav_file.getframerate())
            channels = max(1, wav_file.getnchannels())
            frames = wav_file.readframes(wav_file.getnframes())
            if not frames:
                return {"rms": 0.0, "peak": 0.0, "voiced_ratio": 0.0}
            samples = np.frombuffer(frames, dtype="<i2").astype(np.float32)
    except Exception:
        return {"rms": math.inf, "peak": math.inf, "voiced_ratio": 1.0}

    if samples.size == 0:
        return {"rms": 0.0, "peak": 0.0, "voiced_ratio": 0.0}

    if channels > 1 and samples.size >= channels:
        usable = samples[: samples.size - (samples.size % channels)]
        samples = usable.reshape(-1, channels).mean(axis=1)

    rms = float(np.sqrt(np.mean(samples * samples)))
    peak = float(np.max(np.abs(samples)))
    block_size = max(1, int(frame_rate * max(10, VOICE_BLOCK_MS) / 1000))
    block_count = samples.size // block_size
    if block_count <= 0:
        voiced_ratio = 1.0 if rms >= MIN_AUDIO_RMS else 0.0
    else:
        blocks = samples[: block_count * block_size].reshape(block_count, block_size)
        block_rms = np.sqrt(np.mean(blocks * blocks, axis=1))
        voiced_ratio = float(np.mean(block_rms >= MIN_AUDIO_RMS))

    return {"rms": rms, "peak": peak, "voiced_ratio": voiced_ratio}
