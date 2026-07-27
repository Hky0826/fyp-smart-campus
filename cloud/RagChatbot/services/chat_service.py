"""
Core chat service.

Orchestrates the full RAG pipeline for a single user query:

    1. Prompt injection guard
    2. JWT resolution -> user_id + session_id
    3. RBAC: resolve allowed document access levels from DB
    4. Embed the sanitized query with Google AI
    5. Retrieve authorized document chunks from MySQL VECTOR index
    6. Re-rank and trim to context window
    7. Generate grounded answer with Gemini
    8. Build CitationSchema objects
    9. Audit log the interaction
   10. Return ChatResponse

Security invariant: the LLM never receives chunks that have not already
passed RBAC filtering. The LLM never decides access permissions.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import List, Optional

import jwt as pyjwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from RagChatbot.config import rag_settings
from RagChatbot.embeddings.google_embedding_service import embed_text
from RagChatbot.generation.google_llm_service import (
    generate_answer,
    generate_no_access_response,
)
from RagChatbot.retrieval.retriever import retrieve_chunks
from RagChatbot.schemas import ChatRequest, ChatResponse, CitationSchema
from RagChatbot.security.audit_logger import log_access_denied, log_chatbot_interaction, log_personal_interaction
from RagChatbot.security.prompt_guard import check_query
from RagChatbot.security.rbac import get_allowed_access_levels_for_user
from RagChatbot.security.auth_context import resolve_auth_context
from RagChatbot.personalisation.intents import parse_personal_intent
from RagChatbot.personalisation.service import handle_personal_request
from RagChatbot.logging.inference_logger import InferenceMetrics, StageTimer, log_inference_metrics

logger = logging.getLogger(__name__)

VISITOR_ACCESS_LEVELS = ["PUBLIC"]
PROTECTED_ACCESS_LEVELS = ["STUDENT", "LECTURER", "ADMIN"]
AUTH_REQUIRED_ANSWER = (
    "This question may require access above visitor level. "
    "Please scan your face so I can confirm whether you have permission to answer it."
)
AUTH_REQUIRED_STATUS = "Authentication required: please scan your face to check protected document access."


# JWT helpers

def _decode_jwt(token: str) -> dict:
    """
    Decode and validate a JWT, returning the payload.

    Raises:
        HTTPException 401: If the token is invalid or expired.
    """
    try:
        payload = pyjwt.decode(
            token,
            rag_settings.JWT_SECRET,
            algorithms=[rag_settings.JWT_ALGORITHM],
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT token has expired. Please re-authenticate.",
        )
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )


def _verify_session(token: str, db: Session) -> tuple[int, int]:
    """
    Verify that the JWT has a valid, non-revoked session in the database.

    Supports two JWT formats:
      - Edge user tokens: payload contains 'user_id' (int) field.
      - Admin tokens: payload contains 'sub' (admin_id str) - these can
        also use the chatbot if they want, but are less likely to.

    Returns:
        (user_id, session_id)

    Raises:
        HTTPException 401: If the session is not found, revoked, or expired.
    """
    from app.models.models import JWTSession
    import datetime

    payload = _decode_jwt(token)

    # Edge user tokens have an explicit 'user_id' field (int)
    user_id: Optional[int] = payload.get("user_id")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing user_id. Please re-authenticate via face recognition.",
        )

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = (
        db.query(JWTSession)
        .filter_by(token_hash=token_hash, is_revoked=False)
        .first()
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session not found or has been revoked.",
        )
    if session.expires_at < datetime.datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please re-authenticate.",
        )
    if int(session.user_id) != int(user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication session does not match the token user.")
    from app.models.models import User
    if not db.query(User).filter_by(user_id=user_id, is_active=True).first():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or unavailable. Please re-authenticate.")

    return user_id, session.session_id


# Main chat pipeline

def process_chat(
    request: ChatRequest,
    bearer_token: str | None,
    db: Session,
) -> ChatResponse:
    """
    Execute the full RAG pipeline for a user's chat query.

    Args:
        request: Validated ChatRequest from the API endpoint.
        bearer_token: The raw JWT extracted from the Authorization header, or None for visitor/PUBLIC access.
        db: Active SQLAlchemy session.

    Returns:
        ChatResponse containing the answer, citations, and audit info.
    """
    start_time = time.monotonic()
    metrics = InferenceMetrics()

# Step 1: Prompt injection guard
    with StageTimer() as timer:
        guard_result = check_query(request.query)
    metrics.prompt_injection_ms += timer.elapsed_ms

    if not guard_result.is_safe:
        logger.warning("Prompt injection blocked. pattern=%s", guard_result.matched_pattern)

        # We still need session_id for the audit log; attempt JWT decode without
        # a hard failure so the log is written before the error is returned.
        user_id, session_id = None, None
        if bearer_token:
            try:
                user_id, session_id = _verify_session(bearer_token, db)
            except HTTPException:
                user_id, session_id = None, None

        if session_id and session_id > 0:
            log_access_denied(
                db,
                session_id=session_id,
                user_id=user_id,
                query_text=request.query,
                reason=f"prompt_injection:{guard_result.matched_pattern}",
            )

        metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
        log_inference_metrics(
            request_type="text",
            user_id=user_id,
            session_id=session_id,
            query_text=request.query,
            metrics=metrics,
            status="blocked",
        )

        return ChatResponse(
            answer=(
                "I'm not able to process that request. "
                "Please ask a straightforward question about campus services or documents."
            ),
            citations=[],
            access_granted=False,
            status_message="Request blocked: potentially unsafe query pattern detected.",
            response_time_ms=int((time.monotonic() - start_time) * 1000),
        )

    sanitized_query = guard_result.sanitized_query or request.query

# Step 2: JWT verification and user/session resolution
    context = resolve_auth_context(bearer_token, db)
    user_id, session_id = context.user_id, context.session_id
    if context.authenticated and user_id is not None:
        allowed_levels = get_allowed_access_levels_for_user(user_id, db)
        logger.info("Chat: user_id=%d allowed_levels=%s", user_id, allowed_levels)
    else:
        allowed_levels = VISITOR_ACCESS_LEVELS
        logger.info("Chat: anonymous visitor allowed_levels=%s", allowed_levels)

    with StageTimer() as timer:
        personal_route = parse_personal_intent(sanitized_query)
        personal_result = handle_personal_request(personal_route, context, db)
    metrics.prompt_classification_ms += timer.elapsed_ms

    if personal_result is not None:
        response_time_ms = int((time.monotonic() - start_time) * 1000)
        query_id = None
        if session_id is not None and user_id is not None:
            logged_query_id = log_personal_interaction(db, session_id=session_id, user_id=user_id, intent=personal_result.intent.value, response_time_ms=response_time_ms, is_navigational=personal_result.navigation_target is not None)
            query_id = logged_query_id if logged_query_id > 0 else None
        navigation = None
        if personal_result.navigation_target:
            navigation = {"label": personal_result.navigation_target.label, "location": personal_result.navigation_target.location.display}

        metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
        log_inference_metrics(
            request_type="text",
            user_id=user_id,
            session_id=session_id,
            query_text=sanitized_query,
            metrics=metrics,
            status="ok" if personal_result.access_granted else "no_access",
        )

        return ChatResponse(answer=personal_result.answer, citations=[], access_granted=personal_result.access_granted, status_message=personal_result.status_message, response_time_ms=response_time_ms, query_id=query_id, response_scope=personal_result.response_scope, personal_intent=personal_result.intent.value, authentication_required=personal_result.authentication_required, navigation_target=navigation)

# Step 2.5: Query routing
    from RagChatbot.generation.query_router import classify_query, get_capabilities_summary
    
    with StageTimer() as timer:
        route = classify_query(sanitized_query)
    metrics.prompt_classification_ms += timer.elapsed_ms

    fast_answer = None

    if route.category == "GREETING":
        first_name = context.full_name.strip().split()[0] if (context.authenticated and context.full_name and context.full_name.strip()) else ""
        if first_name:
            fast_answer = f"Hi {first_name}! How can I help you with Quest International University today?"
        else:
            fast_answer = "Hi! How can I help you with Quest International University today?"
    elif route.category == "CAPABILITY":
        fast_answer = get_capabilities_summary(authenticated=context.authenticated, personalisation_enabled=rag_settings.RAG_PERSONALISATION_ENABLED)
    elif route.category == "NAVIGATIONAL":
        fast_answer = "Navigational request detected. Routing to map module..."
    elif route.category == "OUT_OF_SCOPE":
        fast_answer = "I'm designed to answer questions based on the university information I have. I may not have reliable information about outside topics."
    elif route.category == "UNCLEAR":
        fast_answer = route.clarification_question or "Could you please clarify what university information you are looking for?"

    if fast_answer:
        # Bypass RAG completely and return the fast answer.
        response_time_ms = int((time.monotonic() - start_time) * 1000)
        query_id = None
        if session_id is not None:
            logged_query_id = log_chatbot_interaction(
                db,
                session_id=session_id,
                user_id=user_id,
                query_text=sanitized_query,
                response_text=fast_answer,
                retrieved_chunk_ids=[],
                response_time_ms=response_time_ms,
            )
            query_id = logged_query_id if logged_query_id > 0 else None

        metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
        log_inference_metrics(
            request_type="text",
            user_id=user_id,
            session_id=session_id,
            query_text=sanitized_query,
            metrics=metrics,
            status="ok",
        )

        return ChatResponse(
            answer=fast_answer,
            citations=[],
            access_granted=True,
            status_message=None,
            response_time_ms=response_time_ms,
            query_id=query_id,
        )

# Step 3: RBAC access levels

# Step 4: Embed the query
    with StageTimer() as timer:
        try:
            query_embedding = embed_text(sanitized_query)
        except RuntimeError as exc:
            logger.error("Embedding failed for user_id=%s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Embedding service is temporarily unavailable. Please try again later.",
            )
    metrics.embedding_return_ms += timer.elapsed_ms

# Steps 5-6: Retrieve and re-rank authorized chunks
    with StageTimer() as timer:
        ranked_chunks = retrieve_chunks(
            query_embedding=query_embedding,
            allowed_access_levels=allowed_levels,
            db=db,
        )
    metrics.embedding_db_search_ms += timer.elapsed_ms

# Step 7: Generate answer
    with StageTimer() as timer:
        if not ranked_chunks:
            if not bearer_token and _has_relevant_protected_chunks(query_embedding, db):
                answer = AUTH_REQUIRED_ANSWER
                access_granted = False
                status_message = AUTH_REQUIRED_STATUS
            else:
                answer = generate_no_access_response()
                access_granted = False
                status_message = "No relevant documents found for your access level."
        else:
            try:
                chat_history = []
                if session_id:
                    from app.models.models import ChatbotQuery
                    recent_queries = (
                        db.query(ChatbotQuery)
                        .filter(ChatbotQuery.session_id == session_id)
                        .filter(ChatbotQuery.response_text.isnot(None))
                        .order_by(ChatbotQuery.timestamp.desc())
                        .limit(3)
                        .all()
                    )
                    for q in reversed(recent_queries):
                        chat_history.append({
                            "user": q.query_text,
                            "assistant": q.response_text
                        })

                answer = generate_answer(sanitized_query, ranked_chunks, chat_history=chat_history)
                access_granted = True
                status_message = None
            except RuntimeError as exc:
                logger.error("LLM generation failed for user_id=%s: %s", user_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Answer generation is temporarily unavailable. Please try again later.",
                )
    metrics.rag_ms += timer.elapsed_ms

# Step 8: Build citation objects
    citations: List[CitationSchema] = [
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

    response_time_ms = int((time.monotonic() - start_time) * 1000)

# Step 9: Audit log
    query_id = None
    if session_id is not None:
        logged_query_id = log_chatbot_interaction(
            db,
            session_id=session_id,
            user_id=user_id,
            query_text=sanitized_query,
            response_text=answer,
            retrieved_chunk_ids=[c.chunk_id for c in ranked_chunks],
            response_time_ms=response_time_ms,
        )
        query_id = logged_query_id if logged_query_id > 0 else None

    metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
    log_inference_metrics(
        request_type="text",
        user_id=user_id,
        session_id=session_id,
        query_text=sanitized_query,
        metrics=metrics,
        status="ok" if access_granted else "no_access",
    )

# Step 10: Return response
    return ChatResponse(
        answer=answer,
        citations=citations,
        access_granted=access_granted,
        status_message=status_message,
        response_time_ms=response_time_ms,
        query_id=query_id,
    )


def _has_relevant_protected_chunks(query_embedding: List[float], db: Session) -> bool:
    """Return True when protected chunks match an anonymous visitor query."""
    protected_chunks = retrieve_chunks(
        query_embedding=query_embedding,
        allowed_access_levels=PROTECTED_ACCESS_LEVELS,
        db=db,
        top_k_retrieval=3,
        top_k_context=1,
    )
    return bool(protected_chunks)


def process_public_smoke_chat(
    request: ChatRequest,
    db: Session,
) -> ChatResponse:
    """
    Execute a no-JWT smoke-test RAG query against PUBLIC documents only.

    This is intended for edge-device audio/cloud diagnostics. It deliberately
    does not resolve a user, does not grant elevated document access, and does
    not write chatbot_queries because that table requires a JWT session.
    """
    start_time = time.monotonic()
    metrics = InferenceMetrics()

    with StageTimer() as timer:
        guard_result = check_query(request.query)
    metrics.prompt_injection_ms += timer.elapsed_ms

    if not guard_result.is_safe:
        logger.warning("Public smoke-test prompt injection blocked. pattern=%s", guard_result.matched_pattern)
        metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
        log_inference_metrics(
            request_type="text",
            user_id=None,
            session_id=None,
            query_text=request.query,
            metrics=metrics,
            status="blocked",
        )
        return ChatResponse(
            answer=(
                "I'm not able to process that request. "
                "Please ask a straightforward question about campus services or documents."
            ),
            citations=[],
            access_granted=False,
            status_message="Request blocked: potentially unsafe query pattern detected.",
            response_time_ms=int((time.monotonic() - start_time) * 1000),
        )

    sanitized_query = guard_result.sanitized_query or request.query
    allowed_levels = ["PUBLIC"]
    logger.info("Public smoke-test chat: allowed_levels=%s", allowed_levels)

# Step 2.5: Query routing
    from RagChatbot.generation.query_router import classify_query, get_capabilities_summary
    
    with StageTimer() as timer:
        route = classify_query(sanitized_query)
    metrics.prompt_classification_ms += timer.elapsed_ms

    fast_answer = None

    if route.category == "GREETING":
        fast_answer = "Hi! How can I help you with Quest International University today?"
    elif route.category == "CAPABILITY":
        fast_answer = get_capabilities_summary()
    elif route.category == "NAVIGATIONAL":
        fast_answer = "Navigational request detected. Routing to map module..."
    elif route.category == "OUT_OF_SCOPE":
        fast_answer = "I'm designed to answer questions based on the university information I have. I may not have reliable information about outside topics."
    elif route.category == "UNCLEAR":
        fast_answer = route.clarification_question or "Could you please clarify what university information you are looking for?"

    if fast_answer:
        metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
        log_inference_metrics(
            request_type="text",
            user_id=None,
            session_id=None,
            query_text=sanitized_query,
            metrics=metrics,
            status="ok",
        )
        return ChatResponse(
            answer=fast_answer,
            citations=[],
            access_granted=True,
            status_message=None,
            response_time_ms=int((time.monotonic() - start_time) * 1000),
            query_id=None,
        )

    with StageTimer() as timer:
        try:
            query_embedding = embed_text(sanitized_query)
        except RuntimeError as exc:
            logger.error("Public smoke-test embedding failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Embedding service is temporarily unavailable. Please try again later.",
            )
    metrics.embedding_return_ms += timer.elapsed_ms

    with StageTimer() as timer:
        ranked_chunks = retrieve_chunks(
            query_embedding=query_embedding,
            allowed_access_levels=allowed_levels,
            db=db,
        )
    metrics.embedding_db_search_ms += timer.elapsed_ms

    with StageTimer() as timer:
        if not ranked_chunks:
            answer = generate_no_access_response()
            access_granted = False
            status_message = "No relevant public documents found."
        else:
            try:
                answer = generate_answer(sanitized_query, ranked_chunks)
                access_granted = True
                status_message = None
            except RuntimeError as exc:
                logger.error("Public smoke-test LLM generation failed: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Answer generation is temporarily unavailable. Please try again later.",
                )
    metrics.rag_ms += timer.elapsed_ms

    citations: List[CitationSchema] = [
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

    metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
    log_inference_metrics(
        request_type="text",
        user_id=None,
        session_id=None,
        query_text=sanitized_query,
        metrics=metrics,
        status="ok" if access_granted else "no_access",
    )

    return ChatResponse(
        answer=answer,
        citations=citations,
        access_granted=access_granted,
        status_message=status_message,
        response_time_ms=int((time.monotonic() - start_time) * 1000),
        query_id=None,
    )
