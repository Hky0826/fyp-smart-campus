"""Chatbot audio worker for the native kiosk UI."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, QThread, Signal, Slot

from edge.audio_io.audio_player import AudioPlayer
from edge.audio_io.config import AudioIOConfig
from edge.audio_io.recorder import AudioRecorder

from .api_client import KioskApiClient


VOICE_RECORDING_MS = int(os.getenv("EDGE_GUI_VOICE_RECORDING_MS", "5500"))
VOICE_RESTART_DELAY_MS = int(os.getenv("EDGE_GUI_VOICE_RESTART_DELAY_MS", "250"))
TTS_OUTPUT_SAMPLE_RATE = int(os.getenv("EDGE_GUI_TTS_OUTPUT_SAMPLE_RATE", "24000"))


class _AudioLoopWorker(QThread):
    listeningChanged = Signal(bool)
    busyChanged = Signal(bool)
    responseReceived = Signal(dict)
    errorOccurred = Signal(str)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._running = False

    def run(self) -> None:
        self._running = True
        config = AudioIOConfig()
        config = replace(config, max_record_seconds=max(0.5, VOICE_RECORDING_MS / 1000.0))
        recorder = AudioRecorder(config)
        player = AudioPlayer(config, sample_rate=TTS_OUTPUT_SAMPLE_RATE)

        while self._running:
            recording_path: Path | None = None
            try:
                self.listeningChanged.emit(True)
                result = recorder.record()
                recording_path = result.path
                self.listeningChanged.emit(False)
                if not self._running:
                    break

                if recording_path.stat().st_size < 1024:
                    self.msleep(VOICE_RESTART_DELAY_MS)
                    continue

                self.busyChanged.emit(True)
                response = self._api.send_chat_audio_file(recording_path, "audio/wav")
                self.responseReceived.emit(response)
                audio_response = response.get("audio_response")
                if audio_response and self._running:
                    player.play_pcm(base64.b64decode(str(audio_response)))
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


class ChatbotController(QObject):
    listeningChanged = Signal()
    busyChanged = Signal()
    errorChanged = Signal()
    responseReceived = Signal(dict)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._worker: _AudioLoopWorker | None = None
        self._listening = False
        self._busy = False
        self._error = ""

    @Slot()
    def startVoiceLoop(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        worker = _AudioLoopWorker(self._api)
        worker.listeningChanged.connect(self._set_listening)
        worker.busyChanged.connect(self._set_busy)
        worker.errorOccurred.connect(self._set_error)
        worker.responseReceived.connect(self.responseReceived)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    @Slot()
    def stopVoiceLoop(self) -> None:
        if not self._worker:
            self._set_listening(False)
            self._set_busy(False)
            return
        self._worker.stop()
        self._worker.wait(1500)
        self._worker = None
        self._set_listening(False)
        self._set_busy(False)

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

    listening = Property(bool, _get_listening, notify=listeningChanged)
    busy = Property(bool, _get_busy, notify=busyChanged)
    error = Property(str, _get_error, notify=errorChanged)

