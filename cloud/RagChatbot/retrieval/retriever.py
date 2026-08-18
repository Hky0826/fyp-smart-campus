"""
Document retriever using MySQL 9 native VECTOR type and in-memory hybrid search.

Distance computation and BM25 token matching are handled in Python with Reciprocal
Rank Fusion (RRF). RBAC filtering is applied in the in-memory index, in the SQL WHERE
clause, and in a post-retrieval access filter safety net.
"""

from __future__ import annotations

import logging
from typing import List

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
) -> List[RankedChunk]:
    """
    Retrieve and rank the most relevant authorized document chunks.

    Pipeline:
        1. Fetch candidate chunks from hybrid index (dense vectors + tokenized BM25)
           filtered by access_level.
        2. Hydrate chunk metadata and texts from MySQL with SQL-level RBAC filter.
        3. Apply in-memory access filter as a second RBAC safety layer.
        4. Re-rank candidates by cosine similarity & optional cross-encoder, trimming
           low-similarity chunks and enforcing context limits.
        5. Return the top_k_context highest-scoring chunks.

    Args:
        query_embedding: The embedded query vector (list of floats).
        allowed_access_levels: Access levels the current user may read.
        db: Active SQLAlchemy session.
        top_k_retrieval: Candidate pool size (overrides config).
        top_k_context: Final ranked chunks returned to the LLM (overrides config).
        query_text: Raw query text for hybrid lexical matching and cross-reranking.

    Returns:
        Ranked and filtered list of RankedChunk objects.
    """
    k_ret = top_k_retrieval or rag_settings.TOP_K_RETRIEVAL
    k_ctx = top_k_context or rag_settings.TOP_K_CONTEXT

    # Fetch a larger candidate pool so reranking has enough to choose from.
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
        )
    else:
        scored_candidates = vector_store.search_with_scores(query_embedding, allowed_access_levels, candidate_limit)

    if not scored_candidates:
        logger.debug("Retrieval: no chunks found in vector store.")
        return []

    score_map = {cid: score for cid, score in scored_candidates}
    top_chunk_ids = [cid for cid, _ in scored_candidates]

    id_placeholders = ", ".join(f":id_{i}" for i in range(len(top_chunk_ids)))
    params = {f"id_{i}": cid for i, cid in enumerate(top_chunk_ids)}
    access_placeholders = ", ".join(f":access_{i}" for i in range(len(allowed_access_levels)))
    params.update({f"access_{i}": level for i, level in enumerate(allowed_access_levels)})

    # Fast lightweight SQL query fetching only text and metadata without 3072-dim float embeddings
    sql = text(f"""
        SELECT
            dc.chunk_id,
            dc.document_id,
            ud.title          AS document_title,
            dc.chunk_index,
            dc.chunk_text,
            dc.access_level
        FROM document_chunks dc
        INNER JOIN uploaded_documents ud
            ON dc.document_id = ud.document_id
           AND ud.is_active = 1
           AND dc.is_outdated = 0
        WHERE dc.chunk_id IN ({id_placeholders})
          AND ud.access_level IN ({access_placeholders})
          AND dc.access_level IN ({access_placeholders})
    """)

    try:
        rows = db.execute(sql, params).fetchall()
    except Exception as exc:
        logger.error("Retrieval SQL execution failed: %s", exc)
        return []

    logger.debug(
        "Retrieval: fetched %d candidate rows from MySQL (access=%s)",
        len(rows),
        allowed_access_levels,
    )

    if not rows:
        return []

    # Second safety layer: in-memory access filter
    safe_rows = filter_chunks_by_access(rows, allowed_access_levels)
    if len(safe_rows) < len(rows):
        logger.warning(
            "Access filter removed %d unauthorized chunks post-SQL.",
            len(rows) - len(safe_rows),
        )

    # Re-rank candidates, apply similarity threshold, and trim to context window size
    ranked = rerank_chunks(safe_rows, score_map=score_map, top_k=k_ctx, query_text=query_text)
    return ranked
