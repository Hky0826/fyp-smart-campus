"""
Document retriever using MySQL 9 native VECTOR type and in-memory hybrid search.

Implements Parent-Child Context Expansion:
- Dense & lexical search operates on small, precise child/summary chunks.
- When child chunks match, the retriever hydrates and delivers the complete PARENT section context
  (1,500 - 2,500 chars) to the LLM to eliminate rule truncation and table fragmentation.
- Supports faceted SQL & in-memory pre-filtering (Category, Faculty, Target Audience, Chunk Type).
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from RagChatbot.config import rag_settings
from RagChatbot.retrieval.access_filter import filter_chunks_by_access
from RagChatbot.retrieval.ranking import RankedChunk, rerank_chunks

logger = logging.getLogger(__name__)


def retrieve_chunks(
    query_embedding: List[float],
    allowed_access_levels: List[str],
    db: Session,
    top_k_retrieval: int | None = None,
    top_k_context: int | None = None,
    query_text: str | None = None,
    category: Optional[str] = None,
    faculty_code: Optional[str] = None,
    target_audience: Optional[str] = None,
    chunk_types: Optional[List[str]] = None,
    is_broad_overview: bool = False,
) -> List[RankedChunk]:
    """
    Retrieve, hydrate parent contexts, and rank the most relevant authorized document chunks.
    """
    k_ret = top_k_retrieval or rag_settings.TOP_K_RETRIEVAL
    k_ctx = top_k_context or rag_settings.TOP_K_CONTEXT

    candidate_limit = k_ret * 3

    if not allowed_access_levels:
        logger.warning("Retrieval called with empty allowed_access_levels; returning empty.")
        return []

    from RagChatbot.retrieval.vector_store import vector_store

    if not vector_store.is_loaded:
        logger.warning("Vector store not loaded, attempting to load from DB...")
        vector_store.load_from_db(db)
        if not vector_store.is_loaded:
            logger.warning("Vector store still empty after load attempt, returning empty.")
            return []

    if getattr(rag_settings, "RAG_HYBRID_SEARCH_ENABLED", True) and query_text:
        scored_candidates = vector_store.search_hybrid_with_scores(
            query_text=query_text,
            query_embedding=query_embedding,
            allowed_access_levels=allowed_access_levels,
            top_k=candidate_limit,
            dense_weight=getattr(rag_settings, "RAG_HYBRID_DENSE_WEIGHT", 0.7),
            lexical_weight=getattr(rag_settings, "RAG_HYBRID_LEXICAL_WEIGHT", 0.3),
            category=category,
            faculty_code=faculty_code,
            target_audience=target_audience,
            chunk_types=chunk_types,
            prefer_summary=is_broad_overview,
        )
    else:
        scored_candidates = vector_store.search_with_scores(
            query_embedding=query_embedding,
            allowed_access_levels=allowed_access_levels,
            top_k=candidate_limit,
            category=category,
            faculty_code=faculty_code,
            target_audience=target_audience,
            chunk_types=chunk_types,
            prefer_summary=is_broad_overview,
        )

    if not scored_candidates:
        logger.debug("Retrieval: no chunks found in vector store.")
        return []

    score_map = {cid: score for cid, score in scored_candidates}
    top_chunk_ids = [cid for cid, _ in scored_candidates]

    id_placeholders = ", ".join(f":id_{i}" for i in range(len(top_chunk_ids)))
    params = {f"id_{i}": cid for i, cid in enumerate(top_chunk_ids)}

    sql = text(f"""
        SELECT
            dc.chunk_id,
            dc.document_id,
            ud.title          AS document_title,
            dc.chunk_index,
            dc.chunk_text,
            COALESCE(dc.allowed_roles, ud.allowed_roles) AS allowed_roles,
            dc.access_level,
            COALESCE(dc.chunk_type, 'DETAIL') AS chunk_type,
            COALESCE(dc.parent_chunk_id, -1) AS parent_chunk_id,
            COALESCE(dc.section_path, '') AS section_path,
            dc.entity_tags
        FROM document_chunks dc
        INNER JOIN uploaded_documents ud
            ON dc.document_id = ud.document_id
           AND ud.is_active = 1
           AND dc.is_outdated = 0
        WHERE dc.chunk_id IN ({id_placeholders})
    """)

    try:
        rows = db.execute(sql, params).fetchall()
    except Exception as exc:
        logger.error("Retrieval SQL execution failed: %s", exc)
        return []

    if not rows:
        return []

    # Second safety layer: in-memory access filter
    safe_rows = filter_chunks_by_access(rows, allowed_access_levels)

    # ── Parent-Child Context Expansion ──────────────────────────────────────────
    # Fetch overarching parent chunk contexts for retrieved child chunks
    parent_ids_to_fetch = list({
        getattr(r, "parent_chunk_id")
        for r in safe_rows
        if getattr(r, "parent_chunk_id", -1) not in (None, -1, 0)
    })

    parent_map: Dict[int, Any] = {}
    if parent_ids_to_fetch:
        p_placeholders = ", ".join(f":pid_{i}" for i in range(len(parent_ids_to_fetch)))
        p_params = {f"pid_{i}": pid for i, pid in enumerate(parent_ids_to_fetch)}
        p_sql = text(f"""
            SELECT chunk_id, chunk_text, section_path, entity_tags, allowed_roles
            FROM document_chunks
            WHERE chunk_id IN ({p_placeholders})
        """)
        try:
            p_rows = db.execute(p_sql, p_params).fetchall()
            for p in p_rows:
                parent_map[p.chunk_id] = p
        except Exception as exc:
            logger.warning("Failed to hydrate parent chunks: %s", exc)

    # Transform child rows into expanded context items
    expanded_items: List[Any] = []
    seen_parent_ids = set()

    for r in safe_rows:
        pid = getattr(r, "parent_chunk_id", -1)
        if pid in parent_map:
            # If parent context exists, hydrate parent context block
            parent_row = parent_map[pid]
            # Avoid duplicating identical parent block multiple times in prompt context
            if pid in seen_parent_ids:
                continue
            seen_parent_ids.add(pid)

            # Build mock object with parent text but preserving child score
            class ExpandedChunk:
                def __init__(self, child, parent):
                    self.chunk_id = child.chunk_id
                    self.document_id = child.document_id
                    self.document_title = child.document_title
                    self.chunk_index = child.chunk_index
                    self.chunk_text = parent.chunk_text  # Expanded rich context
                    self.access_level = getattr(child, "access_level", "VISITOR")
                    self.allowed_roles = getattr(child, "allowed_roles", None) or getattr(parent, "allowed_roles", ["VISITOR"])
                    self.chunk_type = child.chunk_type
                    self.section_path = parent.section_path or child.section_path
                    self.entity_tags = child.entity_tags or parent.entity_tags
                    self.parent_chunk_id = pid

            expanded_items.append(ExpandedChunk(r, parent_row))
        else:
            expanded_items.append(r)

    # Re-rank candidates and trim to context window size
    ranked = rerank_chunks(expanded_items, score_map=score_map, top_k=k_ctx, query_text=query_text)
    return ranked
