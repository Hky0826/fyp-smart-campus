"""
Smart Campus Cloud Backend Live Voice Assistant Client.

Connects directly to the running FastAPI Cloud Backend via WebSocket:
    ws://127.0.0.1:8000/api/chatbot/live/ws  (fallback: 8080)

Architecture:
- Mirrors shitz/test_live.py continuous full-duplex hands-free streaming.
- Streams microphone audio (16kHz PCM) continuously into the Cloud Backend.
- Gemini Live's native neural server VAD handles turn detection automatically without artificial timeouts.
- Real-time display of Campus Navigation wayfinding and RAG source citations.
- Built-in speaker echo suppression.
"""

from __future__ import annotations

import asyncio
import base64
import collections
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import websockets

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("cloud_live_client")

RATE = 16000
CHUNK = 1600  # 100ms blocks
PLAYBACK_RATE = 24000


def calculate_rms(pcm_bytes: bytes) -> float:
    if not pcm_bytes:
        return 0.0
    arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr ** 2)))


async def find_backend_url() -> str:
    """Detect whether backend is listening on 8000 or 8080."""
    candidates = [
        "ws://127.0.0.1:8000/api/chatbot/live/ws?device_id=ENTRY-A8F3D155",
        "ws://127.0.0.1:8080/api/chatbot/live/ws?device_id=ENTRY-A8F3D155",
        "ws://localhost:8000/api/chatbot/live/ws?device_id=ENTRY-A8F3D155",
        "ws://localhost:8080/api/chatbot/live/ws?device_id=ENTRY-A8F3D155",
    ]
    for url in candidates:
        try:
            ws = await asyncio.wait_for(websockets.connect(url), timeout=1.0)
            await ws.close()
            return url
        except Exception:
            continue
    return candidates[0]


async def run_client():
    print("=" * 65)
    print("Smart Campus Cloud Voice Client (WebSocket Full-Duplex)")
    print("=" * 65)

    ws_url = await find_backend_url()
    print(f"[1/3] Connecting to Cloud Backend at {ws_url}...")

    try:
        ws = await websockets.connect(ws_url)
    except Exception as exc:
        print(f"\n[Error] Could not connect to backend at {ws_url}: {exc}")
        print("Please make sure your Cloud Backend is running (e.g. uvicorn on port 8000 or 8080).")
        return

    # 1. Await ready handshake from Cloud Backend
    try:
        ready_msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
        ready_data = json.loads(ready_msg)
        if ready_data.get("event") == "ready":
            model = ready_data.get("data", {}).get("model", "gemini-live")
            print(f"[1/3] Connected to Cloud Backend! Model: {model}")
        else:
            print(f"[1/3] Connected! Initial message: {ready_msg}")
    except Exception as exc:
        print(f"[Warning] Handshake timed out or failed: {exc}")

    # 2. Setup Audio Output Stream (Speaker 24kHz)
    output_stream = sd.RawOutputStream(
        samplerate=PLAYBACK_RATE,
        channels=1,
        dtype="int16",
        blocksize=2400,
    )
    output_stream.start()
    audio_play_queue: asyncio.Queue[bytes] = asyncio.Queue()
    playback_busy_until = 0.0

    # 3. Setup Audio Input Stream (Microphone 16kHz)
    mic_queue: asyncio.Queue[bytes] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def mic_callback(indata, frames, time_info, status):
        pcm = indata.tobytes()
        loop.call_soon_threadsafe(mic_queue.put_nowait, pcm)

    mic_stream = sd.InputStream(
        samplerate=RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK,
        callback=mic_callback,
    )
    mic_stream.start()

    # Load auto-tuned VAD threshold from vad_config.json if present
    vad_config_file = Path(__file__).resolve().parent / "vad_config.json"
    speech_threshold_rms = 300.0
    if vad_config_file.exists():
        try:
            with open(vad_config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                speech_threshold_rms = float(cfg.get("speech_threshold_rms", 300.0))
        except Exception:
            pass

    print(f"[2/3] Audio streams ready. Voice activation threshold: RMS > {speech_threshold_rms:.1f}")
    print("[3/3] Continuous Hands-Free Assistant Active on Cloud Backend!")
    print("\nSpeak naturally! Try asking:")
    print("  - \"What courses are offered in QIU?\"")
    print("  - \"Where is the reception?\"")
    print("  - \"How do I get to the admissions and records department?\"\n")

    # Background audio playback loop
    async def player_loop():
        nonlocal playback_busy_until
        while True:
            chunk = await audio_play_queue.get()
            if chunk:
                # 24000 samples/sec, 16-bit mono = 48000 bytes/sec
                duration = len(chunk) / 48000.0
                playback_busy_until = time.monotonic() + duration + 0.1
                try:
                    await asyncio.to_thread(output_stream.write, chunk)
                except Exception:
                    pass

    # Background receiver loop from Cloud Backend
    async def receiver_loop():
        nonlocal playback_busy_until
        try:
            async for raw_msg in ws:
                try:
                    event_data = json.loads(raw_msg)
                except Exception:
                    continue

                event = event_data.get("event")
                data = event_data.get("data") or {}

                if event == "transcript":
                    user_text = data.get("text", "")
                    if user_text:
                        print(f"\n[You]: {user_text}")

                elif event == "rag_status":
                    status_text = data.get("status", "")
                    query = data.get("query", "")
                    print(f"\n[Cloud Backend]: Searching database for: \"{query}\"")

                elif event == "navigation":
                    print("\n" + "=" * 55)
                    print("  CAMPUS MAP NAVIGATION PAYLOAD RECEIVED")
                    target = data.get("navigation_target") or {}
                    print(f"  Destination: {target.get('label', 'Unknown')}")
                    print(f"  Building:    {target.get('building', 'Campus Main')}")
                    print(f"  Floor:       Level {target.get('floor', '1')}")
                    print(f"  Node ID:     {target.get('node_id', 'N/A')}")
                    if data.get("instructions"):
                        print("  Directions:")
                        for step in data.get("instructions", []):
                            print(f"    - {step.get('instruction')}")
                    print("=" * 55 + "\n")

                elif event == "rag_complete":
                    route = data.get("route", "")
                    citations = data.get("citations") or data.get("sources") or []
                    if citations:
                        print(f"\n[RAG Sources]: {len(citations)} chunks retrieved from database.")
                        for idx, c in enumerate(citations[:3], 1):
                            if isinstance(c, dict):
                                title = c.get("document_title") or f"Document #{c.get('document_id', 'N/A')}"
                            else:
                                title = str(c)
                            print(f"    [{idx}] {title}")

                elif event == "output_transcript":
                    text = data.get("text", "")
                    if text:
                        print(f"[Assistant]: {text}", end="", flush=True)

                elif event == "audio":
                    b64_chunk = data.get("chunk", "")
                    if b64_chunk:
                        pcm_bytes = base64.b64decode(b64_chunk)
                        await audio_play_queue.put(pcm_bytes)

                elif event == "turn_complete":
                    print("\n[Response finished - Ready for next question!]\n")
                    # Clear any remaining playback lock to allow next turn immediately
                    if audio_play_queue.empty():
                        playback_busy_until = 0.0

                elif event == "error":
                    print(f"\n[Backend Error]: {data.get('message', 'Unknown error')}")

        except websockets.ConnectionClosed:
            print("\n[Connection Closed] Backend disconnected.")
        except asyncio.CancelledError:
            pass

    # Continuous microphone sender loop with pre-roll VAD gating
    async def sender_loop():
        nonlocal playback_busy_until
        speech_active = False
        silence_started = 0.0
        pre_roll_buffer: collections.deque[bytes] = collections.deque(maxlen=3)

        while True:
            pcm_chunk = await mic_queue.get()
            if not pcm_chunk:
                continue

            rms = calculate_rms(pcm_chunk)
            now = time.monotonic()
            is_playing = (now < playback_busy_until) or (not audio_play_queue.empty())

            # Echo suppression: do not send audio while assistant is speaking
            if is_playing:
                # Barge-in if speaking loudly over assistant
                if rms >= speech_threshold_rms * 2.0:
                    playback_busy_until = 0.0
                    while not audio_play_queue.empty():
                        try:
                            audio_play_queue.get_nowait()
                        except Exception:
                            break
                    print("\n[Interrupted - Listening to you...]")
                    speech_active = True
                    silence_started = 0.0
                    while pre_roll_buffer:
                        try:
                            await ws.send(pre_roll_buffer.popleft())
                        except Exception:
                            break
                    try:
                        await ws.send(pcm_chunk)
                    except Exception:
                        break
                else:
                    continue
            else:
                # Client VAD audio gating with pre-roll lookback: suppress silence & hiss
                if not speech_active:
                    if rms >= speech_threshold_rms:
                        speech_active = True
                        silence_started = 0.0
                        sys.stdout.write("\n[You]: Speaking... ")
                        sys.stdout.flush()
                        while pre_roll_buffer:
                            try:
                                await ws.send(pre_roll_buffer.popleft())
                            except Exception:
                                break
                        try:
                            await ws.send(pcm_chunk)
                        except Exception:
                            break
                    else:
                        pre_roll_buffer.append(pcm_chunk)
                else:
                    try:
                        await ws.send(pcm_chunk)
                    except Exception:
                        break

                    if rms >= speech_threshold_rms:
                        silence_started = 0.0
                    else:
                        if silence_started == 0.0:
                            silence_started = now
                        elif (now - silence_started) >= 0.45:  # 450ms pause finishes turn
                            speech_active = False
                            silence_started = 0.0
                            print("\n[Speech paused - Waiting for response...]")
                            try:
                                await ws.send(json.dumps({"event": "activity_end"}))
                            except Exception:
                                pass

    tasks = [
        asyncio.create_task(player_loop()),
        asyncio.create_task(receiver_loop()),
        asyncio.create_task(sender_loop()),
    ]

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nExiting client...")
    finally:
        for t in tasks:
            t.cancel()
        await ws.close()
        mic_stream.stop()
        mic_stream.close()
        output_stream.stop()
        output_stream.close()
        print("Client disconnected gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        print("\nExited.")
