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

import base64
import datetime
import json
import logging
from collections import OrderedDict
from collections.abc import Iterator
from threading import Lock

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import iterate_in_threadpool
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_content_admin
from RagChatbot.config import rag_settings
from RagChatbot.generation.audio_query_extractor import AudioQueryExtractionError
from RagChatbot.generation.gemini_live_service import GeminiLiveError
from RagChatbot.generation.response_validator import generate_audio_from_text_stream
from RagChatbot.generation.response_validator import generate_audio_from_text
from RagChatbot.schemas import (
    AudioChatResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    IngestionRequest,
    IngestionResponse,
)
from RagChatbot.services.audio_chat_service import process_audio_chat, process_audio_chat_stream
from RagChatbot.services.greeting_audio_service import generate_greeting_audio
from RagChatbot.services.chat_service import process_chat, process_public_smoke_chat
from RagChatbot.services.ingestion_service import ingest_document
from RagChatbot.security.auth_context import resolve_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatbot", tags=["RAG Chatbot"])

# Optional bearer scheme. Missing tokens use visitor/PUBLIC access.
_bearer_scheme = HTTPBearer(auto_error=False)


_GREETING_AUDIO_CACHE: OrderedDict[str, str] = OrderedDict()
_GREETING_AUDIO_CACHE_LOCK = Lock()
_GREETING_AUDIO_CACHE_SIZE = 128


def _greeting_text(full_name: str | None, given_name: str | None = None) -> str:
    # Use the database's given_name field so names such as "Nur Aisyah" are
    # not truncated to the first whitespace-delimited token.
    display_name = " ".join((given_name or "").split())
    if not display_name and full_name:
        display_name = full_name.strip().split()[0] if full_name.strip() else ""
    return f"Hi {display_name}, how may I help you today?" if display_name else "Hi, how may I help you today?"


def _cached_greeting_audio(text: str, given_name: str | None = None) -> str | None:
    """Return cached greeting audio, synthesizing each unique greeting once."""
    with _GREETING_AUDIO_CACHE_LOCK:
        cached = _GREETING_AUDIO_CACHE.get(text)
        if cached is not None:
            _GREETING_AUDIO_CACHE.move_to_end(text)
            return cached
    try:
        audio = generate_greeting_audio(text, given_name=given_name)
    except Exception:
        logger.warning("Greeting TTS failed; returning text greeting only.", exc_info=True)
        return None
    if not audio:
        return None
    encoded = base64.b64encode(audio).decode("ascii")
    with _GREETING_AUDIO_CACHE_LOCK:
        _GREETING_AUDIO_CACHE[text] = encoded
        _GREETING_AUDIO_CACHE.move_to_end(text)
        while len(_GREETING_AUDIO_CACHE) > _GREETING_AUDIO_CACHE_SIZE:
            _GREETING_AUDIO_CACHE.popitem(last=False)
    return encoded


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


from typing import AsyncIterator

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
    db: Session = Depends(get_db),
):
    """
    No-JWT RAG smoke test for edge-device diagnostics.

    Disabled unless `RAG_ENABLE_PUBLIC_SMOKE_TEST=1` is set on the cloud
    backend. When enabled, retrieval is limited to PUBLIC documents only.
    """
    _require_public_smoke_test_enabled()
    return process_public_smoke_chat(request=body, db=db)


@router.post(
    "/chat/public-smoke-test/stream",
    summary="Submit a public-only RAG smoke-test query and stream chunks without JWT",
)
def public_smoke_chat_stream(
    body: ChatRequest,
    db: Session = Depends(get_db),
):
    """
    Streaming no-JWT RAG smoke test for edge audio playback diagnostics.

    Disabled unless `RAG_ENABLE_PUBLIC_SMOKE_TEST=1` is set on the cloud
    backend. When enabled, retrieval is limited to PUBLIC documents only.
    """
    _require_public_smoke_test_enabled()
    response = process_public_smoke_chat(request=body, db=db)
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
    return process_chat(request=body, bearer_token=bearer_token, db=db)


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


@router.post(
    "/chat/stream",
    summary="Submit a user query and stream response chunks",
)
def chat_stream(
    body: ChatRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
):
    """
    Streaming chatbot endpoint for edge audio playback.

    The existing RAG pipeline still performs RBAC filtering, answer generation,
    citation building, and audit logging for authenticated sessions. Without a
    JWT, it uses visitor/PUBLIC access. The final answer is emitted as
    Server-Sent Events so the edge device can synthesize speech in
    sentence-sized chunks.
    """
    bearer_token = credentials.credentials if credentials else None
    response = process_chat(request=body, bearer_token=bearer_token, db=db)
    return StreamingResponse(
        _chat_response_events(response),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Audio Chat Endpoint ──────────────────────────────────────────────────────

@router.post(
    "/chat/audio",
    response_model=AudioChatResponse,
    summary="Submit audio query from edge device to the RAG chatbot",
)
async def chat_audio(
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
            detail=f"Expected an audio file, got {audio.content_type}.",
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
                f"Audio file exceeds the maximum allowed size of "
                f"{rag_settings.AUDIO_MAX_UPLOAD_BYTES} bytes."
            ),
        )

    # ── Determine MIME type ───────────────────────────────────────────
    mime_type = audio.content_type or "audio/wav"

    # ── Extract bearer token ──────────────────────────────────────────
    bearer_token = credentials.credentials if credentials else None

    # ── Call audio RAG pipeline ───────────────────────────────────────
    try:
        return process_audio_chat(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            bearer_token=bearer_token,
            device_id=device_id,
            session_id=session_id,
            db=db,
        )
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

    if result.chunks_created == 0 and result.skipped == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.message,
        )

    return IngestionResponse(
        document_id=result.document_id,
        chunks_created=result.chunks_created,
        embeddings_created=result.embeddings_created,
        skipped=result.skipped,
        message=result.message,
    )
