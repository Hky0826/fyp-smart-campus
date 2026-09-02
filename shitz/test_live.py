"""
100% Standalone Interactive Voice Assistant for Gemini Live + RAG.
Features Continuous Multi-Turn Full-Duplex Voice Streaming with RAG Grounding & Duration-Based Echo Control.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sounddevice as sd
import numpy as np
from shitz.gemini_live_rag import GeminiLiveRAG


def calculate_rms(pcm_bytes: bytes) -> float:
    """Calculate RMS energy of raw 16-bit PCM bytes."""
    if not pcm_bytes:
        return 0.0
    arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr ** 2)))


async def main():
    print("=" * 65)
    print("Gemini Live + RAG: Multi-Turn Continuous Voice Assistant")
    print("Zero Cloud Backend / Zero DB Server Dependencies")
    print("=" * 65)

    agent = GeminiLiveRAG(
        model_name="gemini-3.1-flash-live-preview",
        voice_name="Kore",
    )

    try:
        await agent.connect()
    except Exception as exc:
        print(f"Failed to connect to Gemini Live: {exc}")
        return

    loop = asyncio.get_running_loop()

    # ── Continuous Audio Output (Speaker) ──────────────────────────────────────
    output_stream = sd.RawOutputStream(
        samplerate=24000,
        channels=1,
        dtype="int16",
        blocksize=2400,
    )
    output_stream.start()
    audio_queue = asyncio.Queue()

    # Playback timing for echo suppression
    playback_busy_until = 0.0
    turn_audio_bytes = 0

    def handle_audio(pcm_data: bytes):
        nonlocal turn_audio_bytes
        if pcm_data:
            turn_audio_bytes += len(pcm_data)
            loop.call_soon_threadsafe(audio_queue.put_nowait, pcm_data)
            
            kb = turn_audio_bytes / 1024.0
            sys.stdout.write(f"\r[Gemini Live Speaking]: 🔊 {kb:5.1f} KB audio received... ")
            sys.stdout.flush()

    def handle_transcript(text: str):
        if text:
            print(f"\n[Transcript]: {text}")

    def handle_tool(tool_name: str, query: str):
        print(f"\n[Tool Triggered]: {tool_name}(query='{query}')")

    def handle_turn_complete():
        nonlocal turn_audio_bytes
        kb = turn_audio_bytes / 1024.0
        print(f"\n✓ [Response Finished ({kb:.1f} KB) - Ready for your next question!]\n")
        turn_audio_bytes = 0

    def handle_interrupted():
        nonlocal playback_busy_until, turn_audio_bytes
        playback_busy_until = 0.0
        turn_audio_bytes = 0
        while not audio_queue.empty():
            try:
                audio_queue.get_nowait()
            except Exception:
                break
        print("\n[Interrupted - Listening to you...]")

    # Start background receiver task from Gemini Live
    receiver_task = asyncio.create_task(
        agent.receive_events(
            on_audio=handle_audio,
            on_transcript=handle_transcript,
            on_tool_call=handle_tool,
            on_interrupted=handle_interrupted,
            on_turn_complete=handle_turn_complete,
        )
    )

    # Background audio playback task
    async def player_loop():
        nonlocal playback_busy_until
        while True:
            chunk = await audio_queue.get()
            if chunk:
                # 24000 samples/sec, 16-bit mono = 48000 bytes/sec
                duration = len(chunk) / 48000.0
                playback_busy_until = time.monotonic() + duration + 0.1
                try:
                    await asyncio.to_thread(output_stream.write, chunk)
                except Exception:
                    pass

    player_task = asyncio.create_task(player_loop())

    # ── Continuous Audio Input with Google Native VAD ───────────────────────────
    mic_queue = asyncio.Queue()

    def mic_callback(indata, frames, time_info, status):
        pcm = indata.tobytes()
        loop.call_soon_threadsafe(mic_queue.put_nowait, pcm)

    mic_stream = sd.InputStream(
        samplerate=16000,
        channels=1,
        dtype="int16",
        blocksize=1600,  # 100ms frames
        callback=mic_callback,
    )
    mic_stream.start()

    # Load auto-tuned VAD parameters if calibrated
    config_path = SCRIPT_DIR / "vad_config.json"
    speech_threshold_rms = 300.0

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                speech_threshold_rms = float(cfg.get("speech_threshold_rms", 300.0))
                print(f"[Config Loaded] Auto-Tuned Threshold: RMS > {speech_threshold_rms:.1f} ({cfg.get('speech_threshold_db', -40):.1f} dBFS)")
        except Exception as e:
            print(f"[Config Warning] Could not load vad_config.json: {e}")
    else:
        print(f"[Config Default] Default Threshold: RMS > {speech_threshold_rms:.1f} (Run shitz/test_mic.py to auto-tune)")

    async def continuous_mic_sender():
        nonlocal playback_busy_until
        speech_active = False

        while True:
            pcm_chunk = await mic_queue.get()
            if not pcm_chunk:
                continue

            rms = calculate_rms(pcm_chunk)
            now = time.monotonic()
            is_playing = (now < playback_busy_until) or (not audio_queue.empty())

            # Prevent laptop speaker echo from looping into mic while assistant speaks
            if is_playing:
                # Barge-in if speaking loudly over assistant
                if rms >= speech_threshold_rms * 2.0:
                    handle_interrupted()
                else:
                    # Echo suppression - skip mic transmission during speaker playback
                    continue

            # Stream audio frames continuously into Gemini Live
            await agent.send_audio_chunk(pcm_chunk, sample_rate=16000)

            # Visual feedback on speech detection
            if rms >= speech_threshold_rms:
                if not speech_active:
                    speech_active = True
                    sys.stdout.write("\n[You]: Speaking... ")
                    sys.stdout.flush()
            elif speech_active:
                speech_active = False
                print("\n[Speech paused - Waiting for response...]")

    sender_task = asyncio.create_task(continuous_mic_sender())

    print("\n[Multi-Turn Continuous Live Session Active]")
    print("Speak naturally whenever you are ready! (Press Ctrl+C to exit)\n")

    try:
        while True:
            await asyncio.sleep(1.0)
    except KeyboardInterrupt:
        print("\nExiting session...")
    finally:
        sender_task.cancel()
        receiver_task.cancel()
        player_task.cancel()
        try:
            mic_stream.stop()
            mic_stream.close()
        except Exception:
            pass
        try:
            output_stream.stop()
            output_stream.close()
        except Exception:
            pass
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
