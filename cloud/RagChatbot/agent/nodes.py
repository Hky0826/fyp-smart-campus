"""Atomic execution nodes for the Agentic RAG graph."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None  # type: ignore
    types = None  # type: ignore

try:
    from sqlalchemy.orm import Session
except ImportError:
    Session = Any  # type: ignore

from RagChatbot.agent.state import AgentState, SubGoal
from RagChatbot.config import rag_settings
from RagChatbot.embeddings.google_embedding_service import embed_text
from RagChatbot.gemini_client import get_gemini_client
from RagChatbot.generation.prompt_builder import build_context_block, build_prompt
from RagChatbot.retrieval.retriever import retrieve_chunks
from RagChatbot.retrieval.ranking import RankedChunk
from RagChatbot.schemas import CitationSchema
from RagChatbot.services.map_service import calculate_navigation, is_navigation_query
from RagChatbot.personalisation.intents import parse_personal_intent
from RagChatbot.personalisation.service import handle_personal_request
from RagChatbot.personalisation.schemas import PersonalIntent

logger = logging.getLogger(__name__)


def decompose_query_node(state: AgentState, db: Optional[Session] = None) -> AgentState:
    """Classifies query complexity and splits compound queries into atomic sub-goals using gemini-3.1-flash-lite."""
    query = state.user_query.strip()
    
    # Fast path detection for trivial short single-fact questions
    words = query.split()
    is_compound = any(w in query.lower() for w in [" and ", " also ", " compare ", " as well as ", " besides ", " plus "]) or len(words) > 14
    
    if not is_compound and getattr(rag_settings, "AGENT_FAST_PATH_ENABLED", True):
        state.is_fast_path = True
        state.sub_goals = [SubGoal(query=query)]
        state.acoustic_bridge = "Checking university records for you..."
        return state

    prompt = f"""You are a query planner for a university assistant. Analyze the user request.
Decompose compound requests into 1 to 3 atomic sub-questions. 
For each sub-question, optionally identify the faculty (FOCS, FOHS, FOBP, FEST, GENERAL) or category (ADMISSIONS, FEES_SCHOLARSHIPS, PROGRAMMES, POLICIES, FACILITIES, GENERAL).
Also generate a short natural spoken acoustic bridge (max 8 words, e.g. "Let me check the fees and requirements for you.") to speak while checking.

User Query: "{query}"

Return JSON only matching this format:
{{
  "acoustic_bridge": "Let me check that across university records...",
  "sub_goals": [
    {{"query": "sub-question 1", "category": "CATEGORY_OR_NULL", "faculty_code": "FACULTY_OR_NULL"}}
  ]
}}
"""
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=rag_settings.AGENT_DECOMPOSER_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=300,
            ),
        )
        data = json.loads(response.text.strip())
        state.acoustic_bridge = data.get("acoustic_bridge", "Let me check that for you...")
        sub_goals_data = data.get("sub_goals", [])
        
        if sub_goals_data:
            state.sub_goals = [
                SubGoal(
                    query=g.get("query", query),
                    category=g.get("category"),
                    faculty_code=g.get("faculty_code"),
                )
                for g in sub_goals_data
            ]
        else:
            state.sub_goals = [SubGoal(query=query)]
    except Exception as exc:
        logger.warning("Query decomposition fallback to single sub-goal: %s", exc)
        state.sub_goals = [SubGoal(query=query)]
        state.acoustic_bridge = "Checking university information for you..."
        
    return state


def retrieve_and_hydrate_node(state: AgentState, db: Session) -> AgentState:
    """Retrieves and hydrates parent chunk contexts for each sub-goal."""
    all_chunks_dict: Dict[int, RankedChunk] = {}
    
    for sub_goal in state.sub_goals:
        try:
            q_emb = embed_text(sub_goal.query)
            chunks = retrieve_chunks(
                query_embedding=q_emb,
                allowed_access_levels=state.allowed_access_levels,
                db=db,
                query_text=sub_goal.query,
                category=sub_goal.category if sub_goal.category not in ("NULL", "null", "") else None,
                faculty_code=sub_goal.faculty_code if sub_goal.faculty_code not in ("NULL", "null", "") else None,
                top_k_retrieval=rag_settings.TOP_K_RETRIEVAL,
                top_k_context=rag_settings.TOP_K_CONTEXT,
            )
            sub_goal.retrieved_chunks = chunks
            for c in chunks:
                if c.chunk_id not in all_chunks_dict:
                    all_chunks_dict[c.chunk_id] = c
        except Exception as exc:
            logger.error("Sub-goal retrieval failed for '%s': %s", sub_goal.query, exc)
            sub_goal.retrieved_chunks = []
            
    # Preserve score ordering
    sorted_chunks = sorted(all_chunks_dict.values(), key=lambda x: getattr(x, "similarity_score", getattr(x, "final_score", 0.0)), reverse=True)
    state.all_retrieved_chunks = sorted_chunks[:rag_settings.TOP_K_CONTEXT]
    return state


def grade_documents_node(state: AgentState) -> AgentState:
    """Fast binary evaluation of chunk relevance using gemini-3.1-flash-lite."""
    if not state.all_retrieved_chunks:
        for sg in state.sub_goals:
            sg.is_relevant = False
        return state

    # If similarity score is very high (> 0.70), fast-grade as relevant to save LLM tokens
    all_high_confidence = all(getattr(c, "similarity_score", getattr(c, "final_score", 0.0)) >= 0.70 for c in state.all_retrieved_chunks)
    if all_high_confidence:
        for sg in state.sub_goals:
            sg.is_relevant = True
        return state

    for sg in state.sub_goals:
        if not sg.retrieved_chunks:
            sg.is_relevant = False
            continue
            
        context_snippets = "\n".join(f"- {getattr(c, 'chunk_text', getattr(c, 'text', ''))[:250]}" for c in sg.retrieved_chunks[:3])
        prompt = f"""Grade whether the following document snippets contain relevant factual information to answer the question.
Question: "{sg.query}"
Snippets:
{context_snippets}

Return JSON with exact format: {{"relevant": true}} or {{"relevant": false}}
"""
        try:
            client = get_gemini_client()
            resp = client.models.generate_content(
                model=rag_settings.AGENT_GRADER_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    max_output_tokens=50,
                ),
            )
            res = json.loads(resp.text.strip())
            sg.is_relevant = bool(res.get("relevant", True))
        except Exception as exc:
            logger.debug("Grading fallback to True: %s", exc)
            sg.is_relevant = True

    return state


def rewrite_query_node(state: AgentState) -> AgentState:
    """Reformulates ambiguous or acronym-heavy sub-goals using gemini-3.1-flash-lite."""
    if state.rewrite_count >= rag_settings.AGENT_MAX_REWRITE_LOOPS:
        return state

    for sg in state.sub_goals:
        if not sg.is_relevant or not sg.retrieved_chunks:
            prompt = f"""The initial search for university information yielded low relevance. 
Rewrite the query into a more explicit, formal search query for university official documents. Expand acronyms (e.g. CS -> Computer Science, fees -> tuition fees and schedule).

Original Query: "{sg.query}"
Return JSON only: {{"rewritten_query": "..."}}
"""
            try:
                client = get_gemini_client()
                resp = client.models.generate_content(
                    model=rag_settings.AGENT_REWRITER_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                        max_output_tokens=100,
                    ),
                )
                data = json.loads(resp.text.strip())
                new_q = data.get("rewritten_query", "").strip()
                if new_q and new_q != sg.query:
                    logger.info("CRAG query rewriter: '%s' -> '%s'", sg.query, new_q)
                    sg.query = new_q
            except Exception as exc:
                logger.warning("Query rewriter failed: %s", exc)

    state.rewrite_count += 1
    return state


def execute_tools_node(state: AgentState, db: Session) -> AgentState:
    """Dispatches cross-domain tools (Navigation, Personal Timetable, Profile) if required."""
    query = state.user_query
    
    # 1. Navigation tool check
    if is_navigation_query(query):
        try:
            nav_result = calculate_navigation(query, state.auth_context, db)
            if nav_result and getattr(nav_result, "navigation", None):
                state.navigation_result = nav_result.navigation
                state.tool_results["navigation"] = nav_result.navigation
        except Exception as exc:
            logger.warning("Agent navigation tool execution error: %s", exc)

    # 2. Personal records / Timetable check
    personal_route = parse_personal_intent(query)
    if personal_route and getattr(personal_route, "intent", None) != PersonalIntent.UNKNOWN:
        try:
            p_result = handle_personal_request(personal_route, state.auth_context, db)
            if p_result:
                state.personal_result = p_result
                state.tool_results["personal"] = p_result
                state.response_scope = "PERSONAL"
        except Exception as exc:
            logger.warning("Agent personal tool execution error: %s", exc)

    return state


def synthesize_answer_node(state: AgentState) -> AgentState:
    """Synthesizes final grounded answer and citations using gemini-3.1-flash-lite."""
    # If personal tool already produced a full formatted personal response
    if state.personal_result and hasattr(state.personal_result, "answer") and state.personal_result.answer:
        state.final_answer = state.personal_result.answer
        state.access_granted = getattr(state.personal_result, "access_granted", True)
        return state

    # If no chunks found and no tool result
    if not state.all_retrieved_chunks and not state.tool_results:
        state.final_answer = "I could not find official information matching your query in the university records. Please check with the Admissions or Student Affairs department."
        state.access_granted = False
        state.status_message = "No relevant documents found."
        return state

    # Build context block from hydrated parent chunks
    context_text = build_context_block(state.all_retrieved_chunks)
    
    # Build citations
    citations: List[CitationSchema] = []
    for chunk in state.all_retrieved_chunks:
        citations.append(
            CitationSchema(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                chunk_index=chunk.chunk_index,
                access_level=chunk.access_level,
                excerpt=getattr(chunk, 'chunk_text', getattr(chunk, 'text', ''))[:200].replace("\n", " "),
            )
        )
    state.citations = citations

    tool_context_str = ""
    if state.navigation_result:
        dest = state.navigation_result.get("destination_label") or state.navigation_result.get("label", "Destination")
        tool_context_str += f"\n[Campus Navigation Info: Destination '{dest}' found on map]\n"

    system_prompt = f"""You are the official Smart Campus AI Assistant.
Provide a clear, accurate, and concise answer to the user query based ONLY on the verified context below.
If tools (like campus navigation or personal data) are included, seamlessly synthesize them into your response.
Do not invent fees, prerequisite rules, room locations, or requirements not present in the context.

Context:
{context_text}
{tool_context_str}
"""
    try:
        client = get_gemini_client()
        resp = client.models.generate_content(
            model=rag_settings.LLM_MODEL,
            contents=state.user_query,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=rag_settings.TEMPERATURE,
                max_output_tokens=rag_settings.MAX_OUTPUT_TOKENS,
            ),
        )
        state.final_answer = resp.text.strip()
        state.access_granted = True
    except Exception as exc:
        logger.error("Synthesis failed: %s", exc)
        state.final_answer = "An error occurred while generating the response. Please try again."
        state.status = "error"

    return state


def groundedness_critic_node(state: AgentState) -> AgentState:
    """Validates factual groundedness against retrieved citations using gemini-3.1-flash-lite."""
    if not getattr(rag_settings, "AGENT_GROUNDEDNESS_CHECK_ENABLED", True) or not state.final_answer or not state.all_retrieved_chunks:
        return state

    # Fast validation for short answers
    snippets = " ".join(getattr(c, 'chunk_text', getattr(c, 'text', ''))[:300] for c in state.all_retrieved_chunks[:3])
    prompt = f"""Check if the response makes factual claims contradicted or completely unsupported by the provided context.
Context:
{snippets}

Response:
{state.final_answer}

Return JSON format: {{"grounded": true, "confidence": 0.95}} or {{"grounded": false, "confidence": 0.50}}
"""
    try:
        client = get_gemini_client()
        resp = client.models.generate_content(
            model=rag_settings.AGENT_CRITIC_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=50,
            ),
        )
        data = json.loads(resp.text.strip())
        state.is_grounded = bool(data.get("grounded", True))
        state.groundedness_score = float(data.get("confidence", 1.0))
    except Exception as exc:
        logger.debug("Critic check skipped: %s", exc)
        state.is_grounded = True

    return state
