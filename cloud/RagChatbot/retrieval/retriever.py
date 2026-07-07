"""
Document retriever using MySQL 9 native VECTOR type.

MySQL 9.0.0 supports STRING_TO_VECTOR / VECTOR_TO_STRING / VECTOR_DIM
but does NOT include a standalone VECTOR_DISTANCE() function for use in
regular SELECT queries. Distance computation is therefore done entirely
in Python via cosine similarity after fetching candidate chunks.

RBAC filtering is applied in the SQL WHERE clause so unauthorized chunks
are never fetched. A second in-memory filter (access_filter) runs after
retrieval as a safety net.
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
) -> List[RankedChunk]:
    """
    Retrieve and rank the most relevant authorized document chunks.

    Pipeline:
        1. Fetch candidate chunks from MySQL filtered by access_level.
           Embeddings are read back via VECTOR_TO_STRING().
        2. Apply in-memory access filter as a second RBAC safety layer.
        3. Re-rank all candidates by cosine similarity to the query.
        4. Return the top_k_context highest-scoring chunks.

    Note on MySQL 9.0.0 compatibility:
        VECTOR_DISTANCE() does not exist in MySQL 9.0.0.
        All distance computation is handled in Python (cosine similarity).

    Args:
        query_embedding: The embedded query vector (list of floats).
        allowed_access_levels: Access levels the current user may read.
        db: Active SQLAlchemy session.
        top_k_retrieval: Candidate pool size fetched from MySQL (overrides config).
        top_k_context: Final ranked chunks returned to the LLM (overrides config).

    Returns:
        Ranked and filtered list of RankedChunk objects.
    """
    k_ret = top_k_retrieval or rag_settings.TOP_K_RETRIEVAL
    k_ctx = top_k_context or rag_settings.TOP_K_CONTEXT

    # Fetch a larger candidate pool so Python ranking has enough to choose from.
    # Multiply by 3 to mimic what SQL-side VECTOR_DISTANCE pre-filtering would do.
    candidate_limit = k_ret * 3

    if not allowed_access_levels:
        logger.warning("Retrieval called with empty allowed_access_levels; returning empty.")
        return []

    # Build the parameterized access-level IN clause
    placeholders = ", ".join(f":level_{i}" for i in range(len(allowed_access_levels)))
    level_params = {f"level_{i}": lv for i, lv in enumerate(allowed_access_levels)}

    sql = text(f"""
        SELECT
            dc.chunk_id,
            dc.document_id,
            ud.title          AS document_title,
            dc.chunk_index,
            dc.chunk_text,
            dc.access_level,
            VECTOR_TO_STRING(ev.embedding) AS chunk_embedding
        FROM embedding_vectors ev
        INNER JOIN document_chunks dc
            ON ev.chunk_id = dc.chunk_id
           AND dc.is_outdated = 0
        INNER JOIN uploaded_documents ud
            ON dc.document_id = ud.document_id
           AND ud.is_active = 1
        WHERE dc.access_level IN ({placeholders})
        LIMIT :k_ret
    """)

    params = {"k_ret": candidate_limit, **level_params}

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

    # Re-rank by cosine similarity and trim to context window size
    ranked = rerank_chunks(safe_rows, query_embedding, top_k=k_ctx)
    return ranked
