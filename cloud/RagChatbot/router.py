"""
FastAPI router for the RAG Chatbot module.

Exposes:
  POST /api/chatbot/chat         – Main query endpoint for edge devices and UI.
  POST /api/chatbot/chat/stream  – SSE stream for edge audio playback.
  POST /api/chatbot/chat/audio   – Audio multipart upload for the RAG pipeline.
  POST /api/chatbot/ingest       – Trigger ingestion/re-indexing of a document.
  GET  /api/chatbot/health       – Health check for the chatbot subsystem.

Security:
  - Chat endpoints allow anonymous visitor access to PUBLIC documents.
  - A valid Bearer JWT is required for document levels above visitor/PUBLIC.
  - The /ingest endpoint additionally requires CONTENT_ADMIN or SUPER_ADMIN.
  - The /chat endpoint resolves the user role from the trusted database record,
    never from the request body.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import json
import os
import time
import logging
import hashlib
from collections import OrderedDict
from collections.abc import Iterator
from threading import Lock, BoundedSemaphore
from typing import AsyncIterator

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import iterate_in_threadpool
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_content_admin
from RagChatbot.config import rag_settings
from RagChatbot.generation.audio_query_extractor import AudioQueryExtractionError
from RagChatbot.generation.gemini_live_service import GeminiLiveError
from RagChatbot.schemas import (
    AudioChatResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    IngestionRequest,
    IngestionResponse,
)
from RagChatbot.services.audio_chat_service import process_audio_chat, process_audio_chat_stream
from RagChatbot.services.chat_service import process_chat, process_chat_stream, process_public_smoke_chat
from RagChatbot.services.ingestion_service import ingest_document
from RagChatbot.security.auth_context import resolve_auth_context
from RagChatbot.logging.timing_logger import cloud_timing
from app.core.rate_limit import client_ip, enforce_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatbot", tags=["RAG Chatbot"])

# Optional bearer scheme. Missing tokens use visitor/PUBLIC access.
_bearer_scheme = HTTPBearer(auto_error=False)

_GREETING_AUDIO_CACHE: OrderedDict[str, str] = OrderedDict()
_GREETING_AUDIO_CACHE_LOCK = Lock()
_GREETING_AUDIO_CACHE_SIZE = 128
_AI_JOB_LIMIT = BoundedSemaphore(max(1, int(os.getenv("MAX_AI_CONCURRENCY", "8"))))


def _enforce_ai_quota(request: Request, token: str | None, device_id: str | None, *, audio: bool = False) -> None:
    ip = client_ip(request)
    enforce_limit(f"ai-ip:{ip}", 120, 60, "AI request quota exceeded")
    identity = f"auth:{hashlib.sha256(token.encode()).hexdigest()[:16]}" if token else f"anon:{ip}"
    enforce_limit(identity, 60 if token else 8, 60, "AI request quota exceeded")
    if audio:
        enforce_limit(f"audio:{identity}", 20, 60, "Audio request quota exceeded")


def _greeting_text(full_name: str | None, given_name: str | None = None) -> str:
    display_name = " ".join((given_name or "").split())
    if not display_name and full_name:
        display_name = full_name.strip().split()[0] if full_name.strip() else ""
    return f"Hi {display_name}, how may I help you today?" if display_name else "Hi, how may I help you today?"


def _cached_greeting_audio(text: str, given_name: str | None = None) -> str | None:
    """Deprecated. All spoken greeting audio is handled by Gemini Live."""
    return None


def _split_stream_text(text: str, max_chars: int = 240) -> Iterator[str]:
    """Split a generated answer into TTS-friendly streamed chunks."""
    pending = " ".join(text.split())
    while len(pending) > max_chars:
        split_at = max(
            pending.rfind(". ", 0, max_chars),
            pending.rfind("? ", 0, max_chars),
            pending.rfind("! ", 0, max_chars),
            pending.rfind(", ", 0, max_chars),
        )
        if split_at < max_chars // 2:
            split_at = pending.rfind(" ", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars

        chunk = pending[: split_at + 1].strip()
        if chunk:
            yield chunk
        pending = pending[split_at + 1 :].strip()

    if pending:
        yield pending


def _sse_event(event: str, payload: dict) -> str:
    """Serialize one Server-Sent Event message."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _ndjson_event(event: str, payload: dict) -> bytes:
    """Serialize one newline-delimited JSON streaming event."""
    return (json.dumps({"event": event, "data": payload}, ensure_ascii=False) + "\n").encode("utf-8")


def _chat_response_events(response: ChatResponse) -> Iterator[str]:
    """Yield chatbot answer chunks followed by the complete response metadata."""
    for chunk in _split_stream_text(response.answer):
        yield _sse_event("chunk", {"text": chunk})
    yield _sse_event("done", response.model_dump(mode="json"))


def _require_public_smoke_test_enabled() -> None:
    if not rag_settings.ENABLE_PUBLIC_SMOKE_TEST:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public chatbot smoke test endpoint is disabled.",
        )


async def _read_valid_audio_upload(audio: UploadFile) -> tuple[bytes, str]:
    """Validate an uploaded audio file and return its bytes and MIME type."""
    if audio.content_type and not audio.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected an audio file, got {audio.content_type}.",
        )

    chunks = []
    total = 0
    limit = rag_settings.AUDIO_MAX_UPLOAD_BYTES
    while total <= limit:
        chunk = await audio.read(min(1024 * 1024, limit - total + 1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            break
    audio_bytes = b"".join(chunks) if total <= limit else b""

    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded audio file is empty.",
        )

    if len(audio_bytes) > rag_settings.AUDIO_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Audio file exceeds the maximum allowed size of "
                f"{rag_settings.AUDIO_MAX_UPLOAD_BYTES} bytes."
            ),
        )

    return audio_bytes, audio.content_type or "audio/wav"


def _should_stream_tts_audio(response: AudioChatResponse) -> bool:
    """Return whether a validated/canned audio response should be spoken."""
    return bool(
        rag_settings.AUDIO_TTS_ENABLED
        and response.text_response
        and response.status in {"ok", "blocked", "no_access", "auth_required"}
    )


async def _audio_chat_stream_events(
    *,
    audio_bytes: bytes,
    mime_type: str,
    bearer_token: str | None,
    device_id: str | None,
    session_id: int | None,
    db: Session,
) -> AsyncIterator[bytes]:
    """Run the audio RAG pipeline and stream TTS PCM chunks as NDJSON line by line."""
    try:
        stream_gen = process_audio_chat_stream(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            bearer_token=bearer_token,
            device_id=device_id,
            session_id=session_id,
            db=db,
        )
        async for event in iterate_in_threadpool(stream_gen):
            event_type = event["event"]
            logger.info("STREAM_DEBUG [%.3f]: Streaming out %s event over network", datetime.datetime.now().timestamp(), event_type)
            yield _ndjson_event(event_type, event["data"])
    except AudioQueryExtractionError:
        yield _ndjson_event(
            "error",
            {"message": "Audio query extraction service is temporarily unavailable."},
        )
        return
    except GeminiLiveError:
        yield _ndjson_event(
            "error",
            {"message": "Audio generation service is temporarily unavailable."},
        )
        return
    except Exception:
        logger.exception("Unexpected error in audio chat stream")
        yield _ndjson_event(
            "error",
            {"message": "An unexpected error occurred while processing the audio."},
        )
        return


# ── Health Check ──────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, summary="Chatbot health check")
def chatbot_health():
    """
    Returns the operational status of the RAG Chatbot and whether the
    Google AI Studio API key has been configured.

    This endpoint does NOT require authentication so edge devices can
    poll it before presenting the chatbot UI.
    """
    return HealthResponse(
        status="ok",
        google_api_configured=bool(rag_settings.GOOGLE_API_KEY),
        timestamp=datetime.datetime.utcnow(),
    )


@router.post(
    "/chat/public-smoke-test",
    response_model=ChatResponse,
    summary="Submit a public-only RAG smoke-test query without JWT",
)
def public_smoke_chat(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    No-JWT RAG smoke test for edge-device diagnostics.

    Disabled unless `RAG_ENABLE_PUBLIC_SMOKE_TEST=1` is set on the cloud
    backend. When enabled, retrieval is limited to PUBLIC documents only.
    """
    _require_public_smoke_test_enabled()
    _enforce_ai_quota(request, None, body.device_id)
    if not _AI_JOB_LIMIT.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="AI service is busy; retry later")
    try:
        return process_public_smoke_chat(request=body, db=db)
    finally:
        _AI_JOB_LIMIT.release()


@router.post(
    "/chat/public-smoke-test/stream",
    summary="Submit a public-only RAG smoke-test query and stream chunks without JWT",
)
def public_smoke_chat_stream(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Streaming no-JWT RAG smoke test for edge audio playback diagnostics.

    Disabled unless `RAG_ENABLE_PUBLIC_SMOKE_TEST=1` is set on the cloud
    backend. When enabled, retrieval is limited to PUBLIC documents only.
    """
    _require_public_smoke_test_enabled()
    _enforce_ai_quota(request, None, body.device_id)
    if not _AI_JOB_LIMIT.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="AI service is busy; retry later")
    try:
        response = process_public_smoke_chat(request=body, db=db)
    finally:
        _AI_JOB_LIMIT.release()
    return StreamingResponse(
        _chat_response_events(response),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Chat Endpoint ─────────────────────────────────────────────────────────────

@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Submit a user query to the RAG chatbot",
)
def chat(
    body: ChatRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    """
    Primary RAG chatbot endpoint.

    The edge device POSTs the user's query here with or without face authentication.
    The cloud backend:
      1. Uses visitor/PUBLIC access when no JWT is present, or validates the JWT
         and resolves the user's role from the database when one is provided.
      2. Screens the query for prompt injection.
      3. Retrieves only authorized document chunks.
      4. Generates a grounded answer using Google AI.
      5. Returns the answer with citations and logs the interaction.

    **Never** include the Google API key or database credentials in
    requests to this endpoint.
    """
    bearer_token = credentials.credentials if credentials else None
    _enforce_ai_quota(request, bearer_token, body.device_id)
    if not _AI_JOB_LIMIT.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="AI service is busy; retry later")
    t0 = time.monotonic()
    client_sent_at = request.headers.get("X-Client-Sent-At")
    cloud_timing.log_receive("REST_CHAT_REQUEST", client_sent_at=client_sent_at, query=(body.query or "")[:60], device_id=body.device_id)
    try:
        resp = process_chat(request=body, bearer_token=bearer_token, db=db)
        duration_ms = (time.monotonic() - t0) * 1000.0
        cloud_timing.log_send("REST_CHAT_RESPONSE", duration_ms=duration_ms, status="ok")
        return resp
    finally:
        _AI_JOB_LIMIT.release()


@router.post(
    "/chat/greeting/audio",
    response_model=AudioChatResponse,
    summary="Generate the authenticated kiosk greeting",
)
def chat_greeting_audio(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    """Return the short session greeting and optional PCM speech independently of chat input."""
    bearer_token = credentials.credentials if credentials else None
    context = resolve_auth_context(bearer_token, db)
    given_name = context.given_name if context.authenticated else None
    greeting = _greeting_text(context.full_name if context.authenticated else None, given_name)
    audio_base64 = None
    if rag_settings.AUDIO_TTS_ENABLED:
        audio_base64 = _cached_greeting_audio(greeting, given_name=given_name)
    return AudioChatResponse(
        text_response=greeting,
        audio_response=audio_base64,
        status="ok",
        access_granted=True,
    )


def _stream_with_semaphore_release(stream_gen: Iterator[str]) -> Iterator[str]:
    try:
        yield from stream_gen
    finally:
        _AI_JOB_LIMIT.release()


@router.post(
    "/chat/stream",
    summary="Submit a user query and stream response chunks",
)
def chat_stream(
    body: ChatRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    """
    Streaming chatbot endpoint for edge audio playback.

    The existing RAG pipeline performs RBAC filtering, true streaming answer generation,
    citation building, and audit logging for authenticated sessions. Without a
    JWT, it uses visitor/PUBLIC access. The final answer is emitted as real-time
    Server-Sent Events so the edge device receives the first response tokens with minimal latency.
    """
    bearer_token = credentials.credentials if credentials else None
    _enforce_ai_quota(request, bearer_token, body.device_id)
    if not _AI_JOB_LIMIT.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="AI service is busy; retry later")
    try:
        stream_gen = process_chat_stream(request=body, bearer_token=bearer_token, db=db)
        return StreamingResponse(
            _stream_with_semaphore_release(stream_gen),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception:
        _AI_JOB_LIMIT.release()
        raise


# ── Audio Chat Endpoint ──────────────────────────────────────────────────────

@router.post(
    "/chat/audio",
    response_model=AudioChatResponse,
    summary="Submit audio query from edge device to the RAG chatbot",
)
async def chat_audio(
    request: Request,
    audio: UploadFile = File(...),
    device_id: str | None = Form(None),
    session_id: int | None = Form(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    """
    Accept audio recording from the edge device, process it through the
    secure audio RAG pipeline, and return text + audio response.

    The audio is sent to Gemini for controlled query extraction first,
    then RBAC-filtered retrieval and response generation.

    Auth: Optional Bearer JWT. Missing JWT → visitor/PUBLIC access only.
    """
    # ── Validate upload ───────────────────────────────────────────────
    if audio.content_type and not audio.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid audio upload.",
        )

    audio_bytes = await audio.read()

    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded audio file is empty.",
        )

    if len(audio_bytes) > rag_settings.AUDIO_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Audio file exceeds the maximum allowed size of {rag_settings.AUDIO_MAX_UPLOAD_BYTES} bytes."
            ),
        )

    # ── Determine MIME type ───────────────────────────────────────────
    mime_type = audio.content_type or "audio/wav"
    _enforce_ai_quota(request, credentials.credentials if credentials else None, device_id, audio=True)

    # ── Extract bearer token ──────────────────────────────────────────
    bearer_token = credentials.credentials if credentials else None

    # ── Call audio RAG pipeline ───────────────────────────────────────
    t0 = time.monotonic()
    client_sent_at = request.headers.get("X-Client-Sent-At")
    cloud_timing.log_receive("REST_AUDIO_REQUEST", client_sent_at=client_sent_at, device_id=device_id, audio_bytes=len(audio_bytes))
    try:
        resp = process_audio_chat(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            bearer_token=bearer_token,
            device_id=device_id,
            session_id=session_id,
            db=db,
        )
        duration_ms = (time.monotonic() - t0) * 1000.0
        cloud_timing.log_send("REST_AUDIO_RESPONSE", duration_ms=duration_ms, status=getattr(resp, "status", "ok"))
        return resp
    except AudioQueryExtractionError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio query extraction service is temporarily unavailable.",
        )
    except GeminiLiveError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio generation service is temporarily unavailable.",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in audio chat endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing the audio.",
        )


# ── Ingestion Endpoint ────────────────────────────────────────────────────────

@router.post(
    "/chat/audio/stream",
    summary="Submit audio query and stream TTS audio chunks to the edge device",
)
async def chat_audio_stream(
    request: Request,
    audio: UploadFile = File(...),
    device_id: str | None = Form(None),
    session_id: int | None = Form(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    """
    Accept audio from the edge device and stream generated speech as NDJSON.

    Events:
      - metadata: AudioChatResponse fields without base64 audio_response
      - audio: base64 PCM chunk, 24 kHz mono int16
      - done: final metadata
      - tts_error/error: recoverable streaming failure information
    """
    audio_bytes, mime_type = await _read_valid_audio_upload(audio)
    bearer_token = credentials.credentials if credentials else None
    _enforce_ai_quota(request, bearer_token, device_id, audio=True)
    return StreamingResponse(
        _audio_chat_stream_events(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            bearer_token=bearer_token,
            device_id=device_id,
            session_id=session_id,
            db=db,
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/ingest",
    response_model=IngestionResponse,
    summary="Ingest or re-index a document into the RAG knowledge base",
)
def ingest(
    body: IngestionRequest,
    db: Session = Depends(get_db),
    current_admin=Depends(verify_content_admin),  # CONTENT_ADMIN or SUPER_ADMIN
):
    """
    Trigger document ingestion (chunking + embedding generation).

    The document must already exist in the `uploaded_documents` table.
    Set `force_reindex=true` to regenerate embeddings for an already-indexed
    document (e.g., after its content has been updated on disk).

    Requires CONTENT_ADMIN or SUPER_ADMIN privilege.
    """
    result = ingest_document(
        document_id=body.document_id,
        db=db,
        force_reindex=body.force_reindex,
    )

    return IngestionResponse(
        document_id=result.document_id,
        chunks_created=result.chunks_created,
        embeddings_created=result.embeddings_created,
        skipped=result.skipped,
        message=result.message,
        status=result.status,
    )


# ── Gemini Live Bi-Directional Duplex WebSocket Endpoint ───────────────────────

_active_device_sessions: dict[str, Any] = {}
_device_sessions_lock = asyncio.Lock()


@router.websocket("/live/ws")
async def live_websocket_chat(
    websocket: WebSocket,
    token: str | None = None,
    device_id: str | None = None,
    session_id: int | None = None,
):
    """
    Bi-directional full-duplex WebSocket connection for real-time Gemini Live.
    Streams continuous 16kHz PCM from microphone directly into Gemini Live,
    invokes process_user_request for Fast-Path RAG, and streams 24kHz PCM audio back.
    """
    device_id = device_id or "ENTRY-A8F3D155"
    await websocket.accept()
    from app.core.database import SessionLocal
    from RagChatbot.generation.live_session_manager import GeminiLiveSession
    from RagChatbot.services.process_user_request import process_user_request

    cloud_timing.log_event("CLOUD INTERNAL", "WS_CONNECT", device_id=device_id)

    async with _device_sessions_lock:
        existing_session = _active_device_sessions.get(device_id)
        if existing_session is not None:
            logger.info("Preempting existing Gemini Live session for device %s to prevent 409 Conflict", device_id)
            try:
                await existing_session.close()
            except Exception as exc:
                logger.debug("Error closing preempted session: %s", exc)
            await asyncio.sleep(0.15)
        live_session = GeminiLiveSession()
        _active_device_sessions[device_id] = live_session

    try:
        await live_session.start()
        await websocket.send_json({
            "event": "ready",
            "data": {
                "status": "connected",
                "model": rag_settings.LIVE_MODEL,
                "input_sample_rate": rag_settings.LIVE_INPUT_SAMPLE_RATE,
                "output_sample_rate": rag_settings.LIVE_OUTPUT_SAMPLE_RATE,
                "server_sent_at": cloud_timing.now_iso(),
            }
        })
    except Exception as exc:
        logger.error("Gemini Live WebSocket connection failed to start: %s", exc)
        try:
            await websocket.send_json({"event": "error", "data": {"message": str(exc)}})
            await websocket.close()
        except Exception:
            pass
        return

    active = True
    current_turn = [""]
    turn_start_mono = [0.0]
    first_audio_sent = [False]

    async def on_transcript(transcript: str):
        if active:
            time_since_speech_end = (time.monotonic() - turn_start_mono[0]) * 1000.0 if turn_start_mono[0] > 0 else None
            cloud_timing.log_internal(
                "TRANSCRIPT",
                turn_id=current_turn[0],
                duration_ms=time_since_speech_end,
                transcript=transcript[:60],
            )
            try:
                server_ts = cloud_timing.now_iso()
                await websocket.send_json({
                    "event": "transcript",
                    "data": {
                        "text": transcript,
                        "turn_id": current_turn[0],
                        "server_sent_at": server_ts,
                    }
                })
            except Exception:
                pass

    async def on_tool_call(call: dict[str, Any]) -> dict[str, Any]:
        transcript = call.get("transcript", "")
        t_tool_start = time.monotonic()
        cloud_timing.log_internal("RAG_TOOL_CALL_START", turn_id=current_turn[0], query=transcript[:60])
        if active:
            try:
                server_ts = cloud_timing.now_iso()
                await websocket.send_json({
                    "event": "rag_status",
                    "data": {
                        "status": "searching",
                        "query": transcript,
                        "turn_id": current_turn[0],
                        "server_sent_at": server_ts,
                    }
                })
                await websocket.send_json({
                    "event": "acoustic_bridge",
                    "data": {
                        "status": "searching",
                        "phrase": "Checking university records for you...",
                        "turn_id": current_turn[0],
                        "server_sent_at": server_ts,
                    },
                })
            except Exception:
                pass

        def _run_request():
            with SessionLocal() as db:
                return process_user_request(
                    transcript=transcript,
                    bearer_token=token,
                    device_id=device_id,
                    session_id=session_id,
                    db=db,
                    fast_voice=True,
                )

        result = await asyncio.to_thread(_run_request)
        rag_dur_ms = (time.monotonic() - t_tool_start) * 1000.0
        cloud_timing.log_internal(
            "RAG_TOOL_CALL_COMPLETE",
            turn_id=current_turn[0],
            duration_ms=rag_dur_ms,
            route=result.get("route"),
            status=result.get("status"),
            citations_count=len(result.get("citations", [])),
        )
        if active:
            try:
                server_ts = cloud_timing.now_iso()
                rag_payload = {
                    "route": result.get("route"),
                    "status": result.get("status"),
                    "citations": result.get("citations", []),
                    "access_granted": result.get("access_granted", True),
                    "turn_id": current_turn[0],
                    "server_sent_at": server_ts,
                }
                nav_data = result.get("navigation")
                if nav_data:
                    if isinstance(nav_data, dict):
                        if "qr_session" not in nav_data and result.get("qr_session"):
                            nav_data["qr_session"] = result["qr_session"]
                        if "map_context" not in nav_data and result.get("map_context"):
                            nav_data["map_context"] = result["map_context"]
                        if "visualisations" not in nav_data and result.get("visualisations"):
                            nav_data["visualisations"] = result["visualisations"]
                    rag_payload["navigation"] = nav_data
                await websocket.send_json({
                    "event": "rag_complete",
                    "data": rag_payload,
                })
                if nav_data:
                    await websocket.send_json({
                        "event": "navigation",
                        "data": nav_data,
                        "turn_id": current_turn[0],
                        "server_sent_at": server_ts,
                    })
            except Exception:
                pass
        return result

    async def on_audio(pcm_bytes: bytes):
        if active and pcm_bytes:
            server_ts = cloud_timing.now_iso()
            if not first_audio_sent[0]:
                first_audio_sent[0] = True
                ttfa_cloud_ms = (time.monotonic() - turn_start_mono[0]) * 1000.0 if turn_start_mono[0] > 0 else None
                cloud_timing.log_send(
                    "FIRST_AUDIO_CHUNK",
                    turn_id=current_turn[0],
                    duration_ms=ttfa_cloud_ms,
                    audio_bytes=len(pcm_bytes),
                )
            try:
                await websocket.send_json({
                    "event": "audio",
                    "data": {
                        "encoding": "pcm_s16le",
                        "sample_rate": rag_settings.LIVE_OUTPUT_SAMPLE_RATE,
                        "chunk": base64.b64encode(pcm_bytes).decode("ascii"),
                        "turn_id": current_turn[0],
                        "server_sent_at": server_ts,
                    }
                })
            except Exception:
                pass

    async def on_output_transcript(text: str):
        if active and text:
            try:
                server_ts = cloud_timing.now_iso()
                await websocket.send_json({
                    "event": "output_transcript",
                    "data": {
                        "text": text,
                        "turn_id": current_turn[0],
                        "server_sent_at": server_ts,
                    }
                })
            except Exception:
                pass

    async def on_turn_complete():
        if active:
            total_cloud_ms = (time.monotonic() - turn_start_mono[0]) * 1000.0 if turn_start_mono[0] > 0 else None
            cloud_timing.log_send(
                "TURN_COMPLETE",
                turn_id=current_turn[0],
                duration_ms=total_cloud_ms,
            )
            try:
                server_ts = cloud_timing.now_iso()
                await websocket.send_json({
                    "event": "turn_complete",
                    "data": {
                        "turn_id": current_turn[0],
                        "server_sent_at": server_ts,
                        "cloud_duration_ms": round(total_cloud_ms, 2) if total_cloud_ms is not None else None,
                    }
                })
            except Exception:
                pass

    async def on_interrupted():
        if active:
            cloud_timing.log_receive("INTERRUPTED", turn_id=current_turn[0])
            try:
                await websocket.send_json({
                    "event": "interrupted",
                    "turn_id": current_turn[0],
                    "server_sent_at": cloud_timing.now_iso(),
                })
            except Exception:
                pass

    receiver_task = asyncio.create_task(
        live_session.receive_events(
            on_audio=on_audio,
            on_transcript=on_transcript,
            on_tool_call=on_tool_call,
            on_output_transcript=on_output_transcript,
            on_turn_complete=on_turn_complete,
            on_interrupted=on_interrupted,
        ),
        name="gemini-live-ws-receiver",
    )

    # Resolve user name for Gemini Live greeting if token or session is provided
    resolved_name: str | None = None
    if token:
        try:
            with SessionLocal() as db:
                auth_ctx = resolve_auth_context(token, db)
                if auth_ctx and auth_ctx.authenticated:
                    resolved_name = auth_ctx.given_name or auth_ctx.full_name
        except Exception as exc:
            logger.debug("Could not resolve user context for live greeting: %s", exc)

    # Greeting is triggered primarily when the client sends the explicit 'greet' event.
    # A fallback task triggers it after 1.5s only if no greet event is received from the client.
    greeting_scheduled = False

    async def _fallback_greeting():
        nonlocal greeting_scheduled
        await asyncio.sleep(1.5)
        if not greeting_scheduled and active and (session_id or token):
            greeting_scheduled = True
            await live_session.trigger_greeting(user_name=resolved_name)

    fallback_greeting_task = asyncio.create_task(_fallback_greeting(), name="live-fallback-greeting")

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                await live_session.send_audio(message["bytes"])
            elif "text" in message and message["text"]:
                try:
                    payload = json.loads(message["text"])
                    event = payload.get("event")
                    if event == "audio_chunk":
                        b64_data = payload.get("data", {}).get("chunk")
                        if b64_data:
                            await live_session.send_audio(base64.b64decode(b64_data))
                    elif event == "greet":
                        greeting_scheduled = True
                        client_name = payload.get("data", {}).get("user_name") or resolved_name
                        asyncio.create_task(live_session.trigger_greeting(user_name=client_name))
                    elif event in ("activity_end", "finish_turn"):
                        turn_data = payload.get("data") or {}
                        turn_id = turn_data.get("turn_id") or f"turn_{int(time.time()*1000)}"
                        client_sent_at = turn_data.get("client_sent_at")
                        speech_dur_ms = turn_data.get("speech_duration_ms")
                        audio_bytes = turn_data.get("total_audio_bytes")

                        current_turn[0] = turn_id
                        turn_start_mono[0] = time.monotonic()
                        first_audio_sent[0] = False

                        cloud_timing.log_receive(
                            "ACTIVITY_END",
                            turn_id=turn_id,
                            client_sent_at=client_sent_at,
                            speech_duration_ms=speech_dur_ms,
                            audio_bytes=audio_bytes,
                        )
                        await live_session.end_user_turn()
                    elif event in ("client_barge_in", "interrupt"):
                        cloud_timing.log_receive("BARGE_IN", turn_id=current_turn[0])
                        await live_session.cancel_input()
                except json.JSONDecodeError:
                    pass
    except WebSocketDisconnect:
        logger.info("Gemini Live client disconnected normally.")
    except Exception as exc:
        logger.warning("Gemini Live WebSocket session ended: %s", exc)
    finally:
        active = False
        fallback_greeting_task.cancel()
        receiver_task.cancel()
        cloud_timing.log_event("CLOUD INTERNAL", "WS_DISCONNECT", device_id=device_id)
        async with _device_sessions_lock:
            if _active_device_sessions.get(device_id) is live_session:
                _active_device_sessions.pop(device_id, None)
        try:
            await live_session.close()
        except Exception:
            pass

