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
from PySide6.QtCore import QObject, Property, QThread, Signal, Slot, QTimer

from edge.audio_io.audio_player import AudioPlayer
from edge.audio_io.config import AudioIOConfig
from edge.audio_io.recorder import AudioRecorder

from .api_client import KioskApiClient


logger = logging.getLogger(__name__)
PTT_MAX_RECORD_SECONDS = float(os.getenv("EDGE_GUI_PTT_MAX_RECORD_SECONDS", "60.0"))
VOICE_RECORDING_MS = int(os.getenv("EDGE_GUI_VOICE_RECORDING_MS", "60000"))
VOICE_RESTART_DELAY_MS = int(os.getenv("EDGE_GUI_VOICE_RESTART_DELAY_MS", "250"))
TTS_OUTPUT_SAMPLE_RATE = int(os.getenv("EDGE_GUI_TTS_OUTPUT_SAMPLE_RATE", "24000"))
VOICE_MIN_RECORD_SECONDS = float(os.getenv("EDGE_GUI_VOICE_MIN_RECORD_SECONDS", "0.1"))
VOICE_SILENCE_SECONDS = float(os.getenv("EDGE_GUI_VOICE_SILENCE_SECONDS", "300.0"))
VOICE_SILENCE_RMS = float(os.getenv("EDGE_GUI_VOICE_SILENCE_RMS", "0.0"))
MIN_AUDIO_RMS = float(os.getenv("EDGE_GUI_AUDIO_MIN_RMS", "50.0"))
MIN_AUDIO_PEAK = float(os.getenv("EDGE_GUI_AUDIO_MIN_PEAK", "100.0"))
MIN_VOICED_RATIO = float(os.getenv("EDGE_GUI_AUDIO_MIN_VOICED_RATIO", "0.001"))
VOICE_BLOCK_MS = int(os.getenv("EDGE_GUI_AUDIO_VOICE_BLOCK_MS", "100"))


class _PushToTalkWorker(QThread):
    listeningChanged = Signal(bool)
    busyChanged = Signal(bool)
    responseReceived = Signal(dict)
    errorOccurred = Signal(str)
    textChunkReceived = Signal(str)
    transcribedTextReceived = Signal(str)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._stop_requested = threading.Event()

    def run(self) -> None:
        self._stop_requested.clear()
        config = AudioIOConfig()
        config = replace(
            config,
            max_record_seconds=max(30.0, PTT_MAX_RECORD_SECONDS),
            min_record_seconds=0.1,
            silence_duration_seconds=300.0,
            silence_rms_threshold=0.0,
            recording_block_ms=max(20, VOICE_BLOCK_MS),
        )
        recorder = AudioRecorder(config)
        player = AudioPlayer(config, sample_rate=TTS_OUTPUT_SAMPLE_RATE)
        recording_path: Path | None = None

        try:
            self.listeningChanged.emit(True)
            result = recorder.record(cancel_requested=self._stop_requested.is_set)
            recording_path = result.path
            self.listeningChanged.emit(False)

            if recording_path and recording_path.exists() and recording_path.stat().st_size >= 512:
                voice_stats = _wav_voice_stats(recording_path)
                logger.info("Push-to-Talk recorded stats: %s", voice_stats)
                self.busyChanged.emit(True)
                def stream_audio():
                    for event_obj in self._api.send_chat_audio_stream_file(recording_path, "audio/wav"):
                        event = event_obj.get("event")
                        data = event_obj.get("data", {})
                        if event == "metadata":
                            text = data.get("transcribed_input")
                            if text:
                                self.transcribedTextReceived.emit(text)
                        elif event == "chunk":
                            text = data.get("text")
                            if text:
                                self.textChunkReceived.emit(text)
                        elif event == "audio":
                            chunk = data.get("chunk")
                            if chunk:
                                yield base64.b64decode(chunk)
                
                logger.info("GUI audio chat TTS stream started.")
                player.play_pcm_stream(stream_audio())
        except Exception as exc:
            logger.error("Push-to-Talk audio processing error: %s", exc)
            self.errorOccurred.emit(str(exc))
        finally:
            self.listeningChanged.emit(False)
            self.busyChanged.emit(False)
            if recording_path is not None:
                recording_path.unlink(missing_ok=True)

    def stop_recording(self) -> None:
        self._stop_requested.set()


class ChatbotController(QObject):
    listeningChanged = Signal()
    busyChanged = Signal()
    errorChanged = Signal()
    mutedChanged = Signal()
    partialTextChanged = Signal()
    transcribedTextChanged = Signal()
    responseReceived = Signal(dict)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._worker: _PushToTalkWorker | None = None
        self._listening = False
        self._busy = False
        self._error = ""
        self._muted = False
        self._partial_text = ""
        self._transcribed_text = ""
        
        self._typing_queue = ""
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(40)  # 40ms per chunk (25 cps)
        self._typing_timer.timeout.connect(self._on_typing_tick)

    @Slot()
    def startPushToTalk(self) -> None:
        if self._busy or self._listening:
            return
        self._error = ""
        self._partial_text = ""
        self._transcribed_text = ""
        self._typing_queue = ""
        self._typing_timer.stop()
        self.errorChanged.emit()
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()
        worker = _PushToTalkWorker(self._api)
        worker.listeningChanged.connect(self._set_listening)
        worker.busyChanged.connect(self._set_busy)
        worker.errorOccurred.connect(self._set_error)
        worker.responseReceived.connect(self.responseReceived)
        worker.textChunkReceived.connect(self._on_text_chunk)
        worker.transcribedTextReceived.connect(self._on_transcribed_text)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._worker = worker
        worker.start()

    @Slot(str)
    def _on_text_chunk(self, chunk: str) -> None:
        self._typing_queue += chunk
        if not self._typing_timer.isActive():
            self._typing_timer.start()

    @Slot()
    def _on_typing_tick(self) -> None:
        if not self._typing_queue:
            self._typing_timer.stop()
            if self._worker is None:
                self._partial_text = ""
                self._transcribed_text = ""
                self.partialTextChanged.emit()
                self.transcribedTextChanged.emit()
            return
            
        # Type a small chunk of characters per tick to keep up with fast reading
        chars_to_type = 1
        self._partial_text += self._typing_queue[:chars_to_type]
        self._typing_queue = self._typing_queue[chars_to_type:]
        self.partialTextChanged.emit()

    @Slot(str)
    def _on_transcribed_text(self, text: str) -> None:
        self._transcribed_text = text
        self.transcribedTextChanged.emit()

    @Slot()
    def stopPushToTalk(self) -> None:
        if self._worker and self._listening:
            self._worker.stop_recording()

    @Slot()
    def togglePushToTalk(self) -> None:
        if self._listening:
            self.stopPushToTalk()
        elif not self._busy:
            self.startPushToTalk()

    @Slot()
    def startVoiceLoop(self) -> None:
        pass

    @Slot()
    def stopVoiceLoop(self) -> None:
        if self._worker and self._listening:
            self.stopPushToTalk()

    @Slot()
    def toggleMute(self) -> None:
        pass

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        pass

    def shutdown(self) -> None:
        if self._worker:
            self._worker.stop_recording()
            self._worker.wait(2000)

    def _cleanup_worker(self, worker: _PushToTalkWorker) -> None:
        if self._worker is worker:
            self._worker = None
            if not self._typing_queue and not self._typing_timer.isActive():
                self._partial_text = ""
                self._transcribed_text = ""
                self.partialTextChanged.emit()
                self.transcribedTextChanged.emit()
        worker.deleteLater()

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

    def _get_partial_text(self) -> str:
        return self._partial_text

    def _get_transcribed_text(self) -> str:
        return self._transcribed_text

    listening = Property(bool, _get_listening, notify=listeningChanged)
    busy = Property(bool, _get_busy, notify=busyChanged)
    error = Property(str, _get_error, notify=errorChanged)
    muted = Property(bool, _get_muted, notify=mutedChanged)
    partialText = Property(str, _get_partial_text, notify=partialTextChanged)
    transcribedText = Property(str, _get_transcribed_text, notify=transcribedTextChanged)


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
