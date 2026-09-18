"""Chatbot audio worker for the native kiosk UI."""

from __future__ import annotations

import asyncio
import base64
import collections
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

try:
    from scipy.signal import butter, sosfilt, sosfilt_zi
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

from access_control.audio_io.audio_player import AudioPlayer
from access_control.audio_io.config import AudioIOConfig

from .api_client import KioskApiClient

try:
    from access_control.timing_logger import edge_timing
except ImportError:
    from timing_logger import edge_timing


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
DEFAULT_OUTPUT_GAIN = float(os.getenv("EDGE_LIVE_OUTPUT_GAIN", "0.65"))
DEFAULT_MIC_GAIN = float(os.getenv("EDGE_LIVE_MIC_GAIN", "0.80"))
DEFAULT_BARGE_IN_THRESHOLD = float(os.getenv("EDGE_LIVE_BARGE_IN_THRESHOLD", "350.0"))
DEFAULT_COOLING_OFF_MS = float(os.getenv("EDGE_LIVE_COOLING_OFF_MS", "100.0"))
DEFAULT_SILENCE_HOLD_SEC = float(os.getenv("EDGE_LIVE_SILENCE_HOLD_SEC", "0.45"))
DEFAULT_BARGE_RATIO = float(os.getenv("EDGE_LIVE_BARGE_RATIO", "0.60"))
DEFAULT_PRE_ROLL_CHUNKS = int(os.getenv("EDGE_LIVE_PRE_ROLL_CHUNKS", "3"))


def _filter_and_calculate_rms(
    pcm_bytes: bytes,
    sos: np.ndarray | None = None,
    zi: np.ndarray | None = None,
) -> tuple[float, np.ndarray | None]:
    """Apply 2nd-order Butterworth high-pass filter (150Hz) and calculate RMS."""
    if not pcm_bytes:
        return 0.0, zi
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0, zi
    if _SCIPY_AVAILABLE and sos is not None and zi is not None:
        try:
            filtered, zi_new = sosfilt(sos, samples, zi=zi)
            rms = float(np.sqrt(np.mean(filtered * filtered)))
            return rms, zi_new
        except Exception:
            pass
    rms = float(np.sqrt(np.mean(samples * samples)))
    return rms, zi


class _LiveDuplexWorker(QThread):
    """Continuous bi-directional streaming worker for Gemini Live duplex WebSocket."""

    listeningChanged = Signal(bool)
    busyChanged = Signal(bool)
    speechStateChanged = Signal(bool)
    userAudioLevelChanged = Signal(float)
    assistantAudioLevelChanged = Signal(float)
    userTranscriptReceived = Signal(str)
    textChunkReceived = Signal(str)
    ragStatusChanged = Signal(str, str)
    navigationReceived = Signal(dict)
    citationsReceived = Signal(list)
    turnCompleted = Signal()
    responseReceived = Signal(dict)
    errorOccurred = Signal(str)

    def __init__(
        self,
        api: KioskApiClient,
        speech_threshold: float = SPEECH_THRESHOLD_RMS,
        output_gain: float = DEFAULT_OUTPUT_GAIN,
        mic_gain: float = DEFAULT_MIC_GAIN,
        barge_threshold: float = DEFAULT_BARGE_IN_THRESHOLD,
        barge_ratio: float = DEFAULT_BARGE_RATIO,
        cooling_off_ms: float = DEFAULT_COOLING_OFF_MS,
        silence_hold_sec: float = DEFAULT_SILENCE_HOLD_SEC,
        pre_roll_chunks: int = DEFAULT_PRE_ROLL_CHUNKS,
    ) -> None:
        super().__init__()
        self._api = api
        self._speech_threshold = speech_threshold
        self._output_gain = output_gain
        self._mic_gain = mic_gain
        self._barge_threshold = barge_threshold
        self._barge_ratio = barge_ratio
        self._cooling_off_ms = cooling_off_ms
        self._silence_hold_sec = silence_hold_sec
        self._pre_roll_chunks = pre_roll_chunks
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
            self.userAudioLevelChanged.emit(0.0)
            self.assistantAudioLevelChanged.emit(0.0)

    async def _duplex_session(self, ws_url: str) -> None:
        logger.info("Connecting to Gemini Live duplex at %s", ws_url)
        loop = asyncio.get_running_loop()
        self._loop = loop
        mic_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._audio_play_queue = asyncio.Queue()

        playback_busy_until = 0.0
        last_speaker_rms = 0.0
        last_user_query = [""]
        last_assistant_text = [""]
        last_citations: list[list[Any]] = [[]]
        session_ready = [False]

        turn_id = [""]
        turn_speech_onset_mono = [0.0]
        turn_speech_end_mono = [0.0]
        turn_audio_bytes_sent = [0]
        first_audio_chunk_received = [False]
        first_audio_playback_started = [False]

        def mic_callback(indata: bytes, frames: int, time_info: Any, status: Any) -> None:
            if self._stop_requested.is_set():
                return
            pcm_bytes = bytes(indata)
            if abs(self._mic_gain - 1.0) > 1e-3:
                samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
                pcm_bytes = (samples * self._mic_gain).clip(-32768, 32767).astype(np.int16).tobytes()
            loop.call_soon_threadsafe(mic_queue.put_nowait, pcm_bytes)

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
                    nonlocal playback_busy_until, last_speaker_rms
                    with output_stream:
                        while not self._stop_requested.is_set():
                            if self._audio_play_queue is None:
                                break
                            try:
                                pcm_bytes = await asyncio.wait_for(self._audio_play_queue.get(), timeout=0.1)
                            except asyncio.TimeoutError:
                                if time.monotonic() >= playback_busy_until:
                                    self.busyChanged.emit(False)
                                    self.assistantAudioLevelChanged.emit(0.0)
                                    last_speaker_rms = 0.0
                                continue

                            if pcm_bytes is None or self._stop_requested.is_set():
                                break

                            self.busyChanged.emit(True)
                            if not first_audio_playback_started[0]:
                                first_audio_playback_started[0] = True
                                time_since_speech_end = (
                                    (time.monotonic() - turn_speech_end_mono[0]) * 1000.0
                                    if turn_speech_end_mono[0] > 0
                                    else None
                                )
                                edge_timing.log_internal(
                                    "AUDIO_PLAYBACK_START",
                                    turn_id=turn_id[0],
                                    time_since_speech_end_ms=time_since_speech_end,
                                    pcm_bytes=len(pcm_bytes),
                                )
                            if abs(self._output_gain - 1.0) > 1e-3:
                                samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
                                pcm_bytes = (samples * self._output_gain).clip(-32768, 32767).astype(np.int16).tobytes()

                            # Compute outgoing speaker RMS for dynamic echo cancellation / barge threshold
                            spk_samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
                            spk_rms = float(np.sqrt(np.mean(spk_samples * spk_samples))) if spk_samples.size > 0 else 0.0
                            last_speaker_rms = spk_rms
                            self.assistantAudioLevelChanged.emit(min(1.0, max(0.0, spk_rms / 2500.0)))

                            duration = len(pcm_bytes) / 48000.0
                            hangover_sec = self._cooling_off_ms / 1000.0
                            playback_busy_until = max(playback_busy_until, time.monotonic()) + duration + hangover_sec
                            try:
                                await loop.run_in_executor(None, output_stream.write, pcm_bytes)
                            except Exception as exc:
                                logger.warning("Audio playback chunk write error: %s", exc)

                async def receiver_loop() -> None:
                    nonlocal playback_busy_until, last_speaker_rms
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
                            msg_turn_id = data.get("turn_id") or msg.get("turn_id") or turn_id[0]
                            server_sent_at = data.get("server_sent_at") or msg.get("server_sent_at")
                            time_since_speech_end = (
                                (time.monotonic() - turn_speech_end_mono[0]) * 1000.0
                                if turn_speech_end_mono[0] > 0
                                else None
                            )

                            if event in ("session_ready", "ready"):
                                session_ready[0] = True
                                self.listeningChanged.emit(True)
                                edge_timing.log_receive("WS_READY", turn_id=msg_turn_id, server_sent_at=server_sent_at)
                            elif event in ("user_transcript", "transcript"):
                                text = data.get("text", "")
                                if text:
                                    last_user_query[0] = text
                                    last_assistant_text[0] = ""
                                    self.userTranscriptReceived.emit(text)
                                    edge_timing.log_receive(
                                        "TRANSCRIPT",
                                        turn_id=msg_turn_id,
                                        server_sent_at=server_sent_at,
                                        time_since_speech_end_ms=time_since_speech_end,
                                        text=text[:60],
                                    )
                            elif event == "rag_status":
                                last_assistant_text[0] = ""
                                st = data.get("status", "")
                                q = data.get("query", "")
                                self.ragStatusChanged.emit(st, q)
                                edge_timing.log_receive(
                                    "RAG_STATUS",
                                    turn_id=msg_turn_id,
                                    server_sent_at=server_sent_at,
                                    time_since_speech_end_ms=time_since_speech_end,
                                    status=st,
                                )
                            elif event == "acoustic_bridge":
                                last_assistant_text[0] = ""
                                edge_timing.log_receive(
                                    "ACOUSTIC_BRIDGE",
                                    turn_id=msg_turn_id,
                                    server_sent_at=server_sent_at,
                                    time_since_speech_end_ms=time_since_speech_end,
                                )
                            elif event == "navigation":
                                self.navigationReceived.emit(data)
                                edge_timing.log_receive("NAVIGATION", turn_id=msg_turn_id, server_sent_at=server_sent_at)
                            elif event == "rag_complete":
                                cites = data.get("citations") or data.get("sources") or []
                                last_citations[0] = cites
                                self.citationsReceived.emit(cites)
                                edge_timing.log_receive(
                                    "RAG_COMPLETE",
                                    turn_id=msg_turn_id,
                                    server_sent_at=server_sent_at,
                                    time_since_speech_end_ms=time_since_speech_end,
                                    citations_count=len(cites),
                                )
                            elif event == "output_transcript":
                                tok = data.get("text", "")
                                if tok:
                                    last_assistant_text[0] += tok
                                    self.textChunkReceived.emit(tok)
                            elif event == "audio":
                                b64_chunk = data.get("chunk", "")
                                if b64_chunk:
                                    pcm = base64.b64decode(b64_chunk)
                                    if not first_audio_chunk_received[0]:
                                        first_audio_chunk_received[0] = True
                                        edge_timing.log_receive(
                                            "FIRST_AUDIO_CHUNK",
                                            turn_id=msg_turn_id,
                                            server_sent_at=server_sent_at,
                                            time_since_speech_end_ms=time_since_speech_end,
                                            chunk_bytes=len(pcm),
                                        )
                                    if self._audio_play_queue:
                                        await self._audio_play_queue.put(pcm)
                            elif event == "turn_complete":
                                total_round_trip = (
                                    (time.monotonic() - turn_speech_end_mono[0]) * 1000.0
                                    if turn_speech_end_mono[0] > 0
                                    else None
                                )
                                edge_timing.log_receive(
                                    "TURN_COMPLETE",
                                    turn_id=msg_turn_id,
                                    server_sent_at=server_sent_at,
                                    duration_ms=total_round_trip,
                                    time_since_speech_end_ms=total_round_trip,
                                )
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
                                edge_timing.log_receive("INTERRUPTED", turn_id=msg_turn_id)
                                playback_busy_until = 0.0
                                last_speaker_rms = 0.0
                                if self._audio_play_queue:
                                    while not self._audio_play_queue.empty():
                                        try:
                                            self._audio_play_queue.get_nowait()
                                        except Exception:
                                            break
                                self.busyChanged.emit(False)
                                self.assistantAudioLevelChanged.emit(0.0)
                            elif event == "error":
                                err_msg = str(data.get("message") or "Unknown error")
                                edge_timing.log_receive("ERROR", turn_id=msg_turn_id, error=err_msg)
                                self.errorOccurred.emit(err_msg)
                    except websockets.ConnectionClosed:
                        pass
                    except asyncio.CancelledError:
                        pass

                async def sender_loop() -> None:
                    nonlocal playback_busy_until, last_speaker_rms
                    is_speaking = False
                    silence_started = 0.0
                    consecutive_barge_count = 0

                    sos = None
                    zi = None
                    if _SCIPY_AVAILABLE:
                        try:
                            sos = butter(2, 150.0, btype="highpass", fs=16000, output="sos")
                            zi = sosfilt_zi(sos)
                        except Exception as exc:
                            logger.warning("Could not initialize high-pass filter: %s", exc)
                            sos = None
                            zi = None

                    with mic_stream:
                        while not self._stop_requested.is_set():
                            pcm_chunk = await mic_queue.get()
                            if pcm_chunk is None or self._stop_requested.is_set():
                                break

                            if not session_ready[0]:
                                # Drop microphone chunks until backend emits ready event
                                continue

                            # High-pass filter (150 Hz) and calculate RMS
                            rms, zi = _filter_and_calculate_rms(pcm_chunk, sos, zi)
                            now = time.monotonic()
                            is_playing = (now < playback_busy_until) or (
                                self._audio_play_queue is not None and not self._audio_play_queue.empty()
                            )
                            if not is_playing:
                                self.userAudioLevelChanged.emit(min(1.0, max(0.0, rms / 1500.0)))
                            else:
                                self.userAudioLevelChanged.emit(0.0)

                            # Echo suppression & dynamic adaptive barge-in
                            if is_playing:
                                dynamic_barge_thresh = max(
                                    self._barge_threshold,
                                    self._barge_ratio * last_speaker_rms + 100.0,
                                )
                                if rms >= dynamic_barge_thresh:
                                    consecutive_barge_count = 0
                                    playback_busy_until = 0.0
                                    last_speaker_rms = 0.0
                                    last_assistant_text[0] = ""
                                    if self._audio_play_queue:
                                        while not self._audio_play_queue.empty():
                                            try:
                                                self._audio_play_queue.get_nowait()
                                            except Exception:
                                                break
                                    self.busyChanged.emit(False)
                                    self.assistantAudioLevelChanged.emit(0.0)
                                    edge_timing.log_send("CLIENT_BARGE_IN", turn_id=turn_id[0], rms=round(rms, 1))
                                    try:
                                        await ws.send(json.dumps({"event": "client_barge_in"}))
                                    except Exception:
                                        pass
                                    if not is_speaking:
                                        is_speaking = True
                                        self.speechStateChanged.emit(True)
                                    silence_started = 0.0
                                    try:
                                        turn_audio_bytes_sent[0] += len(pcm_chunk)
                                        await ws.send(pcm_chunk)
                                    except Exception:
                                        break
                                else:
                                    # Drop speaker echo locally: never send to Gemini Live
                                    continue
                            else:
                                consecutive_barge_count = 0
                                # Continuous streaming: send microphone audio continuously while assistant is not playing.
                                # This ensures Gemini Live's ASR pipeline receives unbroken audio frames (mirroring
                                # test_chatbot_rbac.py) and completely eliminates the ~17.5s inactivity timeout freeze.
                                try:
                                    turn_audio_bytes_sent[0] += len(pcm_chunk)
                                    await ws.send(pcm_chunk)
                                except Exception:
                                    break

                                # Client VAD turn-end detection for instant response
                                if rms >= self._speech_threshold:
                                    if not is_speaking:
                                        is_speaking = True
                                        turn_speech_onset_mono[0] = time.monotonic()
                                        turn_id[0] = f"turn_{int(time.time() * 1000)}"
                                        turn_audio_bytes_sent[0] = len(pcm_chunk)
                                        first_audio_chunk_received[0] = False
                                        first_audio_playback_started[0] = False
                                        edge_timing.log_internal(
                                            "SPEECH_ONSET",
                                            turn_id=turn_id[0],
                                            rms=round(rms, 1),
                                            threshold=self._speech_threshold,
                                        )
                                        last_assistant_text[0] = ""
                                        self.speechStateChanged.emit(True)
                                    silence_started = 0.0
                                elif is_speaking:
                                    if silence_started == 0.0:
                                        silence_started = now
                                    elif (now - silence_started) >= self._silence_hold_sec:
                                        is_speaking = False
                                        silence_started = 0.0
                                        turn_speech_end_mono[0] = time.monotonic()
                                        speech_duration_ms = (turn_speech_end_mono[0] - turn_speech_onset_mono[0]) * 1000.0
                                        client_sent_at = edge_timing.log_send(
                                            "ACTIVITY_END",
                                            turn_id=turn_id[0],
                                            duration_ms=speech_duration_ms,
                                            audio_bytes=turn_audio_bytes_sent[0],
                                        )
                                        self.speechStateChanged.emit(False)
                                        self.userAudioLevelChanged.emit(0.0)
                                        try:
                                            await ws.send(json.dumps({
                                                "event": "activity_end",
                                                "data": {
                                                    "turn_id": turn_id[0],
                                                    "client_sent_at": client_sent_at,
                                                    "speech_duration_ms": round(speech_duration_ms, 2),
                                                    "total_audio_bytes": turn_audio_bytes_sent[0],
                                                },
                                            }))
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

    def send_greeting(self, user_name: str | None = None) -> None:
        if self._ws and self._loop:
            try:
                payload = json.dumps({"event": "greet", "data": {"user_name": user_name}})
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._ws.send(payload))
                )
            except Exception as exc:
                logger.debug("Failed to send greet event over WebSocket: %s", exc)


class ChatbotController(QObject):
    listeningChanged = Signal()
    busyChanged = Signal()
    speechStateChanged = Signal()
    userAudioLevelChanged = Signal()
    assistantAudioLevelChanged = Signal()
    errorChanged = Signal()
    mutedChanged = Signal()
    partialTextChanged = Signal()
    transcribedTextChanged = Signal()
    ragStatusChanged = Signal()
    currentNavigationChanged = Signal()
    citationsChanged = Signal()
    outputGainChanged = Signal()
    micGainChanged = Signal()
    bargeThresholdChanged = Signal()
    speechThresholdChanged = Signal()
    coolingOffMsChanged = Signal()
    silenceHoldSecChanged = Signal()
    bargeRatioChanged = Signal()
    responseReceived = Signal(dict)

    def __init__(self, api: KioskApiClient) -> None:
        super().__init__()
        self._api = api
        self._worker: _LiveDuplexWorker | None = None
        self._listening = False
        self._busy = False
        self._speaking = False
        self._user_audio_level = 0.0
        self._assistant_audio_level = 0.0
        self._error = ""
        self._muted = False
        self._partial_text = ""
        self._transcribed_text = ""
        self._rag_status = ""
        self._current_navigation: dict[str, Any] = {}
        self._citations: list[Any] = []
        self._output_gain = DEFAULT_OUTPUT_GAIN
        self._mic_gain = DEFAULT_MIC_GAIN
        self._barge_threshold = DEFAULT_BARGE_IN_THRESHOLD
        self._speech_threshold = SPEECH_THRESHOLD_RMS
        self._cooling_off_ms = DEFAULT_COOLING_OFF_MS
        self._silence_hold_sec = DEFAULT_SILENCE_HOLD_SEC
        self._barge_ratio = DEFAULT_BARGE_RATIO

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

        worker = _LiveDuplexWorker(
            self._api,
            speech_threshold=self._speech_threshold,
            output_gain=self._output_gain,
            mic_gain=self._mic_gain,
            barge_threshold=self._barge_threshold,
            barge_ratio=self._barge_ratio,
            cooling_off_ms=self._cooling_off_ms,
            silence_hold_sec=self._silence_hold_sec,
        )
        worker.listeningChanged.connect(self._set_listening)
        worker.busyChanged.connect(self._set_busy)
        worker.speechStateChanged.connect(self._set_speaking)
        worker.userAudioLevelChanged.connect(self._set_user_audio_level)
        worker.assistantAudioLevelChanged.connect(self._set_assistant_audio_level)
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
    def clearNavigation(self) -> None:
        """Clear current navigation directions."""
        self._current_navigation = {}
        self.currentNavigationChanged.emit()

    @Slot()
    def resetSessionState(self) -> None:
        """Reset all ephemeral session state (navigation, citations, transcripts)."""
        self._current_navigation = {}
        self._citations = []
        self._partial_text = ""
        self._transcribed_text = ""
        self._rag_status = ""
        self.currentNavigationChanged.emit()
        self.citationsChanged.emit()
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()
        self.ragStatusChanged.emit()

    @Slot()
    def stopVoiceLoop(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker.wait(1000)
            self._worker = None
        self._set_listening(False)
        self._set_busy(False)
        self._set_speaking(False)
        self._set_user_audio_level(0.0)
        self._set_assistant_audio_level(0.0)
        self._partial_text = ""
        self._transcribed_text = ""
        self._rag_status = ""
        self._current_navigation = {}
        self._citations = []
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()
        self.busyChanged.emit()
        self.ragStatusChanged.emit()
        self.currentNavigationChanged.emit()
        self.citationsChanged.emit()

    @Slot()
    def stopAudioPlayback(self) -> None:
        if self._worker:
            self._worker.stop_audio_playback()

    @Slot()
    def interruptPlayback(self) -> None:
        """Explicitly interrupt current audio playback and signal barge-in."""
        self.stopAudioPlayback()

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
        self._partial_text = ""
        self._transcribed_text = text
        self._set_busy(True)
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()

    @Slot(str, str)
    def _on_rag_status(self, status: str, query: str) -> None:
        if status or query:
            self._partial_text = ""
            self.partialTextChanged.emit()
        self._rag_status = "Searching database..." if status or query else ""
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
        self._partial_text = ""
        self._transcribed_text = ""
        self.ragStatusChanged.emit()
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()

    @Slot(dict)
    def _on_worker_response(self, payload: dict) -> None:
        self._set_busy(self._speaking)
        self._partial_text = ""
        self._transcribed_text = ""
        self._rag_status = ""
        self.partialTextChanged.emit()
        self.transcribedTextChanged.emit()
        self.ragStatusChanged.emit()
        self.busyChanged.emit()
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

    @Slot(str)
    @Slot()
    def triggerLiveGreeting(self, user_name: str | None = None) -> None:
        """Trigger Gemini Live to speak the welcome greeting over the live duplex session."""
        if not self._worker or not self._worker.isRunning():
            self.startVoiceLoop()
        if self._worker:
            self._worker.send_greeting(user_name)

    @Slot()
    def playGreeting(self) -> None:
        """Deprecated alias; triggers Gemini Live spoken greeting."""
        self.triggerLiveGreeting()

    def shutdown(self) -> None:
        self.stopVoiceLoop()

    def _cleanup_worker(self, worker: _LiveDuplexWorker) -> None:
        if self._worker is worker:
            self._worker = None
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

    @Slot(float)
    def _set_user_audio_level(self, value: float) -> None:
        val = max(0.0, min(1.0, float(value)))
        if abs(val - self._user_audio_level) > 0.02:
            self._user_audio_level = val
            self.userAudioLevelChanged.emit()

    @Slot(float)
    def _set_assistant_audio_level(self, value: float) -> None:
        val = max(0.0, min(1.0, float(value)))
        if abs(val - self._assistant_audio_level) > 0.02:
            self._assistant_audio_level = val
            self.assistantAudioLevelChanged.emit()

    def _get_user_audio_level(self) -> float:
        return self._user_audio_level

    def _get_assistant_audio_level(self) -> float:
        return self._assistant_audio_level

    @Slot(str)
    def _set_error(self, message: str) -> None:
        self._error = message
        self.errorChanged.emit()

    def _get_listening(self) -> bool:
        return self._listening

    def _get_busy(self) -> bool:
        return self._busy or bool(self._transcribed_text)

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

    @Slot(float)
    def setOutputGain(self, gain: float) -> None:
        val = max(0.1, min(1.0, float(gain)))
        if abs(val - self._output_gain) > 1e-4:
            self._output_gain = val
            if self._worker:
                self._worker._output_gain = val
            self.outputGainChanged.emit()

    @Slot(float)
    def setMicGain(self, gain: float) -> None:
        val = max(0.1, min(2.0, float(gain)))
        if abs(val - self._mic_gain) > 1e-4:
            self._mic_gain = val
            if self._worker:
                self._worker._mic_gain = val
            self.micGainChanged.emit()

    @Slot(float)
    def setBargeThreshold(self, threshold: float) -> None:
        val = max(300.0, float(threshold))
        if abs(val - self._barge_threshold) > 1e-4:
            self._barge_threshold = val
            if self._worker:
                self._worker._barge_threshold = val
            self.bargeThresholdChanged.emit()

    @Slot(float)
    def setSpeechThreshold(self, threshold: float) -> None:
        val = max(50.0, float(threshold))
        if abs(val - self._speech_threshold) > 1e-4:
            self._speech_threshold = val
            if self._worker:
                self._worker._speech_threshold = val
            self.speechThresholdChanged.emit()

    @Slot(float)
    def setCoolingOffMs(self, ms: float) -> None:
        val = max(50.0, float(ms))
        if abs(val - self._cooling_off_ms) > 1e-4:
            self._cooling_off_ms = val
            if self._worker:
                self._worker._cooling_off_ms = val
            self.coolingOffMsChanged.emit()

    @Slot(float)
    def setSilenceHoldSec(self, sec: float) -> None:
        val = max(0.1, float(sec))
        if abs(val - self._silence_hold_sec) > 1e-4:
            self._silence_hold_sec = val
            if self._worker:
                self._worker._silence_hold_sec = val
            self.silenceHoldSecChanged.emit()

    @Slot(float)
    def setBargeRatio(self, ratio: float) -> None:
        val = max(1.0, float(ratio))
        if abs(val - self._barge_ratio) > 1e-4:
            self._barge_ratio = val
            if self._worker:
                self._worker._barge_ratio = val
            self.bargeRatioChanged.emit()

    def _get_output_gain(self) -> float:
        return self._output_gain

    def _get_mic_gain(self) -> float:
        return self._mic_gain

    def _get_barge_threshold(self) -> float:
        return self._barge_threshold

    def _get_speech_threshold(self) -> float:
        return self._speech_threshold

    def _get_cooling_off_ms(self) -> float:
        return self._cooling_off_ms

    def _get_silence_hold_sec(self) -> float:
        return self._silence_hold_sec

    def _get_barge_ratio(self) -> float:
        return self._barge_ratio

    listening = Property(bool, _get_listening, notify=listeningChanged)
    busy = Property(bool, _get_busy, notify=busyChanged)
    speaking = Property(bool, _get_speaking, notify=speechStateChanged)
    userAudioLevel = Property(float, _get_user_audio_level, notify=userAudioLevelChanged)
    assistantAudioLevel = Property(float, _get_assistant_audio_level, notify=assistantAudioLevelChanged)
    error = Property(str, _get_error, notify=errorChanged)
    muted = Property(bool, _get_muted, notify=mutedChanged)
    partialText = Property(str, _get_partial_text, notify=partialTextChanged)
    transcribedText = Property(str, _get_transcribed_text, notify=transcribedTextChanged)
    ragStatus = Property(str, _get_rag_status, notify=ragStatusChanged)
    currentNavigation = Property("QVariantMap", _get_current_navigation, notify=currentNavigationChanged)
    citations = Property("QVariantList", _get_citations, notify=citationsChanged)
    outputGain = Property(float, _get_output_gain, setOutputGain, notify=outputGainChanged)
    micGain = Property(float, _get_mic_gain, setMicGain, notify=micGainChanged)
    bargeThreshold = Property(float, _get_barge_threshold, setBargeThreshold, notify=bargeThresholdChanged)
    speechThreshold = Property(float, _get_speech_threshold, setSpeechThreshold, notify=speechThresholdChanged)
    coolingOffMs = Property(float, _get_cooling_off_ms, setCoolingOffMs, notify=coolingOffMsChanged)
    silenceHoldSec = Property(float, _get_silence_hold_sec, setSilenceHoldSec, notify=silenceHoldSecChanged)
    bargeRatio = Property(float, _get_barge_ratio, setBargeRatio, notify=bargeRatioChanged)


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
