"""
Google AI Studio embedding service.

Generates dense vector embeddings for text using the configured
Google embedding model. The API key is loaded from config and is
never exposed to external callers.
"""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import logging
from threading import Lock
from typing import List

import google.generativeai as genai

from RagChatbot.config import rag_settings

logger = logging.getLogger(__name__)

_EMBEDDING_CACHE: OrderedDict[str, List[float]] = OrderedDict()
_EMBEDDING_CACHE_LOCK = Lock()


def _configure_client() -> None:
    """Configure the Google AI client (idempotent)."""
    genai.configure(api_key=rag_settings.GOOGLE_API_KEY)


def clear_embedding_cache() -> None:
    """Clear all cached query embeddings."""
    with _EMBEDDING_CACHE_LOCK:
        _EMBEDDING_CACHE.clear()


def embed_text(text: str) -> List[float]:
    """
    Generate a single embedding vector for the given text.
    Uses an in-memory thread-safe LRU cache to avoid redundant API calls.

    Args:
        text: The input string to embed (query or document chunk).

    Returns:
        A list of floats representing the embedding vector.

    Raises:
        ValueError: If the text is empty.
        RuntimeError: If the Google API call fails.
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text.")

    norm_text = " ".join(text.strip().lower().split())
    cache_key = hashlib.sha256(norm_text.encode("utf-8")).hexdigest()

    with _EMBEDDING_CACHE_LOCK:
        cached = _EMBEDDING_CACHE.get(cache_key)
        if cached is not None:
            _EMBEDDING_CACHE.move_to_end(cache_key)
            logger.debug("Embedding cache hit for query: %.40s", text)
            return list(cached)

    _configure_client()

    try:
        result = genai.embed_content(
            model=f"models/{rag_settings.EMBEDDING_MODEL}",
            content=text,
            task_type="retrieval_query",
        )
        embedding: List[float] = result["embedding"]
        logger.debug(
            "Embedded query (len=%d chars) -> vector dim=%d",
            len(text),
            len(embedding),
        )

        with _EMBEDDING_CACHE_LOCK:
            _EMBEDDING_CACHE[cache_key] = list(embedding)
            _EMBEDDING_CACHE.move_to_end(cache_key)
            max_size = getattr(rag_settings, "EMBEDDING_CACHE_SIZE", 512)
            while len(_EMBEDDING_CACHE) > max_size:
                _EMBEDDING_CACHE.popitem(last=False)

        return embedding
    except Exception as exc:
        logger.error("Google embedding API call failed: %s", exc)
        raise RuntimeError(f"Embedding generation failed: {exc}") from exc


def embed_document_chunk(chunk_text: str) -> List[float]:
    """
    Generate an embedding for a document chunk at ingestion time.

    Uses the 'retrieval_document' task type, which produces vectors
    better suited for the document side of asymmetric retrieval.

    Args:
        chunk_text: The document chunk text to embed.

    Returns:
        A list of floats representing the embedding vector.

    Raises:
        ValueError: If the chunk text is empty.
        RuntimeError: If the Google API call fails.
    """
    if not chunk_text or not chunk_text.strip():
        raise ValueError("Cannot embed empty chunk text.")

    _configure_client()

    try:
        result = genai.embed_content(
            model=f"models/{rag_settings.EMBEDDING_MODEL}",
            content=chunk_text,
            task_type="retrieval_document",
        )
        return result["embedding"]
    except Exception as exc:
        logger.error("Google document embedding API call failed: %s", exc)
        raise RuntimeError(f"Document embedding generation failed: {exc}") from exc
