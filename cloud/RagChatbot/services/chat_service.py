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
import re
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
from RagChatbot.security.auth_context import resolve_auth_context, resolve_user_session
from RagChatbot.personalisation.intents import parse_personal_intent
from RagChatbot.personalisation.service import handle_personal_request
from RagChatbot.logging.inference_logger import InferenceMetrics, StageTimer, log_inference_metrics
from RagChatbot.generation import llm_planner

logger = logging.getLogger(__name__)

VISITOR_ACCESS_LEVELS = ["PUBLIC"]
PROTECTED_ACCESS_LEVELS = ["STUDENT", "LECTURER", "ADMIN"]
AUTH_REQUIRED_ANSWER = (
    "This question may require access above visitor level. "
    "Please scan your face so I can confirm whether you have permission to answer it."
)
AUTH_REQUIRED_STATUS = "Authentication required: please scan your face to check protected document access."


def _greeting_name(context) -> str:
    """Return the user's complete display name without duplicated whitespace."""
    full_name = " ".join(str(getattr(context, "full_name", "") or "").split())
    if full_name:
        return full_name
    return " ".join(str(getattr(context, "given_name", "") or "").split())


def _navigation_for_query(query: str, db: Session, context):
    from RagChatbot.services.map_service import calculate_navigation
    try:
        return calculate_navigation(query, db=db, context=context)
    except Exception as exc:
        logger.info("Navigation adapter could not calculate a route: %s", type(exc).__name__)
        return None


def _navigation_intent(navigation_data: dict | None) -> str | None:
    if not navigation_data:
        return None
    if navigation_data.get("confirmation_required"):
        return "NAVIGATION_CONFIRMATION"
    return "NAVIGATIONAL"


def _confirmed_navigation_label(query: str, db: Session, session_id: int | None) -> str | None:
    """Resolve confirmations and short category choices from the latest prompt."""
    if not session_id:
        return None

    try:
        from app.models.models import ChatbotQuery

        latest = (
            db.query(ChatbotQuery)
            .filter(ChatbotQuery.session_id == session_id)
            .order_by(ChatbotQuery.timestamp.desc(), ChatbotQuery.query_id.desc())
            .first()
        )
        response_text = str(getattr(latest, "response_text", "") or "")
        affirmative = re.fullmatch(
            r"\s*(?:yes|yeah|yep|correct|right|that(?:'s| is) it|yes please|go ahead|proceed)\s*[.!]?\s*",
            query,
            flags=re.IGNORECASE,
        )
        if affirmative:
            match = re.match(
                r"\s*Did you mean (?P<label>[^?]+)\? Is that the place you want to go\?\s*$",
                response_text,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group("label").strip()

        # A user commonly answers a category clarification with a short
        # choice such as “men”, “women”, or “unisex”. Resolve that choice
        # against the current catalog rather than manufacturing a fixed
        # destination label. This keeps the continuation working if labels
        # or facilities change.
        if (
            re.fullmatch(r"\s*(?:men|mens|male|women|womens|female|unisex|accessible)\s*[.!]?\s*", query, re.IGNORECASE)
            and "washroom" in response_text.casefold()
        ):
            from RagChatbot.services.map_service import _destination_matches, _normalise_label

            # Prefer the candidate labels already shown to the user. This
            # preserves the conversational contract and does not assume any
            # particular washroom naming convention.
            labels_match = re.search(r":\s*(?P<labels>[^.]+)\.\s*Which one", response_text, flags=re.IGNORECASE)
            if labels_match:
                requested = _normalise_label(query)
                for candidate_label in labels_match.group("labels").split(","):
                    candidate_label = candidate_label.strip()
                    candidate_words = set(_normalise_label(candidate_label).split())
                    if requested in candidate_words or requested == _normalise_label(candidate_label):
                        return candidate_label or None

            from cloud.mapping_and_notification.mapping.repository import MapRepository

            snapshot = MapRepository(db).snapshot()
            matches = _destination_matches(snapshot.nodes, f"{query} washroom")
            if len(matches) == 1:
                return str(getattr(matches[0], "label", "")).strip() or None

        # For a catalog response, accept a short label choice verbatim. The
        # navigation resolver still performs the final RBAC/catalog check.
        if len(str(query).split()) <= 5 and "which one" in response_text.casefold():
            labels_match = re.search(r":\s*(?P<labels>[^.]+)\.\s*Which one", response_text, flags=re.IGNORECASE)
            if labels_match:
                requested = " ".join(str(query).casefold().split())
                for label in labels_match.group("labels").split(","):
                    if requested == " ".join(label.casefold().split()) or requested in " ".join(label.casefold().split()).split():
                        return label.strip()
        return None
    except Exception as exc:
        logger.info("Could not resolve navigation confirmation: %s", type(exc).__name__)
        return None


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
    _, user_id, session = resolve_user_session(token, db)
    return user_id, int(session.session_id)


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
    context = resolve_auth_context(
        bearer_token,
        db,
        requested_device_id=request.device_id,
    )
    user_id, session_id = context.user_id, context.session_id
    if context.authenticated and user_id is not None:
        allowed_levels = get_allowed_access_levels_for_user(user_id, db)
        logger.info("Chat: user_id=%d allowed_levels=%s", user_id, allowed_levels)
    else:
        allowed_levels = VISITOR_ACCESS_LEVELS
        logger.info("Chat: anonymous visitor allowed_levels=%s", allowed_levels)

    # One shared structured planner owns active intent selection.  It returns
    # only fixed backend operations; university information is the sole result
    # that continues into the existing RBAC-filtered RAG path below.  The
    # planner module contains the deterministic, bounded fallback used when
    # the provider is unavailable.
    with StageTimer() as timer:
        planned = llm_planner.execute_planned_turn(
            sanitized_query,
            context=context,
            db=db,
            confirmation_context=_confirmed_navigation_label(sanitized_query, db, session_id),
        )
    metrics.prompt_classification_ms += timer.elapsed_ms

    if planned.kind != "rag":
        response_time_ms = int((time.monotonic() - start_time) * 1000)
        query_id = None
        if planned.kind == "personal" and planned.personal_result is not None:
            if session_id is not None and user_id is not None:
                logged_query_id = log_personal_interaction(
                    db,
                    session_id=session_id,
                    user_id=user_id,
                    intent=planned.intent or "UNKNOWN",
                    response_time_ms=response_time_ms,
                    is_navigational=bool(planned.navigation),
                )
                query_id = logged_query_id if logged_query_id > 0 else None
        elif session_id is not None:
            logged_query_id = log_chatbot_interaction(
                db,
                session_id=session_id,
                user_id=user_id,
                query_text=sanitized_query,
                response_text=planned.answer or "",
                retrieved_chunk_ids=[],
                response_time_ms=response_time_ms,
                is_navigational=planned.kind == "navigation",
            )
            query_id = logged_query_id if logged_query_id > 0 else None

        metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
        log_inference_metrics(
            request_type="text",
            user_id=user_id,
            session_id=session_id,
            query_text=sanitized_query,
            metrics=metrics,
            status=planned.status,
        )
        navigation_data = planned.navigation
        return ChatResponse(
            answer=planned.answer or "",
            citations=[],
            access_granted=planned.access_granted,
            status_message=planned.status_message,
            response_time_ms=response_time_ms,
            query_id=query_id,
            intent=planned.intent,
            navigation_target=(navigation_data or {}).get("navigation_target"),
            navigation=(navigation_data or {}).get("navigation"),
            route_summary=(navigation_data or {}).get("route_summary"),
            instructions=(navigation_data or {}).get("instructions", []),
            visualisation=(navigation_data or {}).get("visualisation"),
            response_scope=planned.response_scope,
            personal_intent=planned.intent if planned.kind == "personal" else None,
            authentication_required=planned.authentication_required,
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
        route = classify_query(sanitized_query, db=db)
    metrics.prompt_classification_ms += timer.elapsed_ms

    fast_answer = None
    navigation_data = None

    if route.category == "GREETING":
        fast_answer = "Hi! How can I help you with Quest International University today?"
    elif route.category == "CAPABILITY":
        fast_answer = get_capabilities_summary()
    elif route.category == "NAVIGATIONAL":
        navigation_data = _navigation_for_query(sanitized_query, db, None)
        fast_answer = (navigation_data or {}).get("answer") or "Please tell me the unique destination you want to reach."
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
            intent=_navigation_intent(navigation_data),
            navigation_target=(navigation_data or {}).get("navigation_target"),
            navigation=(navigation_data or {}).get("navigation"),
            route_summary=(navigation_data or {}).get("route_summary"),
            instructions=(navigation_data or {}).get("instructions", []),
            visualisation=(navigation_data or {}).get("visualisation"),
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
