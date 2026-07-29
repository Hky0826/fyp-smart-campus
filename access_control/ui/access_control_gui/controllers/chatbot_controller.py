"""Chatbot audio worker for the native kiosk UI."""

from __future__ import annotations

import base64
import logging
import math
import os
import queue
import threading
import time
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Property, QThread, Signal, Slot

from access_control.audio_io.audio_player import AudioPlayer
from access_control.audio_io.config import AudioIOConfig
from access_control.audio_io.recorder import AudioRecorder

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
        self._recording_stop_requested = threading.Event()
        self._stream_cancel_requested = threading.Event()
        self._audio_only_stop_requested = threading.Event()
        self._recording_active = threading.Event()
        self._player: AudioPlayer | None = None
        self._player_lock = threading.Lock()

    def run(self) -> None:
        self._recording_stop_requested.clear()
        self._stream_cancel_requested.clear()
        self._audio_only_stop_requested.clear()
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
        with self._player_lock:
            self._player = player
        recording_path: Path | None = None

        try:
            self.listeningChanged.emit(True)
            self._recording_active.set()
            result = recorder.record(cancel_requested=self._recording_stop_requested.is_set)
            self._recording_active.clear()
            recording_path = result.path
            self.listeningChanged.emit(False)

            if recording_path and recording_path.exists() and recording_path.stat().st_size >= 512:
                voice_stats = _wav_voice_stats(recording_path)
                logger.info("Push-to-Talk recorded stats: %s", voice_stats)
                if not _has_voice(voice_stats):
                    self.errorOccurred.emit("No speech detected. Please try speaking again.")
                    return
                self.busyChanged.emit(True)
                audio_queue: queue.Queue[bytes | None] = queue.Queue()

                def receive_stream() -> None:
                    try:
                        emitted_text = False
                        for event_obj in self._api.send_chat_audio_stream_file(
                            recording_path,
                            "audio/wav",
                            cancel_requested=self._stream_cancel_requested.is_set,
                        ):
                            if self._stream_cancel_requested.is_set():
                                break
                            event = event_obj.get("event")
                            data = event_obj.get("data", {})
                            if event == "metadata":
                                text = data.get("transcribed_input")
                                if text:
                                    self.transcribedTextReceived.emit(text)
                            elif event == "chunk":
                                text = data.get("text")
                                if text:
                                    emitted_text = True
                                    self.textChunkReceived.emit(str(text))
                            elif event == "done":
                                fallback = data.get("text_response")
                                if fallback and not emitted_text:
                                    emitted_text = True
                                    self.textChunkReceived.emit(str(fallback))
                                self.responseReceived.emit(dict(data))
                            elif event == "error":
                                self.errorOccurred.emit(str(data.get("message") or "Audio chat failed."))
                            elif event == "tts_error":
                                logger.warning("TTS unavailable for streamed sentence: %s", data.get("message"))
                            if event == "audio":
                                chunk = data.get("chunk")
                                if chunk and not self._audio_only_stop_requested.is_set():
                                    audio_queue.put(base64.b64decode(chunk))
                    except Exception as exc:
                        if not self._stream_cancel_requested.is_set():
                            self.errorOccurred.emit(str(exc))
                    finally:
                        audio_queue.put(None)

                receiver = threading.Thread(target=receive_stream, name="chat-stream-receiver", daemon=True)
                receiver.start()

                def stream_audio():
                    while (
                        not self._stream_cancel_requested.is_set()
                        and not self._audio_only_stop_requested.is_set()
                    ):
                        try:
                            chunk = audio_queue.get(timeout=0.2)
                        except queue.Empty:
                            continue
                        if chunk is None:
                            break
                        yield chunk

                try:
                    player.play_pcm_stream(stream_audio())
                finally:
                    if not self._audio_only_stop_requested.is_set():
                        self._stream_cancel_requested.set()
                    player.stop()
                    # The recording file is still owned by the multipart
                    # request until this receiver exits. Do not let this
                    # QThread finish while it can still emit Qt signals.
                    receiver.join()
        except Exception as exc:
            logger.error("Push-to-Talk audio processing error: %s", exc)
            if not self._stream_cancel_requested.is_set() and not self._recording_stop_requested.is_set():
                self.errorOccurred.emit(str(exc))
        finally:
            with self._player_lock:
                self._player = None
            self._recording_active.clear()
            self.listeningChanged.emit(False)
            self.busyChanged.emit(False)
            if recording_path is not None:
                _remove_recording_file(recording_path)

    def stop_recording(self) -> None:
        if self._recording_active.is_set():
            self._recording_stop_requested.set()
        else:
            self._stream_cancel_requested.set()
            with self._player_lock:
                player = self._player
            if player is not None:
                player.stop()

    def stop_audio_only(self) -> None:
        """Stop speaker playback while allowing text/final events to finish."""
        if self._recording_active.is_set():
            return
        self._audio_only_stop_requested.set()
        with self._player_lock:
            player = self._player
        if player is not None:
            player.stop()


class _GreetingWorker(QThread):
    errorOccurred = Signal(str)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._player: AudioPlayer | None = None

    def run(self) -> None:
        try:
            payload = self._api.request_greeting_audio()
            if self.isInterruptionRequested():
                return
            encoded = payload.get("audio_response")
            if not encoded:
                return
            config = AudioIOConfig()
            player = AudioPlayer(config, sample_rate=int(payload.get("sample_rate") or TTS_OUTPUT_SAMPLE_RATE))
            self._player = player
            if self.isInterruptionRequested():
                player.stop()
                return
            player.play_pcm_stream(iter((base64.b64decode(encoded),)))
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            self.errorOccurred.emit(str(exc))

    def stop(self) -> None:
        self.requestInterruption()
        if self._player is not None:
            self._player.stop()


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
        self._final_response_seen = False
        
        self._greeting_worker: _GreetingWorker | None = None

    @Slot()
    def startPushToTalk(self) -> None:
        if self._busy or self._listening:
            return
        self._error = ""
        self._partial_text = ""
        self._transcribed_text = ""
        self._final_response_seen = False
        self.errorChanged.emit()
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()
        worker = _PushToTalkWorker(self._api)
        worker.listeningChanged.connect(self._set_listening)
        worker.busyChanged.connect(self._set_busy)
        worker.errorOccurred.connect(self._set_error)
        worker.responseReceived.connect(self._on_worker_response)
        worker.textChunkReceived.connect(self._on_text_chunk)
        worker.transcribedTextReceived.connect(self._on_transcribed_text)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._worker = worker
        worker.start()

    @Slot(str)
    def _on_text_chunk(self, chunk: str) -> None:
        # Render complete received chunks immediately; synthesis/playback is
        # handled independently by the worker's audio queue.
        self._partial_text += chunk
        self.partialTextChanged.emit()

    @Slot(str)
    def _on_transcribed_text(self, text: str) -> None:
        self._transcribed_text = text
        self.transcribedTextChanged.emit()

    @Slot(dict)
    def _on_worker_response(self, payload: dict) -> None:
        self._final_response_seen = True
        self.responseReceived.emit(payload)

    @Slot()
    def stopPushToTalk(self) -> None:
        if self._worker:
            self._worker.stop_recording()

    @Slot()
    def stopAudioPlayback(self) -> None:
        if self._worker:
            self._worker.stop_audio_only()

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
        if self._worker:
            self.stopPushToTalk()
        if self._greeting_worker:
            self._greeting_worker.stop()

    @Slot()
    def toggleMute(self) -> None:
        self.setMuted(not self._muted)

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        muted = bool(muted)
        if muted == self._muted:
            return
        self._muted = muted
        self.mutedChanged.emit()

    @Slot()
    def playGreeting(self) -> None:
        if self._greeting_worker and self._greeting_worker.isRunning():
            return
        worker = _GreetingWorker(self._api)
        worker.errorOccurred.connect(self._set_error)
        worker.finished.connect(lambda: self._cleanup_greeting_worker(worker))
        self._greeting_worker = worker
        worker.start()

    def shutdown(self) -> None:
        if self._worker:
            self._worker.stop_recording()
            self._worker.wait(2000)
        if self._greeting_worker:
            self._greeting_worker.stop()
            self._greeting_worker.wait(2000)

    def _cleanup_worker(self, worker: _PushToTalkWorker) -> None:
        if self._worker is worker:
            self._worker = None
            if self._final_response_seen:
                self._partial_text = ""
                self._transcribed_text = ""
                self.partialTextChanged.emit()
                self.transcribedTextChanged.emit()
        worker.deleteLater()

    def _cleanup_greeting_worker(self, worker: _GreetingWorker) -> None:
        if self._greeting_worker is worker:
            self._greeting_worker = None
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


def _remove_recording_file(path: Path) -> None:
    """Remove a completed recording, tolerating Windows handle release lag."""
    for attempt in range(5):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == 4:
                logger.warning("Could not remove temporary recording: %s", path)
                return
            time.sleep(0.1 * (attempt + 1))


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
