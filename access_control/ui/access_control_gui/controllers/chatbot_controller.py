"""Chatbot audio worker for the native kiosk UI."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import queue
import threading
import time
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PySide6.QtCore import QObject, Property, QThread, Signal, Slot
import sounddevice as sd
import websockets

from access_control.audio_io.audio_player import AudioPlayer
from access_control.audio_io.config import AudioIOConfig

from .api_client import KioskApiClient


logger = logging.getLogger(__name__)
TTS_OUTPUT_SAMPLE_RATE = int(os.getenv("EDGE_GUI_TTS_OUTPUT_SAMPLE_RATE", "24000"))
MIN_AUDIO_RMS = float(os.getenv("EDGE_GUI_AUDIO_MIN_RMS", "50.0"))
MIN_AUDIO_PEAK = float(os.getenv("EDGE_GUI_AUDIO_MIN_PEAK", "100.0"))
MIN_VOICED_RATIO = float(os.getenv("EDGE_GUI_AUDIO_MIN_VOICED_RATIO", "0.001"))
VOICE_BLOCK_MS = int(os.getenv("EDGE_GUI_AUDIO_VOICE_BLOCK_MS", "100"))
def _load_speech_threshold() -> float:
    env_val = os.getenv("EDGE_LIVE_SPEECH_THRESHOLD")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    for candidate in (Path("shitz/vad_config.json"), Path("vad_config.json")):
        if candidate.exists():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    val = float(cfg.get("speech_threshold_rms", 0.0))
                    if val > 0:
                        return val
            except Exception:
                pass
    return 450.0


SPEECH_THRESHOLD_RMS = _load_speech_threshold()


class _LiveDuplexWorker(QThread):
    """Continuous bi-directional streaming worker for Gemini Live duplex WebSocket."""

    listeningChanged = Signal(bool)
    busyChanged = Signal(bool)
    speechStateChanged = Signal(bool)
    userTranscriptReceived = Signal(str)
    textChunkReceived = Signal(str)
    ragStatusChanged = Signal(str, str)
    navigationReceived = Signal(dict)
    citationsReceived = Signal(list)
    turnCompleted = Signal()
    responseReceived = Signal(dict)
    errorOccurred = Signal(str)

    def __init__(self, api: KioskApiClient, speech_threshold: float = SPEECH_THRESHOLD_RMS) -> None:
        super().__init__()
        self._api = api
        self._speech_threshold = speech_threshold
        self._stop_requested = threading.Event()
        self._audio_play_queue: asyncio.Queue[bytes | None] | None = None
        self._ws: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self) -> None:
        self._stop_requested.clear()
        try:
            live_config = self._api.get_live_config()
            ws_url = live_config.get("ws_url")
            if not ws_url:
                raise RuntimeError("No Live Voice WebSocket URL provided by edge API.")
            asyncio.run(self._duplex_session(ws_url))
        except Exception as exc:
            if not self._stop_requested.is_set():
                logger.error("LiveDuplexWorker error: %s", exc)
                self.errorOccurred.emit(str(exc))
        finally:
            self.listeningChanged.emit(False)
            self.busyChanged.emit(False)
            self.speechStateChanged.emit(False)

    async def _duplex_session(self, ws_url: str) -> None:
        logger.info("Connecting to Gemini Live duplex at %s", ws_url)
        loop = asyncio.get_running_loop()
        self._loop = loop
        mic_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._audio_play_queue = asyncio.Queue()

        playback_busy_until = 0.0
        last_user_query = [""]
        last_assistant_text = [""]
        last_citations: list[list[Any]] = [[]]

        def mic_callback(indata: bytes, frames: int, time_info: Any, status: Any) -> None:
            if self._stop_requested.is_set():
                return
            loop.call_soon_threadsafe(mic_queue.put_nowait, bytes(indata))

        try:
            mic_stream = sd.RawInputStream(
                samplerate=16000,
                channels=1,
                dtype="int16",
                blocksize=1600,
                callback=mic_callback,
            )
            output_stream = sd.RawOutputStream(
                samplerate=24000,
                channels=1,
                dtype="int16",
                blocksize=2400,
            )
        except Exception as exc:
            logger.error("Failed to initialize audio devices: %s", exc)
            self.errorOccurred.emit(f"Audio device error: {exc}")
            return

        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                self._ws = ws
                self.listeningChanged.emit(True)

                async def player_loop() -> None:
                    nonlocal playback_busy_until
                    with output_stream:
                        while not self._stop_requested.is_set():
                            if self._audio_play_queue is None:
                                break
                            try:
                                pcm_bytes = await asyncio.wait_for(self._audio_play_queue.get(), timeout=0.1)
                            except asyncio.TimeoutError:
                                if time.monotonic() >= playback_busy_until:
                                    self.busyChanged.emit(False)
                                continue

                            if pcm_bytes is None or self._stop_requested.is_set():
                                break

                            self.busyChanged.emit(True)
                            duration = len(pcm_bytes) / 48000.0
                            playback_busy_until = max(playback_busy_until, time.monotonic()) + duration + 0.25
                            try:
                                await loop.run_in_executor(None, output_stream.write, pcm_bytes)
                            except Exception as exc:
                                logger.warning("Audio playback chunk write error: %s", exc)

                async def receiver_loop() -> None:
                    try:
                        async for raw_message in ws:
                            if self._stop_requested.is_set():
                                break
                            if isinstance(raw_message, bytes):
                                if self._audio_play_queue:
                                    await self._audio_play_queue.put(raw_message)
                                continue

                            try:
                                msg = json.loads(raw_message)
                            except Exception:
                                continue

                            event = msg.get("event")
                            data = msg.get("data") or {}

                            if event in ("session_ready", "ready"):
                                self.listeningChanged.emit(True)
                            elif event in ("user_transcript", "transcript"):
                                text = data.get("text", "")
                                if text:
                                    last_user_query[0] = text
                                    self.userTranscriptReceived.emit(text)
                            elif event == "rag_status":
                                st = data.get("status", "")
                                q = data.get("query", "")
                                self.ragStatusChanged.emit(st, q)
                            elif event == "navigation":
                                self.navigationReceived.emit(data)
                            elif event == "rag_complete":
                                cites = data.get("citations") or data.get("sources") or []
                                last_citations[0] = cites
                                self.citationsReceived.emit(cites)
                            elif event == "output_transcript":
                                tok = data.get("text", "")
                                if tok:
                                    last_assistant_text[0] += tok
                                    self.textChunkReceived.emit(tok)
                            elif event == "audio":
                                b64_chunk = data.get("chunk", "")
                                if b64_chunk:
                                    pcm = base64.b64decode(b64_chunk)
                                    if self._audio_play_queue:
                                        await self._audio_play_queue.put(pcm)
                            elif event == "turn_complete":
                                self.turnCompleted.emit()
                                user_q = last_user_query[0]
                                bot_a = last_assistant_text[0]
                                cites = last_citations[0]
                                last_user_query[0] = ""
                                last_assistant_text[0] = ""
                                last_citations[0] = []
                                if user_q or bot_a:
                                    self.responseReceived.emit({
                                        "transcribed_input": user_q,
                                        "text_response": bot_a,
                                        "citations": cites,
                                    })
                            elif event == "interrupted":
                                playback_busy_until = 0.0
                                if self._audio_play_queue:
                                    while not self._audio_play_queue.empty():
                                        try:
                                            self._audio_play_queue.get_nowait()
                                        except Exception:
                                            break
                                self.busyChanged.emit(False)
                            elif event == "error":
                                self.errorOccurred.emit(str(data.get("message") or "Unknown error"))
                    except websockets.ConnectionClosed:
                        pass
                    except asyncio.CancelledError:
                        pass

                async def sender_loop() -> None:
                    nonlocal playback_busy_until
                    is_speaking = False
                    silence_started = 0.0
                    barge_in_streak = 0

                    with mic_stream:
                        while not self._stop_requested.is_set():
                            pcm_chunk = await mic_queue.get()
                            if pcm_chunk is None or self._stop_requested.is_set():
                                break

                            # Calculate RMS
                            samples = np.frombuffer(pcm_chunk, dtype=np.int16).astype(np.float32)
                            rms = float(np.sqrt(np.mean(samples * samples))) if samples.size > 0 else 0.0
                            now = time.monotonic()
                            is_playing = (now < playback_busy_until) or (
                                self._audio_play_queue is not None and not self._audio_play_queue.empty()
                            )

                            # Echo suppression & barge-in
                            if is_playing:
                                barge_threshold = max(2800.0, self._speech_threshold * 3.5)
                                if rms >= barge_threshold:
                                    barge_in_streak += 1
                                else:
                                    barge_in_streak = 0

                                if barge_in_streak >= 2:
                                    barge_in_streak = 0
                                    playback_busy_until = 0.0
                                    if self._audio_play_queue:
                                        while not self._audio_play_queue.empty():
                                            try:
                                                self._audio_play_queue.get_nowait()
                                            except Exception:
                                                break
                                    self.busyChanged.emit(False)
                                    try:
                                        await ws.send(json.dumps({"event": "client_barge_in"}))
                                    except Exception:
                                        pass
                                else:
                                    continue
                            else:
                                barge_in_streak = 0

                            try:
                                await ws.send(pcm_chunk)
                            except Exception:
                                break

                            # Client VAD: 450ms silence detection
                            if rms >= self._speech_threshold:
                                if not is_speaking:
                                    is_speaking = True
                                    self.speechStateChanged.emit(True)
                                silence_started = 0.0
                            elif is_speaking:
                                if silence_started == 0.0:
                                    silence_started = now
                                elif (now - silence_started) >= 0.45:
                                    is_speaking = False
                                    silence_started = 0.0
                                    self.speechStateChanged.emit(False)
                                    try:
                                        await ws.send(json.dumps({"event": "activity_end"}))
                                    except Exception:
                                        pass

                player_task = asyncio.create_task(player_loop())
                receiver_task = asyncio.create_task(receiver_loop())
                sender_task = asyncio.create_task(sender_loop())

                while not self._stop_requested.is_set():
                    await asyncio.sleep(0.1)

                player_task.cancel()
                receiver_task.cancel()
                sender_task.cancel()
                await mic_queue.put(None)
                if self._audio_play_queue:
                    await self._audio_play_queue.put(None)
        except Exception as exc:
            if not self._stop_requested.is_set():
                logger.error("Duplex session error: %s", exc)
                self.errorOccurred.emit(str(exc))

    def stop(self) -> None:
        self._stop_requested.set()

    def stop_audio_playback(self) -> None:
        if self._audio_play_queue:
            while not self._audio_play_queue.empty():
                try:
                    self._audio_play_queue.get_nowait()
                except Exception:
                    break
        self.busyChanged.emit(False)
        if self._ws and self._loop:
            try:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._ws.send(json.dumps({"event": "client_barge_in"})))
                )
            except Exception:
                pass


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
    speechStateChanged = Signal()
    errorChanged = Signal()
    mutedChanged = Signal()
    partialTextChanged = Signal()
    transcribedTextChanged = Signal()
    ragStatusChanged = Signal()
    currentNavigationChanged = Signal()
    citationsChanged = Signal()
    responseReceived = Signal(dict)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._worker: _LiveDuplexWorker | None = None
        self._listening = False
        self._busy = False
        self._speaking = False
        self._error = ""
        self._muted = False
        self._partial_text = ""
        self._transcribed_text = ""
        self._rag_status = ""
        self._current_navigation: dict[str, Any] = {}
        self._citations: list[Any] = []
        self._greeting_worker: _GreetingWorker | None = None

    @Slot()
    def startVoiceLoop(self) -> None:
        if self._muted:
            return
        if self._worker and self._worker.isRunning():
            return
        self._error = ""
        self._partial_text = ""
        self._transcribed_text = ""
        self._rag_status = ""
        self.errorChanged.emit()
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()
        self.ragStatusChanged.emit()

        worker = _LiveDuplexWorker(self._api)
        worker.listeningChanged.connect(self._set_listening)
        worker.busyChanged.connect(self._set_busy)
        worker.speechStateChanged.connect(self._set_speaking)
        worker.userTranscriptReceived.connect(self._on_transcribed_text)
        worker.textChunkReceived.connect(self._on_text_chunk)
        worker.ragStatusChanged.connect(self._on_rag_status)
        worker.navigationReceived.connect(self._on_navigation)
        worker.citationsReceived.connect(self._on_citations)
        worker.turnCompleted.connect(self._on_turn_completed)
        worker.responseReceived.connect(self._on_worker_response)
        worker.errorOccurred.connect(self._set_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._worker = worker
        worker.start()

    @Slot()
    def stopVoiceLoop(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait(1000)
            self._worker = None
        if self._greeting_worker:
            self._greeting_worker.stop()
        self._set_listening(False)
        self._set_busy(False)
        self._set_speaking(False)

    @Slot()
    def stopAudioPlayback(self) -> None:
        if self._worker:
            self._worker.stop_audio_playback()
        if self._greeting_worker:
            self._greeting_worker.stop()

    @Slot()
    def startPushToTalk(self) -> None:
        """Compatibility alias for hands-free voice loop."""
        self.startVoiceLoop()

    @Slot()
    def stopPushToTalk(self) -> None:
        """Compatibility alias for stopping audio playback."""
        self.stopAudioPlayback()

    @Slot()
    def togglePushToTalk(self) -> None:
        """Compatibility alias."""
        if self._listening:
            self.stopVoiceLoop()
        else:
            self.startVoiceLoop()

    @Slot(str)
    def _on_text_chunk(self, chunk: str) -> None:
        self._partial_text += chunk
        self.partialTextChanged.emit()

    @Slot(str)
    def _on_transcribed_text(self, text: str) -> None:
        self._transcribed_text = text
        self.transcribedTextChanged.emit()

    @Slot(str, str)
    def _on_rag_status(self, status: str, query: str) -> None:
        self._rag_status = f"Searching campus records for '{query}'..." if query else status
        self.ragStatusChanged.emit()

    @Slot(dict)
    def _on_navigation(self, payload: dict[str, Any]) -> None:
        self._current_navigation = payload
        self.currentNavigationChanged.emit()

    @Slot(list)
    def _on_citations(self, citations: list[Any]) -> None:
        self._citations = citations
        self.citationsChanged.emit()

    @Slot()
    def _on_turn_completed(self) -> None:
        self._rag_status = ""
        self.ragStatusChanged.emit()

    @Slot(dict)
    def _on_worker_response(self, payload: dict) -> None:
        self._partial_text = ""
        self._transcribed_text = ""
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()
        self.responseReceived.emit(payload)

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
        if self._muted:
            self.stopVoiceLoop()
        else:
            self.startVoiceLoop()

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
        self.stopVoiceLoop()
        if self._greeting_worker:
            self._greeting_worker.stop()
            self._greeting_worker.wait(1000)

    def _cleanup_worker(self, worker: _LiveDuplexWorker) -> None:
        if self._worker is worker:
            self._worker = None
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

    @Slot(bool)
    def _set_speaking(self, value: bool) -> None:
        if value == self._speaking:
            return
        self._speaking = value
        self.speechStateChanged.emit()

    @Slot(str)
    def _set_error(self, message: str) -> None:
        self._error = message
        self.errorChanged.emit()

    def _get_listening(self) -> bool:
        return self._listening

    def _get_busy(self) -> bool:
        return self._busy

    def _get_speaking(self) -> bool:
        return self._speaking

    def _get_error(self) -> str:
        return self._error

    def _get_muted(self) -> bool:
        return self._muted

    def _get_partial_text(self) -> str:
        return self._partial_text

    def _get_transcribed_text(self) -> str:
        return self._transcribed_text

    def _get_rag_status(self) -> str:
        return self._rag_status

    def _get_current_navigation(self) -> dict[str, Any]:
        return self._current_navigation

    def _get_citations(self) -> list[Any]:
        return self._citations

    listening = Property(bool, _get_listening, notify=listeningChanged)
    busy = Property(bool, _get_busy, notify=busyChanged)
    speaking = Property(bool, _get_speaking, notify=speechStateChanged)
    error = Property(str, _get_error, notify=errorChanged)
    muted = Property(bool, _get_muted, notify=mutedChanged)
    partialText = Property(str, _get_partial_text, notify=partialTextChanged)
    transcribedText = Property(str, _get_transcribed_text, notify=transcribedTextChanged)
    ragStatus = Property(str, _get_rag_status, notify=ragStatusChanged)
    currentNavigation = Property("QVariantMap", _get_current_navigation, notify=currentNavigationChanged)
    citations = Property("QVariantList", _get_citations, notify=citationsChanged)


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
