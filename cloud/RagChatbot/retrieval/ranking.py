"""
Re-ranking utilities for retrieved document chunks.

After vector similarity retrieval, chunks are re-scored and trimmed to
the TOP_K_CONTEXT count before being sent to the LLM. Currently uses
cosine similarity re-ranking based on the query embedding. This module
can be extended with cross-encoder or BM25 re-ranking in the future.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, List

from RagChatbot.embeddings.embedding_utils import cosine_similarity

logger = logging.getLogger(__name__)


@dataclass
class RankedChunk:
    """
    A retrieved and ranked document chunk ready for LLM context building.
    """

    chunk_id: int
    document_id: int
    document_title: str
    chunk_index: int
    chunk_text: str
    access_level: str
    similarity_score: float


def rerank_chunks(
    chunks: List[Any],
    query_embedding: List[float],
    top_k: int,
) -> List[RankedChunk]:
    """
    Re-score retrieved chunks by cosine similarity to the query embedding,
    then return the top-k highest scoring chunks.

    Args:
        chunks: Raw result rows from the retriever. Each row is expected to
                have attributes: chunk_id, document_id, document_title,
                chunk_index, chunk_text, access_level, and chunk_embedding
                (a JSON string or list of floats).
        query_embedding: The query's embedding vector.
        top_k: Maximum number of chunks to return.

    Returns:
        List of RankedChunk objects sorted by descending similarity score.
    """
    scored: List[RankedChunk] = []

    for row in chunks:
        try:
            # chunk_embedding may arrive as a JSON string from MySQL
            raw_emb = row.chunk_embedding
            if isinstance(raw_emb, str):
                chunk_vec: List[float] = json.loads(raw_emb)
            elif isinstance(raw_emb, list):
                chunk_vec = raw_emb
            else:
                logger.warning("Unexpected embedding type for chunk_id=%s, skipping.", row.chunk_id)
                continue

            score = cosine_similarity(query_embedding, chunk_vec)

            scored.append(
                RankedChunk(
                    chunk_id=row.chunk_id,
                    document_id=row.document_id,
                    document_title=row.document_title or "Unknown Document",
                    chunk_index=row.chunk_index,
                    chunk_text=row.chunk_text,
                    access_level=row.access_level,
                    similarity_score=score,
                )
            )
        except Exception as exc:
            logger.error("Re-ranking failed for chunk_id=%s: %s", getattr(row, "chunk_id", "?"), exc)
            continue

    # Sort descending by score and trim to top_k
    scored.sort(key=lambda r: r.similarity_score, reverse=True)
    top = scored[:top_k]

    logger.debug(
        "Re-ranking: input=%d chunks, output=%d (top_k=%d)",
        len(chunks),
        len(top),
        top_k,
    )
    return top
