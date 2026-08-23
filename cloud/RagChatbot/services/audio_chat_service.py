"""
Orchestrate the full two-step Gemini audio RAG pipeline.

Receives raw audio bytes from the edge device and runs the complete
pipeline: audio transcription/query extraction using ``AUDIO_EXTRACTION_MODEL``
(``gemini-3.1-flash-lite``), prompt-injection guard, embedding with
``EMBEDDING_MODEL``, RBAC-resolved retrieval, final text response generation
using ``LLM_MODEL`` (``gemini-3.1-flash-lite``), TTS using
``AUDIO_TTS_MODEL``, response validation gate, and audit logging.

Returns an ``AudioChatResponse`` with the cloud transcription, optional text,
and optional base64-encoded audio output.

Security invariants maintained by this module:
- JWT verification runs before any audio is sent to Gemini.
- RBAC access levels are resolved from the DB (not from the request body).
- Prompt-injection detection runs on the extracted text query before
  retrieval (reuses the existing ``check_query`` guard).
- The ``possible_prompt_injection`` flag from the extraction step provides
  defence-in-depth before ``check_query``.
- The final Gemini prompt separates trusted sections (system instruction,
  authenticated user role, authorised retrieved context) from the
  untrusted extracted query.
- Audio is never returned unless the text response and cited sources pass
  validation (validation gate invariant).
"""

from __future__ import annotations

import base64
import concurrent.futures
import logging
import time
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from RagChatbot.config import rag_settings
from RagChatbot.embeddings.google_embedding_service import embed_text
from RagChatbot.generation.audio_query_extractor import (
    AudioQueryExtractionError,
    extract_query_from_audio,
)
from RagChatbot.generation.gemini_live_service import (
    GeminiLiveError,
)
from RagChatbot.generation.google_llm_service import generate_answer, generate_answer_stream
from RagChatbot.generation.sentence_splitter import StreamingSentenceSplitter
from RagChatbot.generation.response_validator import (
    ValidationResult,
    generate_audio_from_text,
    validate_response,
    validate_sentence,
)
from RagChatbot.generation.query_router import classify_query, get_capabilities_summary
from RagChatbot.retrieval.retriever import retrieve_chunks
from RagChatbot.schemas import AudioChatResponse, CitationSchema
from RagChatbot.security.audit_logger import log_access_denied, log_chatbot_interaction, log_personal_interaction
from RagChatbot.security.prompt_guard import check_query
from RagChatbot.security.rbac import get_allowed_access_levels_for_user
from RagChatbot.security.auth_context import resolve_auth_context
from RagChatbot.generation import llm_planner
from RagChatbot.personalisation.intents import parse_personal_intent
from RagChatbot.personalisation.schemas import PersonalIntent
from RagChatbot.personalisation.service import handle_personal_request
from RagChatbot.logging.inference_logger import InferenceMetrics, StageTimer, log_inference_metrics
from RagChatbot.services.chat_service import (
    AUTH_REQUIRED_ANSWER,
    AUTH_REQUIRED_STATUS,
    PROTECTED_ACCESS_LEVELS,
    VISITOR_ACCESS_LEVELS,
    _confirmed_navigation_label,
    _greeting_name,
    _navigation_intent,
    _verify_session,
)

logger = logging.getLogger(__name__)
_TTS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(1, int(getattr(rag_settings, "AUDIO_TTS_WORKERS", 2))),
    thread_name_prefix="rag-audio-tts",
)

def _safe_query_id(val: Any) -> Optional[int]:
    if isinstance(val, int) and val > 0:
        return val
    return None

def _tts_base64(text: str, language_code: Optional[str] = None) -> Optional[str]:
    """Generate base64 PCM audio for safe response text."""
    if not rag_settings.AUDIO_TTS_ENABLED or not text.strip():
        return None
    timeout_seconds = max(0.0, float(getattr(rag_settings, "AUDIO_TTS_TIMEOUT_SECONDS", 6)))
    use_language = bool(language_code and str(language_code).lower() not in {"en", "en-us"})
    tts_args = (text, language_code) if use_language else (text,)
    try:
        if timeout_seconds:
            future = _TTS_EXECUTOR.submit(generate_audio_from_text, *tts_args)
            try:
                audio_pcm = future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                future.cancel()
                logger.warning(
                    "Audio chat: TTS timed out after %.1fs, returning text only.",
                    timeout_seconds,
                )
                return None
        else:
            audio_pcm = generate_audio_from_text(*tts_args)
    except Exception as exc:
        logger.warning("Audio chat: TTS failed, returning text only: %s", exc)
        return None
    if audio_pcm is None:
        return None
    audio_base64 = base64.b64encode(audio_pcm).decode("ascii")
    logger.info(
        "Audio chat: TTS payload ready. pcm_bytes=%d base64_chars=%d",
        len(audio_pcm),
        len(audio_base64),
    )
    return audio_base64


def _tts_job(text: str, language_code: Optional[str] = None) -> tuple[Optional[bytes], float, Optional[str]]:
    """Run one synthesis request off the response-generation path."""
    started = time.monotonic()
    try:
        if language_code and str(language_code).lower() not in {"en", "en-us"}:
            audio = generate_audio_from_text(text, language_code)
        else:
            audio = generate_audio_from_text(text)
        return audio, (time.monotonic() - started) * 1000.0, None
    except Exception as exc:  # TTS is best-effort; text must still complete.
        return None, (time.monotonic() - started) * 1000.0, str(exc)


def _drain_tts_queue(pending: list[tuple[str, concurrent.futures.Future]], metrics: InferenceMetrics,
                    start_time: float, *, wait: bool = False):
    """Yield ready audio in sentence order without blocking the LLM stream."""
    timeout = max(0.0, float(getattr(rag_settings, "AUDIO_TTS_TIMEOUT_SECONDS", 6)))
    while pending:
        sentence, future = pending[0]
        if not wait and not future.done():
            break
        try:
            audio_pcm, elapsed_ms, error = future.result(timeout=timeout or None)
        except concurrent.futures.TimeoutError:
            future.cancel()
            audio_pcm, elapsed_ms, error = None, timeout * 1000.0, "timeout"
        except Exception as exc:
            audio_pcm, elapsed_ms, error = None, 0.0, str(exc)
        pending.pop(0)
        metrics.tts_ms += elapsed_ms
        if audio_pcm:
            if metrics.time_to_first_tts_ms == 0.0:
                metrics.time_to_first_tts_ms = (time.monotonic() - start_time) * 1000.0
            yield {
                "event": "audio",
                "data": {
                    "encoding": "pcm_s16le",
                    "sample_rate": rag_settings.LIVE_OUTPUT_SAMPLE_RATE,
                    "chunk": base64.b64encode(audio_pcm).decode("ascii"),
                    "text": sentence,
                },
            }
        elif error:
            logger.warning("Audio chat: TTS failed for sentence: %s", error)
            yield {"event": "tts_error", "data": {"text": sentence, "message": "Speech synthesis unavailable."}}


def _audio_response(
    *,
    transcribed_input: Optional[str],
    text_response: Optional[str],
    sources: Optional[List[CitationSchema]] = None,
    status: str,
    access_granted: bool,
    start_time: float,
    error_message: Optional[str] = None,
    query_id: Optional[int] = None,
    include_audio: bool = True,
    response_scope: str = "DOCUMENT",
    personal_intent: Optional[str] = None,
    authentication_required: bool = False,
    navigation_target: Optional[dict] = None,
    navigation: Optional[dict] = None,
    route_summary: Optional[dict] = None,
    instructions: Optional[list[dict]] = None,
    visualisation: Optional[dict] = None,
    intent: Optional[str] = None,
    metrics: Optional[InferenceMetrics] = None,
    user_id: Optional[int] = None,
    session_id: Optional[int] = None,
    language_code: Optional[str] = None,
) -> AudioChatResponse:
    """Build the audio API response with consistent transcription and TTS fields."""
    if metrics is None:
        metrics = InferenceMetrics()

    audio_data = None
    if include_audio and text_response:
        with StageTimer() as timer:
            audio_data = _tts_base64(text_response or "", language_code)
        metrics.tts_ms += timer.elapsed_ms
        if audio_data and metrics.time_to_first_tts_ms == 0.0:
            metrics.time_to_first_tts_ms = (time.monotonic() - start_time) * 1000.0

    metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
    log_inference_metrics(
        request_type="audio",
        user_id=user_id,
        session_id=session_id,
        query_text=transcribed_input,
        metrics=metrics,
        status=status,
    )

    return AudioChatResponse(
        transcribed_input=transcribed_input,
        text_response=text_response,
        audio_response=audio_data,
        sources=sources or [],
        status=status,
        access_granted=access_granted,
        error_message=error_message,
        response_time_ms=int((time.monotonic() - start_time) * 1000),
        query_id=query_id,
        response_scope=response_scope,
        personal_intent=personal_intent,
        authentication_required=authentication_required,
        navigation_target=navigation_target,
        intent=intent,
        navigation=navigation,
        route_summary=route_summary,
        instructions=instructions or [],
        visualisation=visualisation,
    )


def process_audio_chat(
    audio_bytes: bytes,
    mime_type: str,
    bearer_token: Optional[str],
    device_id: Optional[str],
    session_id: Optional[int],
    db: Session,
    include_audio: bool = True,
) -> AudioChatResponse:
    """
    Execute the full audio RAG pipeline.

    Pipeline steps:

    1. Verify JWT -> resolve user_id and session_id
    2. Resolve RBAC access levels from DB (or PUBLIC for anonymous)
    3. Send audio to Gemini for structured query extraction
    4. Run prompt-injection detection on extracted query
    5. If blocked -> return status:"blocked" with safe response, NO retrieval
    6. Embed the extracted query
    7. Retrieve authorised document chunks (RBAC-filtered)
    8. Build separated prompt with trust boundaries
    9. Generate text response via Gemini 3.1 Lite
    10. Validate text response and sources
    11. Convert validated text response to speech with Gemini TTS when requested
    12. Build CitationSchema objects
    13. Audit log the interaction
    14. Return AudioChatResponse

    Args:
        audio_bytes: Raw audio data from the edge device.
        mime_type: MIME type of the audio data (e.g. ``audio/wav``).
        bearer_token: The raw JWT from the Authorization header, or None.
        device_id: Edge device identifier (for audit logging).
        session_id: Existing session ID hint from the request body.
        db: Active SQLAlchemy session.

    Returns:
        AudioChatResponse with text and/or audio, sources, and status.
    """
    start_time = time.monotonic()
    metrics = InferenceMetrics()

# Step 1: Verify JWT
    user_id: Optional[int] = None
    resolved_session_id: Optional[int] = None
    context = None

    if bearer_token:
        try:
            context = resolve_auth_context(
                bearer_token,
                db,
                requested_device_id=device_id,
            )
            user_id, resolved_session_id = context.user_id, context.session_id
        except HTTPException as exc:
            if exc.status_code == 403:
                raise
# Token invalid or expired; return auth_required
            # so the edge device can prompt the user to re-authenticate.
            logger.warning("Audio chat: invalid/expired JWT, returning auth_required.")
            return _audio_response(
                transcribed_input=None,
                text_response=AUTH_REQUIRED_ANSWER,
                status="auth_required",
                access_granted=False,
                error_message=AUTH_REQUIRED_STATUS,
                start_time=start_time,
                include_audio=include_audio,
                metrics=metrics,
                user_id=user_id,
                session_id=resolved_session_id,
                language_code=None,
            )

# Step 2: Resolve RBAC access levels
    if user_id is not None:
        allowed_levels = get_allowed_access_levels_for_user(user_id, db)
        logger.info("Audio chat: user_id=%d allowed_levels=%s", user_id, allowed_levels)
    else:
        allowed_levels = VISITOR_ACCESS_LEVELS
        logger.info("Audio chat: anonymous visitor allowed_levels=%s", allowed_levels)

# Step 3: Extract query from audio
    try:
        with StageTimer() as timer:
            extraction_result = extract_query_from_audio(
                audio_bytes=audio_bytes,
                mime_type=mime_type,
            )
        metrics.prompt_injection_ms += timer.elapsed_ms
    except AudioQueryExtractionError as exc:
        logger.error("Audio chat: query extraction failed: %s", exc)
        return _audio_response(
            transcribed_input=None,
            text_response=None,
            status="error",
            access_granted=False,
            error_message="Could not process the audio. Please try speaking clearly and try again.",
            start_time=start_time,
            include_audio=include_audio,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
        )

# Step 3b: Check audio extraction prompt-injection flag
    if extraction_result.possible_prompt_injection:
        logger.warning(
            "Audio query extraction flagged possible injection: %s",
            extraction_result.unsafe_instruction_summary,
        )
        return _audio_response(
            transcribed_input=extraction_result.user_query,
            text_response=(
                "I'm not able to process that request. "
                "Please ask a straightforward question about campus services or documents."
            ),
            status="blocked",
            access_granted=False,
            error_message=(
                "Your request could not be processed as it contained "
                "potentially unsafe instructions."
            ),
            start_time=start_time,
            include_audio=include_audio,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
        )

    user_query = extraction_result.user_query
    detected_language = extraction_result.detected_language or "en"
    if not user_query:
        logger.warning("Audio chat: extracted query is empty.")
        return _audio_response(
            transcribed_input="",
            text_response=None,
            status="error",
            access_granted=False,
            error_message="No speech detected. Please try speaking clearly and try again.",
            start_time=start_time,
            include_audio=include_audio,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
        )

# Step 4: Prompt-injection detection on extracted query
    with StageTimer() as timer:
        guard_result = check_query(user_query)
    metrics.prompt_injection_ms += timer.elapsed_ms

    if not guard_result.is_safe:
        logger.warning(
            "Audio chat: prompt injection blocked. pattern=%s",
            guard_result.matched_pattern,
        )

        # Audit log the blocked request (if session is available)
        if resolved_session_id is not None and resolved_session_id > 0:
            log_access_denied(
                db,
                session_id=resolved_session_id,
                user_id=user_id,
                query_text=user_query,
                reason=f"prompt_injection:{guard_result.matched_pattern}",
            )

        return _audio_response(
            transcribed_input=user_query,
            text_response=(
                "I'm not able to process that request. "
                "Please ask a straightforward question about campus services or documents."
            ),
            status="blocked",
            access_granted=False,
            start_time=start_time,
            include_audio=include_audio,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
        )

    sanitized_query = guard_result.sanitized_query or user_query

    # Text, uploaded audio, and streamed audio all use the same structured
    # planner.  Keep the original recognized transcript for the response while
    # passing only the guarded text to the planner.
    context = context or resolve_auth_context(bearer_token, db, requested_device_id=device_id)
    confirmation_context = _confirmed_navigation_label(sanitized_query, db, resolved_session_id)
    personal_intent_result = parse_personal_intent(sanitized_query)
    lang = detected_language or detect_query_language(sanitized_query)
    is_non_english = bool(lang and not lang.startswith("en"))

    with StageTimer() as timer:
        route = classify_query(sanitized_query, db=db)
    metrics.prompt_classification_ms += timer.elapsed_ms

    needs_planner = (
        confirmation_context is not None
        or personal_intent_result.intent != PersonalIntent.UNKNOWN
        or route.category in ("NAVIGATIONAL", "UNCLEAR")
        or (is_non_english and context.authenticated)
        or route.category in ("GREETING", "CAPABILITY", "OUT_OF_SCOPE")
    )

    if not needs_planner:
        planned = llm_planner.PlannedOperation(kind="rag", query=sanitized_query)
    else:
        if route.category == "GREETING":
            name = _greeting_name(context) if context.authenticated else ""
            answer = f"Hi {name}, how may I help you today?" if name else "Hi, how may I help you today?"
            planned = llm_planner.PlannedOperation(kind="fixed", answer=answer, intent="GREETING")
        elif route.category == "CAPABILITY":
            answer = get_capabilities_translated(
                authenticated=context.authenticated,
                personalisation_enabled=rag_settings.RAG_PERSONALISATION_ENABLED,
                lang=lang,
            )
            planned = llm_planner.PlannedOperation(kind="fixed", answer=answer, intent="CAPABILITY")
        elif route.category == "OUT_OF_SCOPE":
            answer = get_translated("out_of_scope", lang)
            planned = llm_planner.PlannedOperation(
                kind="blocked",
                answer=answer,
                status="blocked",
                access_granted=False,
                status_message=get_translated("out_of_scope_status", lang),
                intent="OUT_OF_SCOPE",
            )
        else:
            with StageTimer() as timer:
                planned = llm_planner.execute_planned_turn(
                    sanitized_query,
                    context=context,
                    db=db,
                    confirmation_context=confirmation_context,
                )
            metrics.prompt_classification_ms += timer.elapsed_ms

    if planned.kind != "rag":
        context = context or resolve_auth_context(bearer_token, db, requested_device_id=device_id)
        query_id = None
        response_time_ms = int((time.monotonic() - start_time) * 1000)
        if planned.kind == "personal":
            logged_query_id = log_personal_interaction(
                db,
                session_id=resolved_session_id,
                user_id=user_id or 0,
                intent=planned.intent or "UNKNOWN",
                response_time_ms=response_time_ms,
                is_navigational=bool(planned.navigation),
            )
        else:
            logged_query_id = log_chatbot_interaction(
                db,
                session_id=resolved_session_id,
                user_id=user_id,
                query_text=sanitized_query,
                response_text=planned.answer or "",
                retrieved_chunk_ids=[],
                response_time_ms=response_time_ms,
                is_navigational=planned.kind == "navigation",
            )
        query_id = _safe_query_id(logged_query_id)
        navigation_data = planned.navigation
        return _audio_response(
            transcribed_input=user_query,
            text_response=planned.answer or "",
            status=planned.status,
            access_granted=planned.access_granted,
            error_message=planned.status_message,
            start_time=start_time,
            query_id=query_id,
            include_audio=include_audio,
            response_scope=planned.response_scope,
            personal_intent=planned.intent if planned.kind == "personal" else None,
            authentication_required=planned.authentication_required,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
            language_code=detected_language,
            intent=planned.intent,
            navigation_target=(navigation_data or {}).get("navigation_target"),
            navigation=(navigation_data or {}).get("navigation"),
            route_summary=(navigation_data or {}).get("route_summary"),
            instructions=(navigation_data or {}).get("instructions", []),
            visualisation=(navigation_data or {}).get("visualisation"),
        )

# Step 6: Embed the extracted query
    with StageTimer() as timer:
        try:
            query_embedding = embed_text(sanitized_query)
        except RuntimeError as exc:
            logger.error("Audio chat: embedding failed for user_id=%s: %s", user_id, exc)
            return _audio_response(
                transcribed_input=user_query,
                text_response=None,
                status="error",
                access_granted=False,
                error_message=get_translated("search_unavailable", lang),
                start_time=start_time,
                include_audio=include_audio,
                metrics=metrics,
                user_id=user_id,
                session_id=resolved_session_id,
                language_code=detected_language,
            )
    metrics.embedding_return_ms += timer.elapsed_ms

# Step 7: Retrieve authorized document chunks
    with StageTimer() as timer:
        ranked_chunks = retrieve_chunks(
            query_embedding=query_embedding,
            allowed_access_levels=allowed_levels,
            db=db,
            query_text=sanitized_query,
        )
    metrics.embedding_db_search_ms += timer.elapsed_ms

# Check whether authentication upgrade could help
    if not ranked_chunks:
        if not bearer_token and _has_relevant_protected_chunks(query_embedding, db):
            # Anonymous user but there are protected chunks that match
            return _audio_response(
                transcribed_input=user_query,
                text_response=get_translated("auth_required", lang),
                status="auth_required",
                access_granted=False,
                start_time=start_time,
                include_audio=include_audio,
                metrics=metrics,
                user_id=user_id,
                session_id=resolved_session_id,
                language_code=detected_language,
            )
        else:
            # No relevant chunks at all
            return _audio_response(
                transcribed_input=user_query,
                text_response=get_translated("no_access", lang),
                status="no_access",
                access_granted=False,
                start_time=start_time,
                include_audio=include_audio,
                metrics=metrics,
                user_id=user_id,
                session_id=resolved_session_id,
                language_code=detected_language,
            )

# Step 9: Generate text response using the same pipeline as text chat
    with StageTimer() as timer:
        try:
            answer_text = generate_answer(
                sanitized_query,
                ranked_chunks,
                chat_history=_recent_chat_history(db, resolved_session_id),
                user_context=context,
            )
        except RuntimeError as exc:
            logger.error("Audio chat: generation failed for user_id=%s: %s", user_id, exc)
            return _audio_response(
                transcribed_input=user_query,
                text_response=None,
                status="error",
                access_granted=False,
                error_message="The answer service is temporarily unavailable. Please try again later.",
                start_time=start_time,
                include_audio=include_audio,
                metrics=metrics,
                user_id=user_id,
                session_id=resolved_session_id,
            )
    metrics.rag_ms += timer.elapsed_ms

# Step 10: Validate text response and sources
    validation: ValidationResult = validate_response(
        text=answer_text,
        sources=ranked_chunks,
        original_query=sanitized_query,
    )

    if not validation.valid:
        logger.warning(
            "Audio chat: response validation failed: %s", validation.reason
        )
        # If validation failed, sanitize the text and regenerate audio
        if validation.sanitized_text:
            answer_text = validation.sanitized_text

# Do not include audio when validation has failed
        # may contain sanitised/redacted text that should not be spoken.
        # Return with validation_failed status so the edge device knows
        # the response went through extra sanitisation
        status_str = "validation_failed"
        include_response_audio = False
    else:
        status_str = "ok"
        include_response_audio = include_audio

# Step 12: Build CitationSchema objects
    citations: List[CitationSchema] = [
        CitationSchema(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_title=chunk.document_title,
            chunk_index=chunk.chunk_index,
            access_level=chunk.access_level,
            excerpt=chunk.chunk_text[:200],
            chunk_type=getattr(chunk, "chunk_type", "DETAIL"),
            section_path=getattr(chunk, "section_path", None),
            entity_tags=getattr(chunk, "entity_tags", []),
        )
        for chunk in ranked_chunks
    ]

    response_time_ms = int(metrics.time_to_first_tts_ms) if metrics.time_to_first_tts_ms > 0 else int((time.monotonic() - start_time) * 1000)

# Step 13: Audit log
    logged_id = log_chatbot_interaction(
        db,
        session_id=resolved_session_id,
        user_id=user_id,
        query_text=sanitized_query,
        response_text=answer_text,
        retrieved_chunk_ids=[c.chunk_id for c in ranked_chunks],
        response_time_ms=response_time_ms,
    )
    audit_query_id: Optional[int] = _safe_query_id(logged_id)

# Step 14: Return AudioChatResponse
    return _audio_response(
        transcribed_input=user_query,
        text_response=answer_text,
        sources=citations,
        status=status_str,
        access_granted=True,
        start_time=start_time,
        query_id=audit_query_id,
        include_audio=include_response_audio,
        metrics=metrics,
        user_id=user_id,
        session_id=resolved_session_id,
        language_code=detected_language,
    )


def _has_relevant_protected_chunks(
    query_embedding: List[float], db: Session
) -> bool:
    """Return True when protected chunks match an anonymous visitor query."""
    protected_chunks = retrieve_chunks(
        query_embedding=query_embedding,
        allowed_access_levels=PROTECTED_ACCESS_LEVELS,
        db=db,
        top_k_retrieval=3,
        top_k_context=1,
    )
    return bool(protected_chunks)


def _recent_chat_history(db: Session, session_id: Optional[int]) -> list[dict]:
    if not session_id:
        return []
    try:
        from app.models.models import ChatbotQuery
        rows = (
            db.query(ChatbotQuery)
            .filter(ChatbotQuery.session_id == session_id)
            .filter(ChatbotQuery.response_text.isnot(None))
            .order_by(ChatbotQuery.timestamp.desc())
            .limit(3)
            .all()
        )
        history: list[dict] = []
        for row in reversed(rows):
            history.append({
                "user": row.query_text or "",
                "assistant": row.response_text or "",
            })
        return history
    except Exception:
        logger.debug("Audio chat: unable to load recent conversation history", exc_info=True)
        return []


def process_audio_chat_stream(
    audio_bytes: bytes,
    mime_type: str,
    bearer_token: Optional[str],
    device_id: Optional[str],
    session_id: Optional[int],
    db: Session,
):
    """
    Execute the audio RAG pipeline in sentence-by-sentence streaming mode.

    Yields stream dictionary events:
      - {"event": "metadata", "data": response_payload}
      - {"event": "audio", "data": {"chunk": b64_pcm, "text": sentence_text}}
      - {"event": "done", "data": final_response_payload}
    """
    start_time = time.monotonic()
    metrics = InferenceMetrics()

    user_id: Optional[int] = None
    resolved_session_id: Optional[int] = None
    context = None

    if bearer_token:
        try:
            context = resolve_auth_context(
                bearer_token,
                db,
                requested_device_id=device_id,
            )
            user_id, resolved_session_id = context.user_id, context.session_id
        except HTTPException as exc:
            if exc.status_code == 403:
                raise
            logger.warning("Audio chat stream: invalid/expired JWT.")
            res = _audio_response(
                transcribed_input=None,
                text_response=AUTH_REQUIRED_ANSWER,
                status="auth_required",
                access_granted=False,
                error_message=AUTH_REQUIRED_STATUS,
                start_time=start_time,
                include_audio=False,
                metrics=metrics,
                user_id=user_id,
                session_id=resolved_session_id,
            )
            yield {"event": "metadata", "data": res.model_dump(mode="json", exclude={"audio_response"})}
            yield {"event": "done", "data": res.model_dump(mode="json", exclude={"audio_response"})}
            return

    if user_id is not None:
        allowed_levels = get_allowed_access_levels_for_user(user_id, db)
    else:
        allowed_levels = VISITOR_ACCESS_LEVELS

    # Extract audio
    extraction_result = extract_query_from_audio(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
    )

    if extraction_result.possible_prompt_injection or not extraction_result.user_query:
        msg = (
            "I'm not able to process that request."
            if extraction_result.possible_prompt_injection
            else "No speech detected."
        )
        status_str = "blocked" if extraction_result.possible_prompt_injection else "error"
        res = _audio_response(
            transcribed_input=extraction_result.user_query,
            text_response=msg,
            status=status_str,
            access_granted=False,
            error_message=msg,
            start_time=start_time,
            include_audio=False,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
        )
        yield {"event": "metadata", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        yield {"event": "done", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        return

    user_query = extraction_result.user_query
    detected_language = extraction_result.detected_language or "en"
    guard_result = check_query(user_query)
    if not guard_result.is_safe:
        res = _audio_response(
            transcribed_input=user_query,
            text_response="I'm not able to process that request.",
            status="blocked",
            access_granted=False,
            start_time=start_time,
            include_audio=False,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
        )
        yield {"event": "metadata", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        yield {"event": "done", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        return

    sanitized_query = guard_result.sanitized_query or user_query
    yield {"event": "transcript", "data": {"transcribed_input": user_query}}
    context = context or resolve_auth_context(
        bearer_token,
        db,
        requested_device_id=device_id,
    )
    confirmation_context = _confirmed_navigation_label(sanitized_query, db, resolved_session_id)
    personal_intent_result = parse_personal_intent(sanitized_query)
    lang = detected_language or detect_query_language(sanitized_query)
    is_non_english = bool(lang and not lang.startswith("en"))

    with StageTimer() as timer:
        route = classify_query(sanitized_query, db=db)
    metrics.prompt_classification_ms += timer.elapsed_ms

    needs_planner = (
        confirmation_context is not None
        or personal_intent_result.intent != PersonalIntent.UNKNOWN
        or route.category in ("NAVIGATIONAL", "UNCLEAR")
        or (is_non_english and context.authenticated)
    )

    if not needs_planner:
        if route.category == "GREETING":
            name = _greeting_name(context) if context.authenticated else ""
            answer = f"Hi {name}, how may I help you today?" if name else "Hi, how may I help you today?"
            planned = llm_planner.PlannedOperation(kind="fixed", answer=answer, intent="GREETING")
        elif route.category == "CAPABILITY":
            answer = get_capabilities_translated(
                authenticated=context.authenticated,
                personalisation_enabled=rag_settings.RAG_PERSONALISATION_ENABLED,
                lang=lang,
            )
            planned = llm_planner.PlannedOperation(kind="fixed", answer=answer, intent="CAPABILITY")
        elif route.category == "OUT_OF_SCOPE":
            answer = get_translated("out_of_scope", lang)
            planned = llm_planner.PlannedOperation(
                kind="blocked",
                answer=answer,
                status="blocked",
                access_granted=False,
                status_message=get_translated("out_of_scope_status", lang),
                intent="OUT_OF_SCOPE",
            )
        else:
            planned = llm_planner.PlannedOperation(kind="rag", query=sanitized_query)
    else:
        with StageTimer() as timer:
            planned = llm_planner.execute_planned_turn(
                sanitized_query,
                context=context,
                db=db,
                confirmation_context=confirmation_context,
            )
        metrics.prompt_classification_ms += timer.elapsed_ms

    if planned.kind != "rag":
        # Preserve the deterministic handler seam for legacy callers that
        # provide an authenticated test/context without role records.  Normal
        # authenticated sessions always carry their full role set and use the
        # registry handler above.
        if planned.kind == "personal" and context.authenticated and not context.roles:
            legacy_route = parse_personal_intent(sanitized_query)
            legacy_result = handle_personal_request(legacy_route, context, db)
            if legacy_result is not None:
                planned = llm_planner.PlannedOperation(
                    kind="personal",
                    answer=legacy_result.answer,
                    personal_result=legacy_result,
                    intent=legacy_result.intent.value,
                    status="ok" if legacy_result.access_granted else ("auth_required" if legacy_result.authentication_required else "no_access"),
                    access_granted=legacy_result.access_granted,
                    status_message=legacy_result.status_message,
                    authentication_required=legacy_result.authentication_required,
                    response_scope=legacy_result.response_scope,
                )
        navigation_data = planned.navigation
        res = _audio_response(
            transcribed_input=user_query,
            text_response=planned.answer or "",
            status=planned.status,
            access_granted=planned.access_granted,
            error_message=planned.status_message,
            start_time=start_time,
            include_audio=False,
            response_scope=planned.response_scope,
            personal_intent=planned.intent if planned.kind == "personal" else None,
            authentication_required=planned.authentication_required,
            intent=planned.intent,
            navigation_target=(navigation_data or {}).get("navigation_target"),
            navigation=(navigation_data or {}).get("navigation"),
            route_summary=(navigation_data or {}).get("route_summary"),
            instructions=(navigation_data or {}).get("instructions", []),
            visualisation=(navigation_data or {}).get("visualisation"),
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
        )
        yield {"event": "metadata", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        if planned.answer:
            yield {"event": "chunk", "data": {"text": planned.answer}}
        pending: list[tuple[str, concurrent.futures.Future]] = []
        if rag_settings.AUDIO_TTS_ENABLED and planned.answer:
            pending.append((planned.answer, _TTS_EXECUTOR.submit(_tts_job, planned.answer, detected_language)))
        yield from _drain_tts_queue(pending, metrics, start_time, wait=True)
        yield {"event": "done", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        return

    # The shared planner already handled every non-RAG operation.  Keep this
    # legacy branch unreachable for planner-produced RAG turns so it cannot
    # perform a second personal or route classification.
    personal_route = None
    personal_result = None

    if personal_result is not None:
        navigation = None
        if personal_result.navigation_target:
            navigation = {
                "label": personal_result.navigation_target.label,
                "location": personal_result.navigation_target.location.display,
            }
        res = _audio_response(
            transcribed_input=user_query,
            text_response=personal_result.answer,
            status=(
                "ok"
                if personal_result.access_granted
                else (
                    "auth_required"
                    if personal_result.authentication_required
                    else "no_access"
                )
            ),
            access_granted=personal_result.access_granted,
            error_message=personal_result.status_message,
            start_time=start_time,
            include_audio=False,
            response_scope=personal_result.response_scope,
            personal_intent=personal_result.intent.value,
            authentication_required=personal_result.authentication_required,
            navigation_target=navigation,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
        )
        yield {"event": "metadata", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        if personal_result.answer:
            yield {"event": "chunk", "data": {"text": personal_result.answer}}
        pending: list[tuple[str, concurrent.futures.Future]] = []
        if rag_settings.AUDIO_TTS_ENABLED and personal_result.answer:
            pending.append((personal_result.answer, _TTS_EXECUTOR.submit(_tts_job, personal_result.answer, detected_language)))
        yield from _drain_tts_queue(pending, metrics, start_time, wait=True)
        if resolved_session_id is not None and resolved_session_id > 0:
            tts_time = int(metrics.time_to_first_tts_ms) if metrics.time_to_first_tts_ms > 0 else int((time.monotonic() - start_time) * 1000)
            log_personal_interaction(db, session_id=resolved_session_id, user_id=user_id or 0, intent=personal_route.intent.name, response_time_ms=tts_time)
        yield {"event": "done", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        return

    # Query routing: check if query is related to university information
    with StageTimer() as timer:
        route = type("Route", (), {"category": "UNIVERSITY_INFO"})()
    metrics.prompt_classification_ms += timer.elapsed_ms

    navigation_data = None
    # Confirmation context is supplied to the shared planner.  Do not run the
    # retired regex confirmation branch for planner-produced RAG turns.
    confirmed_label = None
    if confirmed_label:
        from RagChatbot.services.map_service import calculate_navigation
        navigation_data = calculate_navigation(f"where is {confirmed_label}", db=db, context=context)
        fast_answer = (navigation_data or {}).get("answer") or "I could not confirm that destination."
    elif route.category != "UNIVERSITY_INFO":
        if route.category == "GREETING":
            first_name = _greeting_name(context) if context.authenticated else ""
            if first_name:
                fast_answer = f"Hi {first_name}, how may I help you today?"
            else:
                fast_answer = "Hi, how may I help you today?"
        elif route.category == "CAPABILITY":
            fast_answer = get_capabilities_summary(authenticated=context.authenticated, personalisation_enabled=rag_settings.RAG_PERSONALISATION_ENABLED)
        elif route.category == "NAVIGATIONAL":
            from RagChatbot.services.map_service import calculate_navigation
            navigation_data = calculate_navigation(sanitized_query, db=db, context=context)
            fast_answer = (navigation_data or {}).get("answer") or "Please tell me the unique destination you want to reach."
        elif route.category == "OUT_OF_SCOPE":
            fast_answer = "I'm designed to answer questions based on the university information I have. I may not have reliable information about outside topics."
        elif route.category == "UNCLEAR":
            fast_answer = route.clarification_question or "Could you please clarify what university information you are looking for?"
        else:
            fast_answer = "I'm sorry, I could not process your query."

        res = _audio_response(
            transcribed_input=user_query,
            text_response=fast_answer,
            status="ok",
            access_granted=True,
            start_time=start_time,
            include_audio=False,
            metrics=metrics,
            user_id=user_id,
            session_id=resolved_session_id,
            intent=(
                "NAVIGATION_CONFIRMATION"
                if (navigation_data or {}).get("confirmation_required")
                else _navigation_intent(navigation_data)
            ),
            navigation_target=(navigation_data or {}).get("navigation_target") if navigation_data else None,
            navigation=(navigation_data or {}).get("navigation") if navigation_data else None,
            route_summary=(navigation_data or {}).get("route_summary") if navigation_data else None,
            instructions=(navigation_data or {}).get("instructions", []) if navigation_data else [],
            visualisation=(navigation_data or {}).get("visualisation") if navigation_data else None,
        )
        yield {"event": "metadata", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        if fast_answer:
            yield {"event": "chunk", "data": {"text": fast_answer}}
        pending = []
        if rag_settings.AUDIO_TTS_ENABLED and fast_answer:
            pending.append((fast_answer, _TTS_EXECUTOR.submit(_tts_job, fast_answer, detected_language)))
        yield from _drain_tts_queue(pending, metrics, start_time, wait=True)
        tts_time = int(metrics.time_to_first_tts_ms) if metrics.time_to_first_tts_ms > 0 else int((time.monotonic() - start_time) * 1000)
        log_chatbot_interaction(db, session_id=resolved_session_id, user_id=user_id, query_text=sanitized_query, response_text=fast_answer, retrieved_chunk_ids=[], response_time_ms=tts_time, is_navigational=bool(navigation_data))
        yield {"event": "done", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        return

    query_embedding = embed_text(sanitized_query)
    ranked_chunks = retrieve_chunks(
        query_embedding=query_embedding,
        allowed_access_levels=allowed_levels,
        db=db,
        top_k_retrieval=rag_settings.TOP_K_RETRIEVAL,
        top_k_context=rag_settings.TOP_K_CONTEXT,
        query_text=sanitized_query,
    )

    if not ranked_chunks:
        if user_id is None and _has_relevant_protected_chunks(query_embedding, db):
            res = _audio_response(
                transcribed_input=user_query,
                text_response=AUTH_REQUIRED_ANSWER,
                status="auth_required",
                access_granted=False,
                start_time=start_time,
                include_audio=False,
                metrics=metrics,
                user_id=user_id,
                session_id=resolved_session_id,
            )
        else:
            res = _audio_response(
                transcribed_input=user_query,
                text_response="I'm sorry, I don't have enough information in the available documents to answer that question.",
                status="no_access" if user_id is None else "ok",
                access_granted=True,
                start_time=start_time,
                include_audio=False,
                metrics=metrics,
                user_id=user_id,
                session_id=resolved_session_id,
            )
        yield {"event": "metadata", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        if res.text_response:
            yield {"event": "chunk", "data": {"text": res.text_response}}
        pending = []
        if res.text_response and rag_settings.AUDIO_TTS_ENABLED:
            pending.append((res.text_response, _TTS_EXECUTOR.submit(_tts_job, res.text_response, detected_language)))
        yield from _drain_tts_queue(pending, metrics, start_time, wait=True)
        yield {"event": "done", "data": res.model_dump(mode="json", exclude={"audio_response"})}
        return

    citations = [
        CitationSchema(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_title=chunk.document_title,
            chunk_index=chunk.chunk_index,
            access_level=chunk.access_level,
            excerpt=chunk.chunk_text[:200],
        )
        for chunk in ranked_chunks
    ]

    initial_res = _audio_response(
        transcribed_input=user_query,
        text_response="",
        sources=citations,
        status="ok",
        access_granted=True,
        start_time=start_time,
        include_audio=False,
        metrics=metrics,
        user_id=user_id,
        session_id=resolved_session_id,
    )
    yield {"event": "metadata", "data": initial_res.model_dump(mode="json", exclude={"audio_response"})}

    splitter = StreamingSentenceSplitter()
    full_answer_parts: List[str] = []
    pending_tts: list[tuple[str, concurrent.futures.Future]] = []

    try:
        for token in generate_answer_stream(
            sanitized_query,
            ranked_chunks,
            chat_history=_recent_chat_history(db, resolved_session_id),
            user_context=context,
        ):
            full_answer_parts.append(token)
            yield {"event": "chunk", "data": {"text": token}}
            for sentence in splitter.feed(token):
                val = validate_sentence(sentence)
                clean_sentence = val.sanitized_text or sentence if not val.valid else sentence
                logger.info("STREAM_DEBUG [%.3f]: Yielding sentence text: %s", time.time(), clean_sentence)
                yield {"event": "sentence", "data": {"text": clean_sentence}}
                if rag_settings.AUDIO_TTS_ENABLED:
                    pending_tts.append((clean_sentence, _TTS_EXECUTOR.submit(_tts_job, clean_sentence, detected_language)))
                yield from _drain_tts_queue(pending_tts, metrics, start_time)
    except RuntimeError as exc:
        logger.error("Audio chat stream: generation failed for user_id=%s: %s", user_id, exc)
        raise GeminiLiveError(f"Response generation failed: {exc}") from exc

    for sentence in splitter.flush():
        val = validate_sentence(sentence)
        clean_sentence = val.sanitized_text or sentence if not val.valid else sentence
        yield {"event": "sentence", "data": {"text": clean_sentence}}
        if rag_settings.AUDIO_TTS_ENABLED:
            pending_tts.append((clean_sentence, _TTS_EXECUTOR.submit(_tts_job, clean_sentence, detected_language)))
        yield from _drain_tts_queue(pending_tts, metrics, start_time)

    # Preserve all generated text and only wait for speech after the LLM has
    # finished. Text consumers can therefore render immediately.
    yield from _drain_tts_queue(pending_tts, metrics, start_time, wait=True)

    full_answer = "".join(full_answer_parts)
    audit_query_id: Optional[int] = None
    try:
        tts_time = int(metrics.time_to_first_tts_ms) if metrics.time_to_first_tts_ms > 0 else int((time.monotonic() - start_time) * 1000)
        logged_id = log_chatbot_interaction(
            db,
            session_id=resolved_session_id,
            user_id=user_id,
            query_text=sanitized_query,
            response_text=full_answer,
            retrieved_chunk_ids=[c.chunk_id for c in ranked_chunks],
            response_time_ms=tts_time,
        )
        audit_query_id = _safe_query_id(logged_id)
    except Exception:
        logger.warning("Audio chat stream: unable to persist conversation", exc_info=True)
    final_res = _audio_response(
        transcribed_input=user_query,
        text_response=full_answer,
        sources=citations,
        status="ok",
        access_granted=True,
        start_time=start_time,
        include_audio=False,
        query_id=audit_query_id,
        metrics=metrics,
        user_id=user_id,
        session_id=resolved_session_id,
    )
    yield {"event": "done", "data": final_res.model_dump(mode="json", exclude={"audio_response"})}
