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

from google.genai import types

from RagChatbot.config import rag_settings
from RagChatbot.gemini_client import call_with_retry, get_gemini_client

logger = logging.getLogger(__name__)

_EMBEDDING_CACHE: OrderedDict[str, List[float]] = OrderedDict()
_EMBEDDING_CACHE_LOCK = Lock()


def _configure_client():
    """Return the singleton Google GenAI client."""
    return get_gemini_client()


def clear_embedding_cache() -> None:
    """Clear all cached query embeddings."""
    with _EMBEDDING_CACHE_LOCK:
        _EMBEDDING_CACHE.clear()


def _extract_single_embedding(result: object) -> List[float]:
    if isinstance(result, dict):
        return list(result.get("embedding") or [])
    embeddings = getattr(result, "embeddings", None) or []
    if not embeddings:
        return []
    return list(getattr(embeddings[0], "values", None) or [])


def _extract_batch_embeddings(result: object) -> List[List[float]]:
    if isinstance(result, dict):
        return [list(item) for item in (result.get("embedding") or [])]
    embeddings = getattr(result, "embeddings", None) or []
    return [list(getattr(item, "values", None) or []) for item in embeddings]


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

    client = get_gemini_client()

    try:
        result = call_with_retry(
            client.models.embed_content,
            model=rag_settings.EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
            max_retries=2,
        )
        embedding: List[float] = _extract_single_embedding(result)
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

    client = get_gemini_client()

    try:
        result = call_with_retry(
            client.models.embed_content,
            model=rag_settings.EMBEDDING_MODEL,
            contents=chunk_text,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            max_retries=2,
        )
        return _extract_single_embedding(result)
    except Exception as exc:
        logger.error("Google document embedding API call failed: %s", exc)
        raise RuntimeError(f"Document embedding generation failed: {exc}") from exc


def embed_document_chunks_batch(chunk_texts: List[str], batch_size: int = 50) -> List[List[float]]:
    """
    Generate embeddings for multiple document chunks in batched API calls.
    Drastically reduces HTTP roundtrips and avoids rate limits.
    """
    if not chunk_texts:
        return []

    client = get_gemini_client()
    embeddings: List[List[float]] = []

    for i in range(0, len(chunk_texts), batch_size):
        batch = chunk_texts[i:i + batch_size]
        try:
            result = call_with_retry(
                client.models.embed_content,
                model=rag_settings.EMBEDDING_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
                max_retries=2,
            )
            batch_embs = _extract_batch_embeddings(result)
            embeddings.extend(batch_embs)
            logger.debug("Batch embedded %d chunks (total so far: %d)", len(batch), len(embeddings))
        except Exception as exc:
            logger.warning("Batch embedding failed for batch %d..%d (%s); falling back to single calls", i, i + len(batch), exc)
            for text in batch:
                try:
                    embeddings.append(embed_document_chunk(text))
                except Exception as sub_exc:
                    logger.error("Single chunk embedding fallback failed: %s", sub_exc)
                    embeddings.append([])
    return embeddings

