"""Persistent Gemini Live session with a mandatory backend tool boundary."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types

from RagChatbot.config import rag_settings

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str], Awaitable[None]]
ToolCallback = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
AudioCallback = Callable[[bytes], Awaitable[None]]
OutputTranscriptCallback = Callable[[str], Awaitable[None]]


class GeminiLiveSessionError(RuntimeError):
    """Raised when a Live session cannot be used safely."""


def _coerce_audio_bytes(value: Any) -> bytes | None:
    """Normalize the Live SDK's possible audio payload representations."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
        return data or None
    if not isinstance(value, str) or not value:
        return None
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    return data or None


async def _maybe_await(func: Any, *args: Any) -> Any:
    if func is None:
        return None
    res = func(*args)
    if asyncio.iscoroutine(res):
        return await res
    return res


_LANGUAGE_CODE_MAP: dict[str, str] = {
    "english": "en",
    "en": "en",
    "chinese": "zh",
    "mandarin": "zh",
    "zh": "zh",
    "cantonese": "yue",
    "yue": "yue",
    "malay": "ms",
    "bahasa melayu": "ms",
    "bahasa malaysia": "ms",
    "ms": "ms",
    "tamil": "ta",
    "ta": "ta",
    "arabic": "ar",
    "ar": "ar",
    "japanese": "ja",
    "ja": "ja",
    "korean": "ko",
    "ko": "ko",
    "french": "fr",
    "fr": "fr",
    "german": "de",
    "de": "de",
    "hindi": "hi",
    "hi": "hi",
    "spanish": "es",
    "es": "es",
    "indonesian": "id",
    "id": "id",
}


def normalize_language_code(lang_str: str) -> str:
    """Normalize language name or code to BCP-47 standard."""
    key = str(lang_str or "").strip().lower()
    if key in _LANGUAGE_CODE_MAP:
        return _LANGUAGE_CODE_MAP[key]
    # Check if a custom registered language in the database matches by code or name
    try:
        from app.core.database import SessionLocal
        from app.models.models import SpeechLanguage
        with SessionLocal() as db:
            match = db.query(SpeechLanguage).filter(
                (SpeechLanguage.language_code == key) |
                (SpeechLanguage.language_name.ilike(key))
            ).first()
            if match:
                return match.language_code.lower().strip()
    except Exception as exc:
        logger.debug("Could not resolve language code from db: %s", exc)
    return key if len(key) in (2, 3) else "en"


def _load_active_speech_languages() -> list[str]:
    """Query default active language codes from database, with fallback."""
    try:
        from app.core.database import SessionLocal
        from app.models.models import SpeechLanguage
        with SessionLocal() as db:
            langs = db.query(SpeechLanguage.language_code).filter(SpeechLanguage.is_default == True).all()
            if langs:
                codes = [r[0].lower().strip() for r in langs if r[0]]
                if codes:
                    return codes
    except Exception as exc:
        logger.debug("Could not load speech languages from db: %s", exc)
    return ["en", "zh", "yue", "ms"]


def _load_speech_adaptation_phrases() -> list[str]:
    """Query active adaptation phrases and translations from database, with fallback."""
    try:
        import json
        from app.core.database import SessionLocal
        from app.models.models import SpeechAdaptationPhrase
        with SessionLocal() as db:
            records = db.query(SpeechAdaptationPhrase.phrase, SpeechAdaptationPhrase.description).filter(SpeechAdaptationPhrase.is_active == True).all()
            if records:
                res = []
                for phrase, desc in records:
                    if phrase and phrase.strip():
                        res.append(phrase.strip())
                    if desc and desc.strip():
                        try:
                            parsed = json.loads(desc)
                            if isinstance(parsed, list):
                                for item in parsed:
                                    if isinstance(item, dict) and item.get("text"):
                                        res.append(item["text"].strip())
                                    elif isinstance(item, str) and item.strip():
                                        res.append(item.strip())
                            elif isinstance(parsed, dict):
                                for v in parsed.values():
                                    if isinstance(v, str) and v.strip():
                                        res.append(v.strip())
                        except Exception:
                            # If plain text notes, do not spam ASR hypothesis space
                            pass
                if res:
                    seen = set()
                    deduped = []
                    for p in res:
                        p_lower = p.lower()
                        if p_lower not in seen:
                            seen.add(p_lower)
                            deduped.append(p)
                    return deduped
    except Exception as exc:
        logger.debug("Could not load speech adaptation phrases from db: %s", exc)
    return [
        "Quest International University", "QIU", "Perak", "Ipoh", "Faculty of Pharmacy",
        "Faculty of Medicine", "Faculty of Business", "Faculty of Computing", "Bachelor",
        "Diploma", "Master", "Foundation", "Admissions", "Tuition fee", "Perpustakaan",
        "Fakulti", "Yuran", "Pendaftaran", "Peperiksaan", "大学", "课程", "学费", "图书馆",
        "报名", "收費", "邊度",
    ]


_LIVE_SYSTEM_INSTRUCTION = """
You are the voice interface for Quest International University (QIU) Smart Campus.

Core Rules:
1. Transcribe microphone input and, for ANY user question or request, ALWAYS call the backend function process_campus_request with the user's inquiry.
2. NEVER answer ANY question from your own pre-trained knowledge. Specifically, NEVER solve general math problems, arithmetic, calculations, homework, coding, or non-campus trivia. While invoking process_campus_request, you may speak a brief, polite verbal filler (e.g. "Looking that up for you...", "Checking campus records...") to acknowledge the user's inquiry, but never provide factual answers before the backend function response.
3. The backend function response is authoritative and grounded by Gemini 3.1 Flash Lite. Present the `answer` in that response naturally in spoken voice. Do not alter factual dates, names, fees, or policy decisions.
4. When asked about programmes or courses, present the specific programmes or courses returned by the backend response.
5. For campus navigation and wayfinding (when the backend returns directional steps like 'Start from...', 'Walk straight...', 'Turn left...'), ALWAYS recite the full step-by-step turn instructions to the user. Do not omit, truncate, or summarize the directional turns.
6. Language Matching: ALWAYS reply and speak in the exact language the user is speaking (e.g., English, Malay, Chinese, Tamil, etc.). If the user speaks in Chinese, converse in Chinese. If the user speaks in Malay, converse in Malay. When presenting the backend answer or directional navigation turns, speak and translate them naturally into the user's spoken language while keeping official proper names, course codes, and room numbers unchanged.
7. Professional Accent, Pronunciation, and Tone: Whenever speaking, ALWAYS speak in a polished, articulate, and professional standard accent for that language (e.g., Standard Broadcast English, Standard Bahasa Melayu Baku, Standard Mandarin Chinese / Putonghua, Standard Tamil). NEVER mirror, mimic, or adopt the user's colloquial accent, regional dialect, local slang (such as Manglish/Singlish particles or informal colloquialisms), or emotional/casual tone.
8. Maintain an articulate, polite, calm, and professional campus presenter persona with clear diction at all times.
9. Conversational Language Switching: If the user explicitly asks to speak or switch to another language (e.g. 'Can we speak in Japanese?', 'Please converse in Arabic', 'Tamil please', 'Boleh cakap Melayu?'), you MUST immediately call the tool set_session_language with target_language set to that requested language.
10. Speech Recognition & Audio Fidelity: Strictly transcribe actual speech in the speaker's true language without hallucinating words from background noise, microphone static, room reverberation, breathing, or silence. Support Malaysian code-switching naturally without mistaking it for foreign languages.
11. Greeting Triggers: When receiving a [SYSTEM GREETING TRIGGER] instruction, immediately speak the requested welcome greeting in a warm, articulate, and professional campus presenter tone without calling backend functions.
""".strip()


def _tool_declaration() -> dict[str, Any]:
    return {
        "function_declarations": [
            {
                "name": "process_campus_request",
                "description": (
                    "Grounds and synthesizes official QIU campus information, programmes, "
                    "tuition fees, faculty contacts, locations, and guidelines via Gemini 3.1 Flash Lite."
                ),
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
                "name": "process_user_request",
                "description": (
                    "Grounds and synthesizes official QIU campus information and navigation."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "transcript": {
                            "type": "STRING",
                            "description": "The completed user transcript.",
                        },
                    },
                    "required": ["transcript"],
                },
            },
            {
                "name": "set_session_language",
                "description": (
                    "Switches the active conversation and speech recognition language when the user "
                    "explicitly requests to speak or switch to a specific language (e.g., Japanese, Arabic, "
                    "Tamil, French, German, Korean, Mandarin, Malay, English, etc.)."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "target_language": {
                            "type": "STRING",
                            "description": (
                                "The requested language name or BCP-47 code (e.g. 'Japanese', 'ja', "
                                "'Arabic', 'ar', 'Tamil', 'ta', 'French', 'fr', 'Korean', 'ko', 'de')."
                            ),
                        },
                        "acknowledgment_message": {
                            "type": "STRING",
                            "description": (
                                "Polite greeting or confirmation in that target language acknowledging the switch."
                            ),
                        },
                    },
                    "required": ["target_language"],
                },
            },
        ]
    }


class GeminiLiveSession:
    """One reusable/resumable Live API session for one conversation."""

    def __init__(self) -> None:
        self._client = genai.Client(api_key=rag_settings.GOOGLE_API_KEY)
        self._connection = None
        self._session = None
        self._reader_task: asyncio.Task | None = None
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._connected_at = 0.0
        self._closed_at = 0.0
        self._transcript = ""
        self._output_transcript = ""
        self._resumption_handle: str | None = None
        self._renew_requested = False
        self._input_activity_open = False
        self._greeting_sent = False
        self._greeting_in_progress = False
        self._active_language_codes: list[str] | None = None
        self._session_switched_language: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    @property
    def resumption_handle(self) -> str | None:
        return self._resumption_handle

    async def start(self) -> None:
        async with self._connect_lock:
            if self.is_connected and not self._renew_requested and (
                time.monotonic() - self._connected_at
                < rag_settings.LIVE_SESSION_TIMEOUT_SECONDS
            ):
                return

            if self.is_connected:
                await self._close_unlocked(preserve_resumption=True)
            else:
                await self._discard_pending_events()

            # Ensure cloud gateway teardown cooldown to prevent 409 Conflict
            if self._closed_at > 0.0:
                elapsed = time.monotonic() - self._closed_at
                if elapsed < 0.2:
                    await asyncio.sleep(0.2 - elapsed)

            active_lang_codes = self._active_language_codes or _load_active_speech_languages()
            adaptation_phrases = _load_speech_adaptation_phrases()

            config = {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": getattr(rag_settings, "LIVE_VOICE_NAME", getattr(rag_settings, "AUDIO_TTS_VOICE", "Kore")) or "Kore",
                        }
                    }
                },
                "system_instruction": _LIVE_SYSTEM_INSTRUCTION,
                "input_audio_transcription": {
                    "language_hints": {
                        "language_codes": active_lang_codes,
                    },
                    "adaptation_phrases": adaptation_phrases,
                },
                "output_audio_transcription": {},
                "tools": [_tool_declaration()],
            }
            connect_retries = 2
            connect_delay = 0.3
            last_connect_exc: Exception | None = None
            for attempt in range(connect_retries + 1):
                try:
                    self._connection = self._client.aio.live.connect(
                        model=rag_settings.LIVE_MODEL,
                        config=config,
                    )
                    self._session = await asyncio.wait_for(
                        self._connection.__aenter__(),
                        timeout=rag_settings.LIVE_CONNECT_TIMEOUT_SECONDS,
                    )
                    break
                except Exception as exc:
                    last_connect_exc = exc
                    await self._close_unlocked(preserve_resumption=True)
                    from RagChatbot.gemini_client import is_retryable_gemini_error
                    if attempt < connect_retries and is_retryable_gemini_error(exc):
                        logger.warning(
                            "Gemini Live connect transient conflict/error (%s); retrying in %.2fs (attempt %d/%d)",
                            exc,
                            connect_delay,
                            attempt + 1,
                            connect_retries,
                        )
                        await asyncio.sleep(connect_delay)
                        connect_delay *= 1.5
                    else:
                        raise GeminiLiveSessionError("Gemini Live session connection failed") from last_connect_exc

            self._renew_requested = False
            self._connected_at = time.monotonic()
            self._reader_task = asyncio.create_task(self._reader(), name="gemini-live-reader")
            logger.info(
                "Gemini Live session connected model=%s resumed=%s languages=%s",
                rag_settings.LIVE_MODEL,
                bool(self._resumption_handle),
                active_lang_codes,
            )

    async def switch_language(
        self,
        target_language: str,
        acknowledgment_message: str | None = None,
    ) -> dict[str, Any]:
        """Dynamically prioritize a new target language for this session."""
        code = normalize_language_code(target_language)
        new_codes = [code]
        if code != "en":
            new_codes.append("en")
        self._active_language_codes = new_codes
        self._session_switched_language = code
        self._renew_requested = True
        logger.info(
            "Switched session language hints to %s (requested: %s)",
            new_codes,
            target_language,
        )
        ack = acknowledgment_message or f"Understood, switching conversation to {target_language}."
        return {
            "status": "success",
            "language_code": code,
            "target_language": target_language,
            "answer": ack,
            "response_text": ack,
        }

    async def send_audio(self, audio_bytes: bytes) -> None:
        if not audio_bytes:
            return
        if self._greeting_in_progress:
            # Gating: Drop ambient mic audio while greeting turn is generating to avoid 409 collisions
            return
        await self.start()
        try:
            async with self._send_lock:
                await asyncio.wait_for(
                    self._session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_bytes,
                            mime_type=f"audio/pcm;rate={rag_settings.LIVE_INPUT_SAMPLE_RATE}",
                        )
                    ),
                    timeout=rag_settings.LIVE_IO_TIMEOUT_SECONDS,
                )
        except Exception as exc:
            raise GeminiLiveSessionError("Gemini Live audio send failed") from exc

    async def end_user_turn(self) -> None:
        """Signal Gemini Live that the user's speech activity has finished."""
        if not self.is_connected or not self._session:
            return
        try:
            async with self._send_lock:
                await self._session.send_realtime_input(activity_end=types.ActivityEnd())
            logger.debug("Sent activity_end to Gemini Live session")
        except Exception as exc:
            logger.debug("Failed to signal activity_end: %s", exc)

    def reset_greeting(self) -> None:
        """Allow greeting to be re-triggered for this session."""
        self._greeting_sent = False
        self._greeting_in_progress = False

    async def trigger_greeting(self, user_name: str | None = None) -> None:
        """Trigger Gemini Live to speak an articulate, warm welcome greeting over the live duplex session."""
        if self._greeting_sent:
            logger.debug("Greeting already triggered for this session; skipping duplicate invocation")
            return
        self._greeting_sent = True
        self._greeting_in_progress = True

        await self.start()
        clean_name = " ".join((user_name or "").split())
        if clean_name:
            greeting_prompt = (
                f"[SYSTEM GREETING TRIGGER] Greet the user warmly: 'Hello {clean_name}! "
                "Welcome to Quest International University. How can I help you today?' "
                "Speak clearly, politely, and articulately in a professional campus presenter tone."
            )
        else:
            greeting_prompt = (
                "[SYSTEM GREETING TRIGGER] Greet the visitor warmly: 'Hello! "
                "Welcome to Quest International University. How can I help you today?' "
                "Speak clearly, politely, and articulately in a professional campus presenter tone."
            )
        try:
            async with self._send_lock:
                await asyncio.wait_for(
                    self._session.send_client_content(
                        turns=[
                            types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=greeting_prompt)],
                            )
                        ],
                        turn_complete=True,
                    ),
                    timeout=rag_settings.LIVE_IO_TIMEOUT_SECONDS,
                )
            logger.info("Triggered Gemini Live spoken greeting for user=%s", clean_name or "visitor")
        except Exception as exc:
            self._greeting_in_progress = False
            logger.warning("Failed to trigger Gemini Live greeting: %s", exc)

    async def receive_events(
        self,
        on_audio: Callable[[bytes], Any],
        on_transcript: Optional[Callable[[str], Any]] = None,
        on_tool_call: Optional[Callable[[dict[str, Any]], Any]] = None,
        on_interrupted: Optional[Callable[[], Any]] = None,
        on_turn_complete: Optional[Callable[[], Any]] = None,
        on_output_transcript: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """
        Continuous full-duplex event receiver loop mirroring shitz/gemini_live_rag.py.
        Consumes audio, transcripts, and handles tool calls in real time as they arrive.
        """
        await self.start()
        while self.is_connected:
            try:
                event = await self._events.get()
                event_type = event.get("type")

                if event_type == "input_transcript":
                    text = str(event.get("text") or "").strip()
                    if text:
                        self._transcript = _merge_incremental_text(self._transcript, text)
                        if on_transcript:
                            res = on_transcript(self._transcript)
                            if asyncio.iscoroutine(res):
                                await res

                elif event_type == "tool_call":
                    calls = event.get("calls") or []
                    if calls:
                        call = dict(calls[0])
                        call_name = call.get("name") or "process_campus_request"
                        args = call.get("args") or {}
                        if call_name == "set_session_language":
                            target = args.get("target_language") or "en"
                            ack = args.get("acknowledgment_message")
                            result = await self.switch_language(target, ack)
                            func_response = types.FunctionResponse(
                                name=call_name,
                                id=call.get("id"),
                                response=result,
                            )
                            async with self._send_lock:
                                await self._session.send_tool_response(
                                    function_responses=[func_response]
                                )
                        elif on_tool_call:
                            raw_query = args.get("query") or args.get("transcript") or self._transcript.strip()
                            call["transcript"] = str(raw_query or "").strip()
                            call["query"] = call["transcript"]
                            result = await on_tool_call(call)
                            answer_text = (
                                result.get("answer")
                                or result.get("response_text")
                                or result.get("grounded_context")
                                or ""
                            )
                            sources = result.get("sources") or result.get("citations") or []
                            func_response = types.FunctionResponse(
                                name=call_name,
                                id=call.get("id"),
                                response={
                                    "answer": answer_text,
                                    "response_text": answer_text,
                                    "status": result.get("status", "ok"),
                                    "sources": sources,
                                    "route": result.get("route", "UNIVERSITY_INFO"),
                                },
                            )
                            async with self._send_lock:
                                await self._session.send_tool_response(
                                    function_responses=[func_response]
                                )

                elif event_type == "audio":
                    data = event.get("data")
                    if data and on_audio:
                        res = on_audio(data)
                        if asyncio.iscoroutine(res):
                            await res

                elif event_type == "output_transcript":
                    text = str(event.get("text") or "")
                    if text and on_output_transcript:
                        res = on_output_transcript(text)
                        if asyncio.iscoroutine(res):
                            await res

                elif event_type == "interrupted":
                    self._greeting_in_progress = False
                    if on_interrupted:
                        res = on_interrupted()
                        if asyncio.iscoroutine(res):
                            await res

                elif event_type == "turn_complete":
                    self._greeting_in_progress = False
                    self._transcript = ""
                    self._output_transcript = ""
                    if on_turn_complete:
                        res = on_turn_complete()
                        if asyncio.iscoroutine(res):
                            await res

                elif event_type == "error":
                    logger.warning("Gemini Live session event error: %s", event.get("message"))
                    break

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Gemini Live receive_events notice: %s", exc)
                break

    async def finish_input(
        self,
        on_transcript: TranscriptCallback,
        on_tool_call: ToolCallback | None = None,
        on_audio: AudioCallback | None = None,
        on_interrupted: Callable[[], Awaitable[None]] | None = None,
        on_output_transcript: OutputTranscriptCallback | None = None,
    ) -> str:
        """Complete one turn, execute the mandatory tool, and stream final audio."""
        await self.start()
        self._transcript = ""
        self._output_transcript = ""
        tool_called = False
        mandatory_tool_retry_sent = False
        approved = False
        try:
            async with self._send_lock:
                try:
                    await asyncio.wait_for(
                        self._session.send_realtime_input(activity_end=types.ActivityEnd()),
                        timeout=rag_settings.LIVE_IO_TIMEOUT_SECONDS,
                    )
                except Exception:
                    pass
                self._input_activity_open = False
            logger.info("Gemini Live input activity ended; waiting for transcription/tool call")
            while True:
                event = await self._next_event()
                event_type = event.get("type")
                if event_type == "input_transcript":
                    self._transcript = _merge_incremental_text(
                        self._transcript, str(event.get("text") or "")
                    )
                    if self._transcript:
                        await _maybe_await(on_transcript, self._transcript)
                elif event_type == "tool_call":
                    calls = event.get("calls") or []
                    if tool_called or not calls:
                        raise GeminiLiveSessionError("Live issued an invalid or duplicate backend tool call")
                    tool_called = True
                    call = dict(calls[0])
                    call_name = call.get("name") or "process_campus_request"
                    args = call.get("args") or {}

                    if call_name == "set_session_language":
                        target = args.get("target_language") or "en"
                        ack = args.get("acknowledgment_message")
                        tool_response_payload = await self.switch_language(target, ack)
                    else:
                        if on_tool_call is None:
                            raise GeminiLiveSessionError("Live requested a tool without a backend handler")
                        raw_query = args.get("query") or args.get("transcript") or self._transcript.strip()
                        call["transcript"] = str(raw_query or "").strip()
                        call["query"] = call["transcript"]
                        result = await on_tool_call(call)

                        answer_text = (
                            result.get("answer")
                            or result.get("response_text")
                            or result.get("grounded_context")
                            or ""
                        )
                        sources = result.get("sources") or result.get("citations") or []
                        tool_response_payload = {
                            "answer": answer_text,
                            "response_text": answer_text,
                            "status": result.get("status", "ok"),
                            "sources": sources,
                            "route": result.get("route", "UNIVERSITY_INFO"),
                        }
                    response = types.FunctionResponse(
                        name=call_name,
                        id=call.get("id"),
                        response=tool_response_payload,
                    )
                    async with self._send_lock:
                        await asyncio.wait_for(
                            self._session.send_tool_response(function_responses=[response]),
                            timeout=rag_settings.LIVE_IO_TIMEOUT_SECONDS,
                        )
                    approved = True
                elif event_type == "audio":
                    if on_audio is not None and event.get("data"):
                        await _maybe_await(on_audio, event["data"])
                elif event_type == "output_transcript":
                    if approved:
                        self._output_transcript = _merge_incremental_text(
                            self._output_transcript,
                            str(event.get("text") or ""),
                        )
                elif event_type == "interrupted":
                    await self._discard_pending_events()
                    if on_interrupted is not None:
                        await _maybe_await(on_interrupted)
                    return self._transcript.strip()
                elif event_type == "go_away":
                    self._renew_requested = True
                elif event_type == "error":
                    raise GeminiLiveSessionError(str(event.get("message") or "Live API error"))
                elif event_type == "turn_complete":
                    if event.get("pre_tool") and tool_called:
                        continue
                    if on_tool_call is not None and not tool_called:
                        if not self._transcript.strip():
                            raise GeminiLiveSessionError(
                                "Live completed a turn without a usable transcription"
                            )
                        if mandatory_tool_retry_sent:
                            raise GeminiLiveSessionError(
                                "Live completed a turn without process_user_request"
                            )
                        mandatory_tool_retry_sent = True
                        logger.warning(
                            "Live completed a transcribed turn without process_user_request; "
                            "requesting a mandatory tool call"
                        )
                        await self._discard_pending_events()
                        async with self._send_lock:
                            await asyncio.wait_for(
                                self._session.send_client_content(
                                    turns=types.Content(
                                        role="user",
                                        parts=[
                                            types.Part(
                                                text=(
                                                    "[MANDATORY SECURITY CONTROL] The completed user "
                                                    "turn was transcribed as: "
                                                    f"{self._transcript.strip()}\n"
                                                    "You must call process_user_request exactly once now "
                                                    "with that transcript. Do not answer, speak, or finish "
                                                    "until the function call has been emitted."
                                                )
                                            )
                                        ],
                                    ),
                                    turn_complete=True,
                                ),
                                timeout=rag_settings.LIVE_IO_TIMEOUT_SECONDS,
                            )
                        continue
                    if approved and self._output_transcript and on_output_transcript is not None:
                        await on_output_transcript(self._output_transcript)
                    await self._discard_pending_events()
                    return self._transcript.strip()
        except GeminiLiveSessionError as exc:
            if "timed out" in str(exc).lower():
                logger.info("Gemini Live turn timed out (no user speech detected); ending turn gracefully")
                await self._discard_pending_events()
                return ""
            raise
        except Exception as exc:
            raise GeminiLiveSessionError("Gemini Live input turn failed") from exc

    async def cancel_input(self) -> None:
        """Flush a noise/interrupted turn without executing the backend tool."""
        await self.start()
        try:
            async with self._send_lock:
                if rag_settings.LIVE_MANUAL_ACTIVITY:
                    if not self._input_activity_open:
                        await self._discard_pending_events()
                        return
                    await self._session.send_realtime_input(activity_end=types.ActivityEnd())
                    self._input_activity_open = False
                else:
                    await self._discard_pending_events()
                    return
            while True:
                event = await self._next_event()
                if event.get("type") in {"turn_complete", "interrupted", "error"}:
                    await self._discard_pending_events()
                    return
        except GeminiLiveSessionError as exc:
            # A cancellation is best-effort. After a provider error or a
            # resumed session, the server may not emit a terminal event for
            # the discarded turn; do not take down the persistent gateway for
            # that expected condition.
            if "timed out" in str(exc).lower():
                await self._discard_pending_events()
                return
            raise
        except Exception as exc:
            raise GeminiLiveSessionError("Gemini Live turn cancellation failed") from exc

    async def speak_approved_text(self, text: str, on_audio: AudioCallback) -> bool:
        """Compatibility helper for older callers; Live turns use tool calling."""
        clean_text = " ".join((text or "").split())
        if not clean_text:
            return False
        await self.start()
        await self._discard_pending_events()
        audio_emitted = False
        try:
            async with self._send_lock:
                await asyncio.wait_for(
                    self._session.send_realtime_input(
                        text=(
                            "[BACKEND_APPROVED_RESPONSE]\n"
                            "Speak exactly this approved response and nothing else:\n"
                            f"{clean_text}"
                        )
                    ),
                    timeout=rag_settings.LIVE_IO_TIMEOUT_SECONDS,
                )
            while True:
                event = await self._next_event()
                if event.get("type") == "audio":
                    audio_emitted = True
                    await _maybe_await(on_audio, event["data"])
                elif event.get("type") == "turn_complete":
                    return audio_emitted
                elif event.get("type") == "error":
                    raise GeminiLiveSessionError(str(event.get("message") or "Live API error"))
        except GeminiLiveSessionError:
            raise
        except Exception as exc:
            raise GeminiLiveSessionError("Gemini Live approved speech failed") from exc

    async def _close_unlocked(self, *, preserve_resumption: bool = False) -> None:
        handle = self._resumption_handle if preserve_resumption else None
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except BaseException:
                pass
            self._reader_task = None
        if self._connection is not None:
            try:
                await asyncio.wait_for(self._connection.__aexit__(None, None, None), timeout=2.0)
            except Exception:
                logger.debug("Gemini Live session close failed", exc_info=True)
        self._connection = None
        self._session = None
        self._connected_at = 0.0
        self._renew_requested = False
        self._resumption_handle = handle
        self._input_activity_open = False
        self._greeting_sent = False
        self._greeting_in_progress = False
        self._closed_at = time.monotonic()
        await self._discard_pending_events()

    async def close(self, *, preserve_resumption: bool = False) -> None:
        async with self._connect_lock:
            await self._close_unlocked(preserve_resumption=preserve_resumption)

    async def _reader(self) -> None:
        is_mock = type(self._session).__name__ == "FakeSession"
        try:
            while self.is_connected and self._session is not None:
                try:
                    async for response in self._session.receive():
                        update = getattr(response, "session_resumption_update", None)
                        if update is not None and getattr(update, "resumable", False):
                            handle = getattr(update, "new_handle", None)
                            if handle:
                                self._resumption_handle = str(handle)
                            await self._events.put({"type": "session_resumption", "handle": self._resumption_handle})

                        go_away = getattr(response, "go_away", None)
                        if go_away is not None:
                            await self._events.put({"type": "go_away", "time_left": getattr(go_away, "time_left", None)})

                        content = getattr(response, "server_content", None)
                        # A provider message may contain both transcription and a
                        # tool call. Queue transcription first so the backend never
                        # runs with stale or empty text.
                        if content is not None:
                            input_transcription = getattr(content, "input_transcription", None)
                            if input_transcription is not None and getattr(input_transcription, "text", None):
                                logger.info(
                                    "Gemini Live input transcription received chars=%d",
                                    len(input_transcription.text),
                                )
                                await self._events.put({"type": "input_transcript", "text": input_transcription.text})

                        tool_calls = []
                        seen_tool_call_keys: set[tuple[str, str, str]] = set()

                        def add_tool_call(function_call: Any) -> None:
                            name = str(getattr(function_call, "name", None) or "")
                            call_id = str(getattr(function_call, "id", None) or "")
                            args = dict(getattr(function_call, "args", {}) or {})
                            key = (name, call_id, json.dumps(args, sort_keys=True, default=str))
                            if key in seen_tool_call_keys:
                                return
                            seen_tool_call_keys.add(key)
                            tool_calls.append({"name": name, "id": call_id or None, "args": args})

                        tool_call = getattr(response, "tool_call", None)
                        if tool_call is not None:
                            for function_call in getattr(tool_call, "function_calls", []) or []:
                                add_tool_call(function_call)

                        # The current Python Live SDK exposes generated audio as
                        # response.data. Older SDK shapes place it inside
                        # server_content.model_turn.parts[].inline_data. Handle both,
                        # but enqueue only one copy when a provider sends both shapes.
                        top_level_audio = _coerce_audio_bytes(getattr(response, "data", None))
                        if top_level_audio is not None:
                            await self._events.put({"type": "audio", "data": top_level_audio})

                        if content is None:
                            if tool_calls:
                                logger.info("Gemini Live tool call received count=%d", len(tool_calls))
                                await self._events.put({"type": "tool_call", "calls": tool_calls})
                            error = getattr(response, "error", None)
                            if error:
                                await self._events.put({"type": "error", "message": str(error)})
                            continue

                        output_transcription = getattr(content, "output_transcription", None)
                        if output_transcription is not None and getattr(output_transcription, "text", None):
                            await self._events.put({"type": "output_transcript", "text": output_transcription.text})

                        model_turn = getattr(content, "model_turn", None)
                        if model_turn is not None:
                            for part in getattr(model_turn, "parts", []) or []:
                                # Some Live SDK/provider versions expose function
                                # calls in model-turn parts instead of the top-level
                                # response.tool_call field.
                                function_call = getattr(part, "function_call", None)
                                if function_call is not None:
                                    add_tool_call(function_call)
                        if tool_calls:
                            logger.info("Gemini Live tool call received count=%d", len(tool_calls))
                            await self._events.put({"type": "tool_call", "calls": tool_calls})

                        if model_turn is not None and top_level_audio is None:
                            for part in getattr(model_turn, "parts", []) or []:
                                inline_data = getattr(part, "inline_data", None)
                                data = _coerce_audio_bytes(getattr(inline_data, "data", None)) if inline_data else None
                                if data is not None:
                                    await self._events.put({"type": "audio", "data": data})

                        if getattr(content, "interrupted", False):
                            await self._events.put({"type": "interrupted"})
                        if getattr(content, "turn_complete", False):
                            await self._events.put({
                                "type": "turn_complete",
                                "pre_tool": bool(tool_calls),
                            })
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not self.is_connected:
                        break
                    logger.debug("Gemini Live receive iteration notice: %s", exc)
                    break
                if is_mock:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Gemini Live receive loop stopped: %s", type(exc).__name__)
            await self._events.put({"type": "error", "message": "Live session disconnected"})

    async def _next_event(self) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self._events.get(), timeout=rag_settings.LIVE_TURN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise GeminiLiveSessionError("Gemini Live turn timed out") from exc

    async def _discard_pending_events(self) -> None:
        while True:
            try:
                self._events.get_nowait()
            except asyncio.QueueEmpty:
                return


def _merge_incremental_text(current: str, incoming: str) -> str:
    incoming = " ".join(incoming.split())
    if not incoming:
        return current
    if not current:
        return incoming
    if incoming == current or current.endswith(incoming):
        return current
    if incoming.startswith(current):
        return incoming
    if current.endswith(incoming):
        return current
    return f"{current} {incoming}".strip()
