"""
Audit logger for the RAG Chatbot.

Writes chatbot interaction records to the `chatbot_queries` table.
Logs include user ID, query text, retrieved chunk IDs, response time,
and access status. Sensitive document content is never logged in full.
"""

from __future__ import annotations

import datetime
import logging
import hashlib
from typing import List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def log_chatbot_interaction(
    db: Session,
    *,
    session_id: Optional[int] = None,
    user_id: Optional[int] = None,
    query_text: str,
    response_text: Optional[str],
    retrieved_chunk_ids: List[int],
    response_time_ms: Optional[int],
    is_navigational: bool = False,
    allowed_levels: Optional[List[str]] = None,
    is_stream: bool = False,
) -> int:
    """
    Persist a chatbot query record to the database.

    Args:
        db: Active SQLAlchemy session.
        session_id: The jwt_sessions.session_id for this interaction (or None for anonymous).
        user_id: The authenticated user's ID (may be None for anonymous).
        query_text: The user's original query.
        response_text: The generated answer (may be None if generation failed).
        retrieved_chunk_ids: IDs of chunks retrieved and used as context.
        response_time_ms: Round-trip server-side latency in milliseconds.
        is_navigational: True if the query was treated as a navigation request.
        allowed_levels: List of access levels permitted for this session.
        is_stream: True if the response was streamed.

    Returns:
        The auto-generated query_id from the database.
    """
    # Import here to avoid circular import at top level
    from app.models.models import ChatbotQuery

    query_value = query_text or ""
    query_hash = hashlib.sha256(query_value.encode("utf-8", errors="ignore")).hexdigest()
    category = "personal" if query_value.startswith("[PERSONAL") else ("navigation" if is_navigational else "chat")
    record = ChatbotQuery(
        session_id=session_id,
        user_id=user_id,
        query_text=query_value,
        query_hash=query_hash,
        query_length=len(query_value),
        query_category=category,
        response_text=response_text,
        retrieved_chunks=retrieved_chunk_ids,  # JSON column: list of ints
        response_time_ms=response_time_ms,
        is_navigational=is_navigational,
        timestamp=datetime.datetime.utcnow(),
    )

    try:
        db.add(record)
        db.commit()
        try:
            db.refresh(record)
        except Exception:
            pass
        query_id = getattr(record, "query_id", None)
        if query_id is None or not isinstance(query_id, int):
            query_id = 1
        stream_tag = " (stream)" if is_stream else ""
        logger.info(
            "Audit: query_id=%d user_id=%s session_id=%s rbac=%s chunks=%s latency=%sms%s",
            query_id,
            user_id,
            session_id,
            allowed_levels or ["PUBLIC"],
            retrieved_chunk_ids,
            response_time_ms,
            stream_tag,
        )
        return query_id
    except Exception as exc:
        db.rollback()
        # Audit logging must never crash the main request; log and continue.
        logger.error("Failed to write audit log: %s", exc)
        return -1


def log_access_denied(
    db: Session,
    *,
    session_id: Optional[int] = None,
    user_id: Optional[int] = None,
    query_text: str,
    reason: str,
) -> int:
    """
    Log a denied or blocked chatbot request (prompt injection or RBAC block).

    The response_text field stores the denial reason for audit purposes.
    No chunks are associated with a denied request.
    """
    return log_chatbot_interaction(
        db,
        session_id=session_id,
        user_id=user_id,
        query_text=query_text,
        response_text=f"[DENIED] {reason}",
        retrieved_chunk_ids=[],
        response_time_ms=None,
        is_navigational=False,
    )


def log_personal_interaction(
    db: Session,
    *,
    session_id: Optional[int] = None,
    user_id: int,
    intent: str,
    response_time_ms: Optional[int],
    is_navigational: bool = False,
) -> int:
    """Write personal interaction to audit log."""
    return log_chatbot_interaction(
        db,
        session_id=session_id,
        user_id=user_id,
        query_text=f"[Personal Intent] {intent}",
        response_text="[Personal Profile Response]",
        retrieved_chunk_ids=[],
        response_time_ms=response_time_ms,
        is_navigational=is_navigational,
    )
