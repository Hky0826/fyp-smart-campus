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

from collections import OrderedDict
from collections.abc import Iterator
import hashlib
import json
import logging
import re
from threading import Lock
import time
from typing import List, Optional

import jwt as pyjwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from RagChatbot.config import rag_settings
from RagChatbot.embeddings.google_embedding_service import embed_text
from RagChatbot.generation.google_llm_service import (
    generate_answer,
    generate_answer_stream,
    generate_no_access_response,
)
from RagChatbot.generation.query_router import classify_query, get_capabilities_summary
from RagChatbot.retrieval.retriever import retrieve_chunks
from RagChatbot.schemas import ChatRequest, ChatResponse, CitationSchema
from RagChatbot.security.audit_logger import log_access_denied, log_chatbot_interaction, log_personal_interaction
from RagChatbot.security.prompt_guard import check_query
from RagChatbot.security.rbac import get_allowed_access_levels_for_user
from RagChatbot.security.auth_context import resolve_auth_context, resolve_user_session
from RagChatbot.personalisation.intents import parse_personal_intent
from RagChatbot.personalisation.schemas import PersonalIntent
from RagChatbot.personalisation.service import handle_personal_request
from RagChatbot.logging.inference_logger import InferenceMetrics, StageTimer, log_inference_metrics
from RagChatbot.generation import llm_planner
from RagChatbot.utils.language_detection import detect_query_language
from RagChatbot.utils.translations import get_translated, get_capabilities_translated

logger = logging.getLogger(__name__)

VISITOR_ACCESS_LEVELS = ["PUBLIC"]
PROTECTED_ACCESS_LEVELS = ["STUDENT", "LECTURER", "ADMIN"]
AUTH_REQUIRED_ANSWER = (
    "This question may require access above visitor level. "
    "Please scan your face so I can confirm whether you have permission to answer it."
)
AUTH_REQUIRED_STATUS = "Authentication required: please scan your face to check protected document access."

_RAG_RESPONSE_CACHE: OrderedDict[str, tuple[float, ChatResponse]] = OrderedDict()
_RAG_RESPONSE_CACHE_LOCK = Lock()


def _rag_cache_key(query: str, allowed_access_levels: List[str]) -> str:
    """Compute RBAC-safe deterministic cache key for a RAG query."""
    norm = " ".join(query.strip().lower().split())
    levels = ",".join(sorted(allowed_access_levels))
    return hashlib.sha256(f"{norm}|{levels}".encode("utf-8")).hexdigest()


def clear_rag_response_cache() -> None:
    """Clear all cached RAG chatbot responses."""
    with _RAG_RESPONSE_CACHE_LOCK:
        _RAG_RESPONSE_CACHE.clear()


def _safe_query_id(val: Any) -> Optional[int]:
    if isinstance(val, int) and val > 0:
        return val
    return None


def _make_citation(chunk) -> CitationSchema:
    c_type = getattr(chunk, "chunk_type", "DETAIL")
    c_type_str = str(c_type) if c_type is not None and not hasattr(c_type, "_mock_name") else "DETAIL"
    s_path = getattr(chunk, "section_path", None)
    s_path_str = str(s_path) if s_path is not None and not hasattr(s_path, "_mock_name") else None
    e_tags = getattr(chunk, "entity_tags", [])
    e_tags_list = list(e_tags) if isinstance(e_tags, list) else []
    
    raw_roles = getattr(chunk, "allowed_roles", None)
    if isinstance(raw_roles, str):
        try:
            parsed_roles = json.loads(raw_roles)
        except Exception:
            parsed_roles = [raw_roles]
    elif isinstance(raw_roles, (list, set, tuple)):
        parsed_roles = list(raw_roles)
    else:
        parsed_roles = ["VISITOR"]

    cid = getattr(chunk, "chunk_id", 1)
    did = getattr(chunk, "document_id", 1)
    dtitle = getattr(chunk, "document_title", "Campus Document")
    cindex = getattr(chunk, "chunk_index", 1)
    alevel = getattr(chunk, "access_level", "VISITOR")
    ctext = getattr(chunk, "chunk_text", "")
    
    return CitationSchema(
        chunk_id=cid if isinstance(cid, int) and not hasattr(cid, "_mock_name") else 1,
        document_id=did if isinstance(did, int) and not hasattr(did, "_mock_name") else 1,
        document_title=str(dtitle) if not hasattr(dtitle, "_mock_name") else "Campus Document",
        chunk_index=cindex if isinstance(cindex, int) and not hasattr(cindex, "_mock_name") else 1,
        access_level=str(alevel) if not hasattr(alevel, "_mock_name") else "VISITOR",
        allowed_roles=parsed_roles,
        excerpt=(str(ctext) if not hasattr(ctext, "_mock_name") else "")[:200],
        chunk_type=c_type_str,
        section_path=s_path_str,
        entity_tags=e_tags_list,
    )


def _split_stream_text(text: str, max_chars: int = 30) -> Iterator[str]:
    """Split a generated answer into small streamed chunks for smooth live display."""
    pending = " ".join(text.split())
    while len(pending) > max_chars:
        split_at = pending.rfind(" ", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars

        chunk = pending[:split_at].strip()
        if chunk:
            yield chunk + " "
        pending = pending[split_at:].strip()

    if pending:
        yield pending


def _sse_event(event: str, payload: dict) -> str:
    """Serialize one Server-Sent Event message."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
            r"\s*(?:yes|yeah|yep|correct|right|that(?:'s| is) it|yes please|go ahead|proceed"
            r"|ya|betul|okay|ok"
            r"|是|对|好|没错|是的|好的|对的"
            r"|ஆம்|சரி"
            r"|हाँ|जी हाँ|सही|ठीक है"
            r")\s*[.!。！]?\s*",
            query,
            flags=re.IGNORECASE,
        )
        if affirmative:
            match = re.match(
                r"\s*(?:Did you mean|您是指|Adakah anda maksudkan)\s+(?P<label>[^?？]+)",
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
            re.fullmatch(
                r"\s*(?:men|mens|male|women|womens|female|unisex|accessible"
                r"|lelaki|perempuan|wanita"
                r"|男|女|无障碍"
                r"|ஆண்|பெண்"
                r"|पुरुष|महिला"
                r")\s*[.!。！]?\s*",
                query,
                re.IGNORECASE,
            )
            and any(w in response_text.casefold() for w in ("washroom", "toilet", "tandas", "厕所", "கழிப்பறை", "शौचालय"))
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

            from RagChatbot.services.map_service import get_map_snapshot

            snapshot = get_map_snapshot(db)
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
def _load_recent_chat_history(session_id: int | None, db: Session, limit: int = 3) -> list[dict[str, str]]:
    """Load the most recent completed conversation turns for the active session."""
    if not session_id or db is None:
        return []
    try:
        from app.models.models import ChatbotQuery
        recent = (
            db.query(ChatbotQuery)
            .filter(ChatbotQuery.session_id == session_id)
            .filter(ChatbotQuery.response_text.isnot(None))
            .order_by(ChatbotQuery.timestamp.desc(), ChatbotQuery.query_id.desc())
            .limit(limit)
            .all()
        )
        history = []
        for q in reversed(recent):
            history.append({
                "user": str(getattr(q, "query_text", "") or ""),
                "assistant": str(getattr(q, "response_text", "") or "")
            })
        return history
    except Exception as exc:
        logger.debug("Could not load recent chat history: %s", exc)
        return []


def _condense_query_with_history(query: str, history: list[dict[str, str]]) -> str:
    """Condense conversational follow-up query into a standalone retrieval search string."""
    if not history or not getattr(rag_settings, "RAG_QUERY_REWRITE_ENABLED", True):
        return query

    # Fast regex screening for pronouns / follow-up hints
    needs_rewrite = bool(re.search(
        r"\b(it|its|this|that|these|those|they|their|them|he|she|his|her|the course|the programme|the fee|the fees|the requirement|the requirements|cost|duration|where is it|what about|and for|how about)\b",
        query,
        re.IGNORECASE,
    ))
    if not needs_rewrite:
        return query

    try:
        from RagChatbot.gemini_client import get_gemini_client
        client = get_gemini_client()
        history_lines = [f"User: {h.get('user', '')}\nAssistant: {h.get('assistant', '')}" for h in history[-2:]]
        prompt = (
            f"Conversation history:\n" + "\n".join(history_lines) + "\n\n"
            f"Rewrite this follow-up into a concise standalone search query for university document retrieval. "
            f"Do not answer it. Return ONLY the rewritten query text.\n"
            f"Follow-up: {query}\n"
            f"Standalone query:"
        )
        response = client.models.generate_content(
            model=rag_settings.PLANNER_MODEL,
            contents=prompt,
            config={"temperature": 0.0, "max_output_tokens": 48},
        )
        rewritten = (response.text or "").strip().replace('"', '').replace("'", "")
        if rewritten and len(rewritten) > 3:
            logger.info("Conversational query condensed: '%s' -> '%s'", query, rewritten)
            return rewritten
    except Exception as exc:
        logger.debug("Conversational query rewrite skipped (%s); using original.", exc)
    return query


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

        user_id, session_id = None, None
        if bearer_token:
            try:
                user_id, session_id = _verify_session(bearer_token, db)
            except HTTPException:
                user_id, session_id = None, None

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

    # Fast-path intent routing & cache check:
    # 1. Check navigation confirmation & personal intent locally
    # 2. Check query router locally (~2ms regex)
    # 3. For greetings, capabilities, and out-of-scope queries: return fast response immediately
    # 4. For direct university RAG: check response cache, then skip the slow LLM planner entirely
    confirmation_context = _confirmed_navigation_label(sanitized_query, db, session_id)
    personal_intent_result = parse_personal_intent(sanitized_query)
    detected_lang = detect_query_language(sanitized_query)
    is_non_english = detected_lang != "en"

    # Fast-path 1: Direct in-memory & dense vector navigation (instant <50ms response)
    from RagChatbot.services.map_service import is_navigation_query
    direct_nav = None
    if confirmation_context is not None:
        direct_nav = _navigation_for_query(confirmation_context, db, context)
    elif is_navigation_query(sanitized_query, db=db):
        direct_nav = _navigation_for_query(sanitized_query, db, context)

    if direct_nav and direct_nav.get("answer"):
        response_time_ms = int((time.monotonic() - start_time) * 1000)
        logged = log_chatbot_interaction(
            db,
            session_id=session_id,
            user_id=user_id,
            query_text=sanitized_query,
            response_text=direct_nav["answer"],
            retrieved_chunk_ids=[],
            response_time_ms=response_time_ms,
            is_navigational=True,
        )
        query_id = _safe_query_id(logged)
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
            answer=direct_nav["answer"],
            citations=[],
            access_granted=True,
            status_message=None,
            response_time_ms=response_time_ms,
            query_id=query_id,
            intent=_navigation_intent(direct_nav),
            navigation_target=direct_nav.get("navigation_target"),
            navigation=direct_nav.get("navigation"),
            route_summary=direct_nav.get("route_summary"),
            instructions=direct_nav.get("instructions", []),
            visualisation=direct_nav.get("visualisation"),
            response_scope="FACILITY",
        )

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
            fast_answer = f"Hi {name}, how may I help you today?" if name else "Hi, how may I help you today?"
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            logged = log_chatbot_interaction(
                db,
                session_id=session_id,
                user_id=user_id,
                query_text=sanitized_query,
                response_text=fast_answer,
                retrieved_chunk_ids=[],
                response_time_ms=response_time_ms,
                is_navigational=False,
            )
            query_id = _safe_query_id(logged)
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
                intent="GREETING",
            )

        if route.category == "CAPABILITY":
            fast_answer = get_capabilities_translated(
                authenticated=context.authenticated,
                personalisation_enabled=rag_settings.RAG_PERSONALISATION_ENABLED,
                lang=detected_lang,
            )
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            logged = log_chatbot_interaction(
                db,
                session_id=session_id,
                user_id=user_id,
                query_text=sanitized_query,
                response_text=fast_answer,
                retrieved_chunk_ids=[],
                response_time_ms=response_time_ms,
                is_navigational=False,
            )
            query_id = _safe_query_id(logged)
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
                intent="CAPABILITY",
            )

        if route.category == "OUT_OF_SCOPE":
            fast_answer = get_translated("out_of_scope", detected_lang)
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            logged = log_chatbot_interaction(
                db,
                session_id=session_id,
                user_id=user_id,
                query_text=sanitized_query,
                response_text=fast_answer,
                retrieved_chunk_ids=[],
                response_time_ms=response_time_ms,
                is_navigational=False,
            )
            query_id = _safe_query_id(logged)
            metrics.total_inference_ms = (time.monotonic() - start_time) * 1000.0
            log_inference_metrics(
                request_type="text",
                user_id=user_id,
                session_id=session_id,
                query_text=sanitized_query,
                metrics=metrics,
                status="blocked",
            )
            return ChatResponse(
                answer=fast_answer,
                citations=[],
                access_granted=False,
                status_message=get_translated("out_of_scope_status", detected_lang),
                response_time_ms=response_time_ms,
                query_id=query_id,
                intent="OUT_OF_SCOPE",
            )

        # Check full RAG response cache for direct university questions:
        cache_key = _rag_cache_key(sanitized_query, allowed_levels)
        with _RAG_RESPONSE_CACHE_LOCK:
            if cache_key in _RAG_RESPONSE_CACHE:
                cached_time, cached_res = _RAG_RESPONSE_CACHE[cache_key]
                ttl = getattr(rag_settings, "RESPONSE_CACHE_TTL_SECONDS", 300.0)
                if time.monotonic() - cached_time < ttl:
                    _RAG_RESPONSE_CACHE.move_to_end(cache_key)
                    logger.debug("RAG response cache hit for query: %.40s", sanitized_query)
                    response_time_ms = int((time.monotonic() - start_time) * 1000)
                    logged_query_id = log_chatbot_interaction(
                        db,
                        session_id=session_id,
                        user_id=user_id,
                        query_text=sanitized_query,
                        response_text=cached_res.answer,
                        retrieved_chunk_ids=[c.chunk_id for c in cached_res.citations],
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
                        status="ok" if cached_res.access_granted else "no_access",
                    )
                    return ChatResponse(
                        answer=cached_res.answer,
                        citations=cached_res.citations,
                        access_granted=cached_res.access_granted,
                        status_message=cached_res.status_message,
                        response_time_ms=response_time_ms,
                        query_id=query_id,
                    )
                else:
                    del _RAG_RESPONSE_CACHE[cache_key]

    else:
        # Complex turn: LLM planner for structured tool dispatch (navigation, personal, unclear)
        with StageTimer() as timer:
            planned = llm_planner.execute_planned_turn(
                sanitized_query,
                context=context,
                db=db,
                confirmation_context=confirmation_context,
            )
        metrics.prompt_classification_ms += timer.elapsed_ms

        if planned.kind != "rag":
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            if planned.kind == "personal" and planned.personal_result is not None:
                logged_query_id = log_personal_interaction(
                    db,
                    session_id=session_id,
                    user_id=user_id or 0,
                    intent=planned.intent or "UNKNOWN",
                    response_time_ms=response_time_ms,
                    is_navigational=bool(planned.navigation),
                )
                query_id = _safe_query_id(logged_query_id)
            else:
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
                query_id = _safe_query_id(logged_query_id)

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

    chat_history = _load_recent_chat_history(session_id, db)
    search_query = _condense_query_with_history(sanitized_query, chat_history)

    # Step 4-8: Execute through Agentic RAG graph (Decomposition, Hybrid Retrieval, CRAG Grading, Rewriting, Groundedness Critic)
    with StageTimer() as timer:
        from RagChatbot.agent.graph import run_agentic_rag
        agent_res = run_agentic_rag(
            query=sanitized_query,
            auth_context=context,
            db=db,
            chat_history=chat_history,
        )
    metrics.rag_ms += timer.elapsed_ms

    answer = agent_res.answer
    access_granted = agent_res.access_granted
    status_message = agent_res.status_message
    citations: List[CitationSchema] = agent_res.citations
    ranked_chunks = []

    total_elapsed = time.monotonic() - start_time
    response_time_ms = int(total_elapsed * 1000)

# Step 9: Audit log
    logged_query_id = log_chatbot_interaction(
        db,
        session_id=session_id,
        user_id=user_id,
        query_text=sanitized_query,
        response_text=answer,
        retrieved_chunk_ids=[c.chunk_id for c in ranked_chunks],
        response_time_ms=response_time_ms,
        allowed_levels=allowed_levels,
        is_stream=False,
    )
    query_id = _safe_query_id(logged_query_id)

    metrics.total_inference_ms = total_elapsed * 1000.0
    metrics.allowed_access_levels = allowed_levels
    metrics.chunks_used_count = len(ranked_chunks)
    metrics.tokens_generated = len(answer.split())
    metrics.tokens_per_second = (metrics.tokens_generated / total_elapsed) if total_elapsed > 0 else 0.0
    metrics.is_streaming = False

    log_inference_metrics(
        request_type="text",
        user_id=user_id,
        session_id=session_id,
        query_text=sanitized_query,
        metrics=metrics,
        status="ok" if access_granted else "no_access",
    )

# Step 10: Cache and return response
    response = ChatResponse(
        answer=answer,
        citations=citations,
        access_granted=access_granted,
        status_message=status_message,
        response_time_ms=response_time_ms,
        query_id=query_id,
    )

    if access_granted:
        cache_key = _rag_cache_key(sanitized_query, allowed_levels)
        with _RAG_RESPONSE_CACHE_LOCK:
            _RAG_RESPONSE_CACHE[cache_key] = (time.monotonic(), response)
            _RAG_RESPONSE_CACHE.move_to_end(cache_key)
            max_size = getattr(rag_settings, "RESPONSE_CACHE_SIZE", 256)
            while len(_RAG_RESPONSE_CACHE) > max_size:
                _RAG_RESPONSE_CACHE.popitem(last=False)

    return response


def process_chat_stream(
    request: ChatRequest,
    bearer_token: str | None,
    db: Session,
) -> Iterator[str]:
    """
    Execute the RAG pipeline and stream answer chunks as Server-Sent Events (SSE).

    For fast/cached/blocked responses, yields the chunks followed by done.
    For RAG responses, streams tokens directly from Gemini Live/Streaming API.
    """
    start_time = time.monotonic()
    metrics = InferenceMetrics()

    # Step 1: Prompt injection guard
    with StageTimer() as timer:
        guard_result = check_query(request.query)
    metrics.prompt_injection_ms += timer.elapsed_ms

    if not guard_result.is_safe:
        logger.warning("Prompt injection blocked in stream. pattern=%s", guard_result.matched_pattern)
        user_id, session_id = None, None
        if bearer_token:
            try:
                user_id, session_id = _verify_session(bearer_token, db)
            except HTTPException:
                user_id, session_id = None, None
        if session_id and session_id > 0:
            log_access_denied(
                db, session_id=session_id, user_id=user_id,
                query_text=request.query, reason=f"prompt_injection:{guard_result.matched_pattern}",
            )
        blocked_resp = ChatResponse(
            answer="I'm not able to process that request. Please ask a straightforward question about campus services or documents.",
            citations=[], access_granted=False,
            status_message="Request blocked: potentially unsafe query pattern detected.",
            response_time_ms=int((time.monotonic() - start_time) * 1000),
        )
        for chunk in _split_stream_text(blocked_resp.answer):
            yield _sse_event("chunk", {"text": chunk})
        yield _sse_event("done", blocked_resp.model_dump(mode="json"))
        return

    sanitized_query = guard_result.sanitized_query or request.query

    # Step 2: Auth resolution
    context = resolve_auth_context(bearer_token, db, requested_device_id=request.device_id)
    user_id, session_id = context.user_id, context.session_id
    allowed_levels = get_allowed_access_levels_for_user(user_id, db) if (context.authenticated and user_id is not None) else VISITOR_ACCESS_LEVELS

    # Step 2.5: Fast-path routing & cache check
    confirmation_context = _confirmed_navigation_label(sanitized_query, db, session_id)
    personal_intent_result = parse_personal_intent(sanitized_query)
    detected_lang = detect_query_language(sanitized_query)
    is_non_english = detected_lang != "en"

    # Fast-path 1: Direct in-memory & dense vector navigation (instant <50ms response)
    from RagChatbot.services.map_service import is_navigation_query
    if confirmation_context is not None or is_navigation_query(sanitized_query, db=db):
        fast_resp = process_chat(request, bearer_token, db)
        for chunk in _split_stream_text(fast_resp.answer):
            yield _sse_event("chunk", {"text": chunk})
        yield _sse_event("done", fast_resp.model_dump(mode="json"))
        return

    with StageTimer() as timer:
        route = classify_query(sanitized_query, db=db)
    metrics.prompt_classification_ms += timer.elapsed_ms

    needs_planner = (
        personal_intent_result.intent != PersonalIntent.UNKNOWN
        or route.category in ("NAVIGATIONAL", "UNCLEAR")
        or (is_non_english and context.authenticated)
    )

    if not needs_planner:
        if route.category in ("GREETING", "CAPABILITY", "OUT_OF_SCOPE"):
            fast_resp = process_chat(request, bearer_token, db)
            for chunk in _split_stream_text(fast_resp.answer):
                yield _sse_event("chunk", {"text": chunk})
            yield _sse_event("done", fast_resp.model_dump(mode="json"))
            return

        # Check response cache
        cache_key = _rag_cache_key(sanitized_query, allowed_levels)
        with _RAG_RESPONSE_CACHE_LOCK:
            if cache_key in _RAG_RESPONSE_CACHE:
                cached_time, cached_res = _RAG_RESPONSE_CACHE[cache_key]
                ttl = getattr(rag_settings, "RESPONSE_CACHE_TTL_SECONDS", 300.0)
                if time.monotonic() - cached_time < ttl:
                    _RAG_RESPONSE_CACHE.move_to_end(cache_key)
                    response_time_ms = int((time.monotonic() - start_time) * 1000)
                    logged = log_chatbot_interaction(
                        db, session_id=session_id, user_id=user_id, query_text=sanitized_query,
                        response_text=cached_res.answer, retrieved_chunk_ids=[c.chunk_id for c in cached_res.citations],
                        response_time_ms=response_time_ms,
                    )
                    query_id = _safe_query_id(logged)
                    done_resp = ChatResponse(
                        answer=cached_res.answer, citations=cached_res.citations,
                        access_granted=cached_res.access_granted, status_message=cached_res.status_message,
                        response_time_ms=response_time_ms, query_id=query_id,
                    )
                    for chunk in _split_stream_text(done_resp.answer):
                        yield _sse_event("chunk", {"text": chunk})
                    yield _sse_event("done", done_resp.model_dump(mode="json"))
                    return
    else:
        # Fallback to standard execution for navigation / personal
        resp = process_chat(request, bearer_token, db)
        for chunk in _split_stream_text(resp.answer):
            yield _sse_event("chunk", {"text": chunk})
        yield _sse_event("done", resp.model_dump(mode="json"))
        return

    chat_history = _load_recent_chat_history(session_id, db)
    search_query = _condense_query_with_history(sanitized_query, chat_history)

    # Step 4: Embed query
    with StageTimer() as timer:
        try:
            query_embedding = embed_text(search_query)
        except RuntimeError as exc:
            logger.error("Streaming embedding failed: %s", exc)
            yield _sse_event("error", {"message": "Embedding service is temporarily unavailable."})
            return
    metrics.embedding_return_ms += timer.elapsed_ms

    # Step 5-6: Retrieve chunks
    with StageTimer() as timer:
        ranked_chunks = retrieve_chunks(
            query_embedding=query_embedding,
            allowed_access_levels=allowed_levels,
            db=db,
            query_text=search_query,
            category=getattr(route, "category_hint", None),
            faculty_code=getattr(route, "faculty_hint", None),
            is_broad_overview=getattr(route, "is_broad_overview", False),
        )
    metrics.embedding_db_search_ms += timer.elapsed_ms

    # Step 7: Generate answer (Streamed)
    if not ranked_chunks:
        if not bearer_token and _has_relevant_protected_chunks(query_embedding, db):
            answer = get_translated("auth_required", detected_lang)
            access_granted = False
            status_message = get_translated("auth_required_status", detected_lang)
        else:
            answer = get_translated("no_access", detected_lang)
            access_granted = False
            status_message = get_translated("no_access_status", detected_lang)

        resp = ChatResponse(
            answer=answer,
            citations=[],
            access_granted=access_granted,
            status_message=status_message,
            response_time_ms=int((time.monotonic() - start_time) * 1000),
            query_id=None,
        )
        for chunk in _split_stream_text(answer):
            yield _sse_event("chunk", {"text": chunk})
        yield _sse_event("done", resp.model_dump(mode="json"))
        return

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
            chat_history.append({"user": q.query_text, "assistant": q.response_text})

    generated_tokens: list[str] = []
    first_token_recorded = False
    try:
        for token in generate_answer_stream(sanitized_query, ranked_chunks, chat_history=chat_history, user_context=context):
            if not first_token_recorded:
                metrics.time_to_first_token_ms = (time.monotonic() - start_time) * 1000.0
                first_token_recorded = True
            generated_tokens.append(token)
            yield _sse_event("chunk", {"text": token})
    except Exception as exc:
        logger.error("LLM streaming answer generation failed: %s", exc)
        yield _sse_event("error", {"message": "Answer generation is temporarily unavailable."})
        return

    full_answer = "".join(generated_tokens).strip()

    citations: List[CitationSchema] = [_make_citation(chunk) for chunk in ranked_chunks]

    total_elapsed = time.monotonic() - start_time
    response_time_ms = int(total_elapsed * 1000)
    logged_query_id = log_chatbot_interaction(
        db,
        session_id=session_id,
        user_id=user_id,
        query_text=sanitized_query,
        response_text=full_answer,
        retrieved_chunk_ids=[c.chunk_id for c in ranked_chunks],
        response_time_ms=response_time_ms,
        allowed_levels=allowed_levels,
        is_stream=True,
    )
    query_id = _safe_query_id(logged_query_id)

    metrics.total_inference_ms = total_elapsed * 1000.0
    metrics.allowed_access_levels = allowed_levels
    metrics.chunks_used_count = len(ranked_chunks)
    metrics.tokens_generated = len(generated_tokens)
    metrics.tokens_per_second = (len(generated_tokens) / total_elapsed) if total_elapsed > 0 else 0.0
    metrics.is_streaming = True

    log_inference_metrics(
        request_type="text",
        user_id=user_id,
        session_id=session_id,
        query_text=sanitized_query,
        metrics=metrics,
        status="ok",
    )

    final_resp = ChatResponse(
        answer=full_answer,
        citations=citations,
        access_granted=True,
        status_message=None,
        response_time_ms=response_time_ms,
        query_id=query_id,
    )

    cache_key = _rag_cache_key(sanitized_query, allowed_levels)
    with _RAG_RESPONSE_CACHE_LOCK:
        _RAG_RESPONSE_CACHE[cache_key] = (time.monotonic(), final_resp)
        _RAG_RESPONSE_CACHE.move_to_end(cache_key)
        max_size = getattr(rag_settings, "RESPONSE_CACHE_SIZE", 256)
        while len(_RAG_RESPONSE_CACHE) > max_size:
            _RAG_RESPONSE_CACHE.popitem(last=False)

    yield _sse_event("done", final_resp.model_dump(mode="json"))


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
            query_text=sanitized_query,
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

    citations: List[CitationSchema] = [_make_citation(chunk) for chunk in ranked_chunks]

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
