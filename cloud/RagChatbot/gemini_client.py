"""
Singleton Google GenAI client for the RAG Chatbot module.

Provides thread-safe access to a single persistent genai.Client instance,
reducing connection setup overhead and latency across requests.
"""

from __future__ import annotations

import logging
import threading
from google import genai
from google.genai import types

from RagChatbot.config import rag_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_client: genai.Client | None = None


def get_gemini_client(*, timeout_seconds: float | None = None) -> genai.Client:
    """
    Get or create the singleton genai.Client instance.

    Args:
        timeout_seconds: Optional request timeout in seconds. Defaults to 30s.

    Returns:
        The shared genai.Client instance.
    """
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                timeout_ms = int(timeout_seconds * 1000) if timeout_seconds else 30000
                _client = genai.Client(
                    api_key=rag_settings.GOOGLE_API_KEY,
                    http_options=types.HttpOptions(timeout=max(10000, timeout_ms)),
                )
                logger.debug("Initialized singleton Gemini client (timeout=%dms)", max(10000, timeout_ms))
    return _client


def reset_gemini_client() -> None:
    """Reset the singleton instance (primarily for testing)."""
    global _client
    with _lock:
        _client = None
