"""Agentic RAG State Machine & Control Graph."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
try:
    from sqlalchemy.orm import Session
except ImportError:
    Session = Any  # type: ignore

from RagChatbot.agent.nodes import (
    decompose_query_node,
    execute_tools_node,
    grade_documents_node,
    groundedness_critic_node,
    retrieve_and_hydrate_node,
    rewrite_query_node,
    synthesize_answer_node,
)
from RagChatbot.agent.state import AgentState
from RagChatbot.config import rag_settings
from RagChatbot.personalisation.schemas import AuthenticatedChatContext
from RagChatbot.schemas import CitationSchema
from RagChatbot.security.rbac import get_allowed_access_levels_for_user

logger = logging.getLogger(__name__)


@dataclass
class AgentExecutionResult:
    """Consolidated result returned by the Agentic RAG graph."""
    answer: str
    citations: List[CitationSchema]
    access_granted: bool
    status: str
    status_message: Optional[str] = None
    acoustic_bridge: Optional[str] = None
    navigation_target: Optional[Dict[str, Any]] = None
    navigation: Optional[Dict[str, Any]] = None
    response_scope: str = "DOCUMENT"
    personal_intent: Optional[str] = None
    authentication_required: bool = False
    is_grounded: bool = True
    groundedness_score: float = 1.0
    latency_ms: int = 0
    step_timings: Dict[str, float] = None


def run_agentic_rag(
    query: str,
    auth_context: AuthenticatedChatContext,
    db: Session,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> AgentExecutionResult:
    """
    Executes the full Agentic RAG control graph:
    1. Resolve allowed RBAC access levels.
    2. Decompose complex compound query / classify complexity.
    3. Retrieve and hydrate parent-child document chunks.
    4. Grade document relevance (CRAG evaluation).
    5. Self-correct / rewrite query and re-retrieve if confidence is low (bounded to max 1 iteration).
    6. Execute cross-domain tools (Navigation, Timetable, Profile).
    7. Synthesize grounded answer.
    8. Check groundedness / hallucination guard.
    """
    start_time = time.monotonic()
    allowed_access_levels = get_allowed_access_levels_for_user(auth_context.user_id, db)
    
    state = AgentState(
        user_query=query,
        auth_context=auth_context,
        allowed_access_levels=allowed_access_levels,
        chat_history=chat_history,
    )
    
    timings: Dict[str, float] = {}

    # Step 1: Decomposition / Router
    t0 = time.monotonic()
    state = decompose_query_node(state, db=db)
    timings["decompose_ms"] = (time.monotonic() - t0) * 1000

    # Step 2: Initial Retrieval
    t0 = time.monotonic()
    state = retrieve_and_hydrate_node(state, db=db)
    timings["retrieval_ms"] = (time.monotonic() - t0) * 1000

    # Step 3: CRAG Relevance Grading
    t0 = time.monotonic()
    state = grade_documents_node(state)
    timings["grading_ms"] = (time.monotonic() - t0) * 1000

    # Step 4: Corrective Query Rewriting & Re-retrieval loop (if needed and within bounds)
    needs_rewrite = any(not sg.is_relevant for sg in state.sub_goals) and state.rewrite_count < rag_settings.AGENT_MAX_REWRITE_LOOPS
    if needs_rewrite:
        t0 = time.monotonic()
        state = rewrite_query_node(state)
        state = retrieve_and_hydrate_node(state, db=db)
        state = grade_documents_node(state)
        timings["rewrite_loop_ms"] = (time.monotonic() - t0) * 1000

    # Step 5: Cross-Domain Tools
    t0 = time.monotonic()
    state = execute_tools_node(state, db=db)
    timings["tools_ms"] = (time.monotonic() - t0) * 1000

    # Step 6: Synthesis
    t0 = time.monotonic()
    state = synthesize_answer_node(state)
    timings["synthesis_ms"] = (time.monotonic() - t0) * 1000

    # Step 7: Groundedness Critic
    t0 = time.monotonic()
    state = groundedness_critic_node(state)
    timings["critic_ms"] = (time.monotonic() - t0) * 1000

    total_latency_ms = int((time.monotonic() - start_time) * 1000)

    logger.info(
        "Agentic RAG execution finished in %d ms (sub_goals=%d, chunks=%d, rewrites=%d, grounded=%s)",
        total_latency_ms,
        len(state.sub_goals),
        len(state.all_retrieved_chunks),
        state.rewrite_count,
        state.is_grounded,
    )

    return AgentExecutionResult(
        answer=state.final_answer,
        citations=state.citations,
        access_granted=state.access_granted,
        status=state.status,
        status_message=state.status_message,
        acoustic_bridge=state.acoustic_bridge,
        navigation_target=state.navigation_result,
        navigation=state.navigation_result,
        response_scope=state.response_scope,
        personal_intent=None,
        authentication_required=state.authentication_required,
        is_grounded=state.is_grounded,
        groundedness_score=state.groundedness_score,
        latency_ms=total_latency_ms,
        step_timings=timings,
    )
