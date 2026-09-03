"""
100% Standalone Gemini Live + RAG Agent for shitz folder.
No cloud backend, no database server, no FastAPI server required.
Connects directly to Google GenAI Live WebSocket API and performs in-memory RAG.
Supports continuous hands-free voice streaming with automatic speech detection (VAD).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger("shitz.live_rag")

# Load environment variables from cloud backend .env
try:
    from dotenv import load_dotenv
    root_dir = Path(__file__).resolve().parent.parent
    candidate_env_paths = [
        root_dir / "cloud" / "dashboard" / "backend" / ".env",
        root_dir / ".env.cloud",
        root_dir / "cloud" / ".env",
        root_dir / ".env",
    ]
    for env_path in candidate_env_paths:
        if env_path.is_file():
            load_dotenv(dotenv_path=env_path, override=False)
            logger.info("Loaded environment from %s", env_path)
except ImportError:
    pass

from google import genai
from google.genai import types
from shitz.flash_lite_rag import standalone_flash_lite, FlashLiteRAG

_SYSTEM_INSTRUCTION = """
You are the voice interface for Quest International University (QIU) Smart Campus.

Core Rules:
1. Transcribe microphone input and, for any question regarding university matters, programmes, faculties, admissions, fees, locations, rules, facilities, or policies, ALWAYS call the backend function process_campus_request with the user's inquiry.
2. Never answer a university question from your own pre-trained knowledge. Do not emit answer audio before the backend function response.
3. The backend function response is authoritative and grounded by Gemini 3.1 Flash Lite. Present the `answer` in that response naturally in spoken voice. Do not alter factual dates, names, fees, or policy decisions.
4. Speak concisely, clearly, and warmly in a natural voice.
""".strip()

_RAG_TOOL_DECLARATION = {
    "function_declarations": [
        {
            "name": "process_campus_request",
            "description": "Grounds and synthesizes official QIU campus information, programmes, tuition fees, faculty contacts, locations, and guidelines via Gemini 3.1 Flash Lite.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "The user's question or search query about the campus.",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "search_campus_knowledge",
            "description": "Searches official campus documents, courses, tuition fees, faculty contacts, locations, and guidelines.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "The search keywords or question to look up in campus records.",
                    },
                },
                "required": ["query"],
            },
        }
    ]
}


class GeminiLiveRAG:
    """Standalone full-duplex Gemini Live session with integrated RAG tool."""

    def __init__(
        self,
        model_name: str = "gemini-3.1-flash-live-preview",
        voice_name: str = "Kore",
        api_key: Optional[str] = None,
    ):
        self.model_name = model_name
        self.voice_name = voice_name
        self.api_key = (
            api_key
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY environment variable is required.")

        self.client = genai.Client(api_key=self.api_key)
        self.connection = None
        self.session = None
        self.is_connected = False
        self._send_lock = asyncio.Lock()

    async def connect(self):
        """Establish full-duplex WebSocket connection to Gemini Live with native VAD."""
        print(f"[Gemini Live] Connecting to {self.model_name} (Voice: {self.voice_name})...")
        config = {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": self.voice_name,
                    }
                }
            },
            "system_instruction": _SYSTEM_INSTRUCTION,
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "tools": [_RAG_TOOL_DECLARATION],
        }

        try:
            self.connection = self.client.aio.live.connect(
                model=self.model_name,
                config=config,
            )
            self.session = await self.connection.__aenter__()
            self.is_connected = True
            print("[Gemini Live] Connected successfully (Continuous Hands-Free Mode Active)!")
        except Exception as exc:
            self.is_connected = False
            print(f"[Gemini Live Error] Connection failed: {exc}")
            raise

    async def close(self):
        """Close the Gemini Live session."""
        if self.is_connected and self.connection:
            try:
                await self.connection.__aexit__(None, None, None)
            except Exception:
                pass
            self.is_connected = False
            print("[Gemini Live] Session closed.")

    async def send_audio_chunk(self, pcm_bytes: bytes, sample_rate: int = 16000):
        """Send continuous 16-bit PCM audio chunk to Gemini Live."""
        if not self.is_connected or not pcm_bytes:
            return
        async with self._send_lock:
            try:
                await self.session.send_realtime_input(
                    audio=types.Blob(
                        data=pcm_bytes,
                        mime_type=f"audio/pcm;rate={sample_rate}",
                    )
                )
            except Exception as exc:
                logger.debug("Failed to send audio chunk: %s", exc)

    async def end_user_turn(self):
        """Notify Gemini Live that the user's speech activity has finished."""
        if not self.is_connected:
            return
        async with self._send_lock:
            try:
                await self.session.send_realtime_input(activity_end=types.ActivityEnd())
            except Exception as exc:
                logger.debug("Failed to signal activity end: %s", exc)

    async def receive_events(
        self,
        on_audio: Callable[[bytes], None],
        on_transcript: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, str], None]] = None,
        on_interrupted: Optional[Callable[[], None]] = None,
        on_turn_complete: Optional[Callable[[], None]] = None,
    ):
        """
        Listen to live streaming events from Gemini Live.
        Executes RAG tool calls automatically and streams audio chunks to on_audio.
        """
        if not self.is_connected:
            return

        while self.is_connected:
            try:
                async for response in self.session.receive():
                    server_content = response.server_content
                    if server_content is not None:
                        # User interrupted assistant speaking
                        if server_content.interrupted and on_interrupted:
                            on_interrupted()

                        # 1. Real-time model turn (audio / text)
                        model_turn = server_content.model_turn
                        if model_turn is not None:
                            for part in model_turn.parts:
                                # Spoken Audio output
                                if part.inline_data and part.inline_data.data:
                                    audio_bytes = part.inline_data.data
                                    on_audio(audio_bytes)
                                # Spoken text transcript
                                if part.text and on_transcript:
                                    on_transcript(part.text)

                        # Check if turn is complete
                        if server_content.turn_complete and on_turn_complete:
                            on_turn_complete()

                    # 2. Tool Calls from Gemini Live
                    tool_call = response.tool_call
                    if tool_call is not None:
                        for call in tool_call.function_calls:
                            call_name = call.name
                            call_id = call.id
                            args = call.args or {}
                            query = args.get("query", "")

                            if on_tool_call:
                                on_tool_call(call_name, query)

                            print(f"\n[Tool Invocation] Gemini Live requested: {call_name}(query='{query}')")
                            flash_res = await standalone_flash_lite.process_query_async(query)
                            print(f"[Flash Lite RAG] Engine: {flash_res.source_engine} | Route: {flash_res.route} in {flash_res.latency_ms:.0f}ms (Sources: {flash_res.sources})")
                            print(f"[Flash Lite RAG Grounded Answer]:\n{flash_res.answer}\n")

                            # Send tool response back to Gemini Live
                            async with self._send_lock:
                                func_response = types.FunctionResponse(
                                    name=call_name,
                                    id=call_id,
                                    response={
                                        "answer": flash_res.answer,
                                        "sources": flash_res.sources,
                                        "route": flash_res.route,
                                    },
                                )
                                await self.session.send_tool_response(
                                    function_responses=[func_response]
                                )
                            print("[Tool Response] Grounded answer sent back to Gemini Live.")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self.is_connected:
                    logger.debug("Receive loop notice: %s", exc)
                break
