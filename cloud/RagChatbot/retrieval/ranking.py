"""
Re-ranking utilities for retrieved document chunks.

After vector similarity and lexical retrieval, candidate chunks are:
1. Filtered against the minimum similarity threshold (RAG_SIMILARITY_THRESHOLD)
2. Filtered against non-stopword domain keywords and entity tags
3. Optionally re-scored and re-ranked using lightweight cross-scoring
4. Trimmed to TOP_K_CONTEXT before being formatted for LLM generation.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict

from google.genai import types

from RagChatbot.config import rag_settings
from RagChatbot.gemini_client import get_gemini_client
from RagChatbot.embeddings.embedding_utils import cosine_similarity

logger = logging.getLogger(__name__)

_COMMON_STOPWORDS = {
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "that", "this", "these", "those", "have", "from", "with", "your", "about",
    "tell", "give", "step", "show", "some", "more", "make", "making", "many",
    "into", "over", "after", "before", "their", "them", "then", "there", "they",
    "city", "best", "good", "like", "just", "know", "help", "need", "want", "find"
}


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
    access_level: str = "VISITOR"
    allowed_roles: Optional[List[str]] = field(default_factory=lambda: ["VISITOR"])
    similarity_score: float = 0.0
    chunk_type: str = "DETAIL"
    section_path: Optional[str] = None
    entity_tags: Optional[List[Dict[str, Any]]] = field(default_factory=list)
    parent_chunk_id: Optional[int] = None


def _has_significant_keyword_match(query_text: str, chunk_text: str, entity_tags: Optional[List[Dict[str, Any]]] = None) -> bool:
    """Check if query contains specific domain identifiers, acronyms, course codes, or entity tags."""
    if not query_text:
        return False
    
    # Check entity tags directly
    if entity_tags:
        query_upper = query_text.upper()
        for tag in entity_tags:
            code = tag.get("entity_code") or tag.get("label") or tag.get("name") or ""
            if code and len(code) >= 3 and code.upper() in query_upper:
                return True

    words = re.findall(r"[A-Za-z0-9_\-]+", query_text)
    chunk_lower = chunk_text.lower() if chunk_text else ""
    for w in words:
        w_lower = w.lower()
        if w_lower in _COMMON_STOPWORDS or len(w_lower) <= 3:
            continue
        is_code = bool(re.match(r"^[a-zA-Z]{2,4}[0-9]{2,4}", w_lower) or re.match(r"^[a-zA-Z]-[0-9]", w_lower))
        if is_code and w_lower in chunk_lower:
            return True
        if len(w_lower) >= 6 and f" {w_lower} " in f" {chunk_lower} ":
            return True
    return False


def _llm_cross_rerank(query_text: str, candidates: List[RankedChunk], top_k: int) -> List[RankedChunk]:
    """
    Lightweight zero-dependency cross-encoder using Gemini Flash-Lite.
    Scores relevance of candidates against the query and reorders them.
    """
    if not candidates or not query_text or len(candidates) <= 1:
        return candidates[:top_k]

    pool = candidates[:8]
    candidate_prompts = []
    for idx, c in enumerate(pool):
        snippet = " ".join(c.chunk_text.split()[:60])
        candidate_prompts.append(f"[{idx}] (Doc: {c.document_title}): {snippet}")

    system_instruction = (
        "You are an expert retrieval reranker. Given a query and candidate passages, "
        "reorder the passage indices [0, 1, 2, ...] in descending order of relevance. "
        "Return ONLY a JSON array of the most relevant indices, e.g. [2, 0, 1]."
    )

    try:
        client = get_gemini_client()
        content = f"Query: {query_text}\n\nPassages:\n" + "\n\n".join(candidate_prompts)
        response = client.models.generate_content(
            model=rag_settings.PLANNER_MODEL,
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=64,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        raw_text = (response.text or "").strip()
        ordered_indices = json.loads(raw_text)
        if isinstance(ordered_indices, list):
            reranked: List[RankedChunk] = []
            seen = set()
            for idx in ordered_indices:
                if isinstance(idx, int) and 0 <= idx < len(pool) and idx not in seen:
                    reranked.append(pool[idx])
                    seen.add(idx)
            for idx, c in enumerate(pool):
                if idx not in seen:
                    reranked.append(c)
            return reranked[:top_k]
    except Exception as exc:
        logger.debug("LLM cross-reranking failed or skipped (%s); using similarity order.", exc)

    return candidates[:top_k]


def rerank_chunks(
    chunks: List[Any],
    query_embedding: Optional[List[float]] = None,
    top_k: int = 5,
    query_text: Optional[str] = None,
    score_map: Optional[dict[int, float]] = None,
) -> List[RankedChunk]:
    """
    Re-score retrieved chunks using in-memory precomputed scores (or cosine similarity),
    filter by RAG_SIMILARITY_THRESHOLD, optionally apply cross-encoder reranking,
    and return the top-k highest scoring chunks.
    """
    scored: List[RankedChunk] = []
    min_threshold = getattr(rag_settings, "RAG_SIMILARITY_THRESHOLD", 0.50)

    for row in chunks:
        try:
            cid = getattr(row, "chunk_id", None)
            if score_map and cid in score_map:
                score = score_map[cid]
            elif query_embedding is not None and hasattr(row, "chunk_embedding"):
                raw_emb = row.chunk_embedding
                if isinstance(raw_emb, str):
                    chunk_vec: List[float] = json.loads(raw_emb)
                elif isinstance(raw_emb, list):
                    chunk_vec = raw_emb
                else:
                    score = 0.50
                score = cosine_similarity(query_embedding, chunk_vec)
            else:
                score = 0.60

            c_text = getattr(row, "chunk_text", "")
            raw_tags = getattr(row, "entity_tags", None)
            if isinstance(raw_tags, str):
                try:
                    parsed_tags = json.loads(raw_tags)
                except Exception:
                    parsed_tags = []
            elif isinstance(raw_tags, list):
                parsed_tags = raw_tags
            raw_roles = getattr(row, "allowed_roles", None)
            if isinstance(raw_roles, str):
                try:
                    parsed_roles = json.loads(raw_roles)
                except Exception:
                    parsed_roles = [raw_roles]
            elif isinstance(raw_roles, (list, set, tuple)):
                parsed_roles = list(raw_roles)
            else:
                parsed_roles = ["VISITOR"]

            has_keyword = _has_significant_keyword_match(query_text or "", c_text, entity_tags=parsed_tags)

            if score >= min_threshold or (has_keyword and score >= 0.35):
                scored.append(
                    RankedChunk(
                        chunk_id=getattr(row, "chunk_id", 0),
                        document_id=getattr(row, "document_id", 0),
                        document_title=getattr(row, "document_title", ""),
                        chunk_index=getattr(row, "chunk_index", 0),
                        chunk_text=c_text,
                        access_level=getattr(row, "access_level", "VISITOR"),
                        allowed_roles=parsed_roles,
                        similarity_score=score,
                        chunk_type=str(getattr(row, "chunk_type", "DETAIL") or "DETAIL"),
                        section_path=getattr(row, "section_path", None),
                        entity_tags=parsed_tags,
                        parent_chunk_id=getattr(row, "parent_chunk_id", None),
                    )
                )
        except Exception as exc:
            logger.warning("Error scoring candidate chunk: %s", exc)

    scored.sort(key=lambda item: item.similarity_score, reverse=True)

    if getattr(rag_settings, "RAG_CROSS_RERANKING_ENABLED", False) and query_text and len(scored) > 1:
        return _llm_cross_rerank(query_text=query_text, candidates=scored, top_k=top_k)

    return scored[:top_k]
