"""Agent state and data transfer definitions for Agentic RAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from RagChatbot.personalisation.schemas import AuthenticatedChatContext
from RagChatbot.retrieval.ranking import RankedChunk
from RagChatbot.schemas import CitationSchema


@dataclass
class SubGoal:
    """An atomic sub-task decomposed from a complex compound query."""
    query: str
    category: Optional[str] = None
    faculty_code: Optional[str] = None
    target_audience: Optional[str] = None
    retrieved_chunks: List[RankedChunk] = field(default_factory=list)
    is_relevant: bool = True
    answer_draft: Optional[str] = None


@dataclass
class AgentState:
    """State tracking the lifecycle of an Agentic RAG execution graph."""
    user_query: str
    auth_context: AuthenticatedChatContext
    allowed_access_levels: List[str]
    chat_history: Optional[List[Dict[str, Any]]] = None

    # Decomposed sub-queries for multi-hop execution
    sub_goals: List[SubGoal] = field(default_factory=list)

    # Aggregated chunks & citations
    all_retrieved_chunks: List[RankedChunk] = field(default_factory=list)
    citations: List[CitationSchema] = field(default_factory=list)

    # Tool outcomes
    tool_results: Dict[str, Any] = field(default_factory=dict)
    navigation_result: Optional[Dict[str, Any]] = None
    personal_result: Optional[Any] = None

    # Agentic control metadata
    rewrite_count: int = 0
    is_fast_path: bool = False
    acoustic_bridge: Optional[str] = None

    # Final outputs
    final_answer: str = ""
    groundedness_score: float = 1.0
    is_grounded: bool = True
    status: str = "ok"
    status_message: Optional[str] = None
    access_granted: bool = True
    authentication_required: bool = False
    response_scope: str = "DOCUMENT"

    # Execution telemetry
    audit_events: List[Dict[str, Any]] = field(default_factory=list)
    step_timings: Dict[str, float] = field(default_factory=dict)
