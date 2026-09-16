"""
Singleton Google GenAI client for the RAG Chatbot module.

Provides thread-safe access to a single persistent genai.Client instance,
reducing connection setup overhead and latency across requests.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable
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


def is_retryable_gemini_error(exc: Exception) -> bool:
    """
    Check if an exception is a transient error from Google AI Studio / Gemini API.

    Specifically targets:
      - 409 Conflict / ABORTED (concurrency conflict or duplicate request race condition)
      - 429 Resource Exhausted / Rate Limit
      - 500, 502, 503, 504 Service Unavailable / Backend Server Errors
    """
    if exc is None:
        return False

    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and code in (409, 429, 500, 502, 503, 504):
        return True

    status = getattr(exc, "status", None)
    if status and str(status).upper() in {
        "ABORTED", "CONFLICT", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED"
    }:
        return True

    try:
        from google.genai import errors
        if isinstance(exc, errors.APIError):
            return True
    except ImportError:
        pass

    try:
        from google.api_core import exceptions as g_exc
        if isinstance(exc, (
            g_exc.Conflict,
            g_exc.Aborted,
            g_exc.ResourceExhausted,
            g_exc.ServiceUnavailable,
            g_exc.DeadlineExceeded,
        )):
            return True
    except ImportError:
        pass

    err_str = str(exc).lower()
    retry_markers = (
        "409", "conflict", "aborted",
        "429", "resource_exhausted", "resource exhausted", "resourceexhausted", "too many requests", "rate limit",
        "500", "502", "503", "504", "service unavailable", "unavailable",
        "concurrent", "already exists", "race condition",
    )
    return any(marker in err_str for marker in retry_markers)


def call_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 0.3,
    backoff_factor: float = 2.0,
    **kwargs: Any,
) -> Any:
    """
    Execute a callable that calls Google AI Studio / Gemini with exponential backoff & jitter.

    Resolves transient 409 Conflict (ABORTED) race conditions, 429 rate limits,
    and temporary service unavailability. Performs up to `max_retries` additional
    attempts after the initial failure.
    """
    import random
    import time

    delay = initial_delay
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries and is_retryable_gemini_error(exc):
                # Add +-25% random jitter to avoid thundering herd on re-collision
                jitter = delay * 0.25 * (random.random() * 2 - 1)
                sleep_time = max(0.01, delay + jitter)
                logger.warning(
                    "Google AI Studio call encountered transient error (%s); retrying in %.2fs (retry %d/%d)",
                    exc,
                    sleep_time,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(sleep_time)
                delay *= backoff_factor
            else:
                raise last_exc

    if last_exc is not None:
        raise last_exc


def generate_content_with_retry(
    client: genai.Client,
    *,
    model: str,
    contents: Any,
    config: Any = None,
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    """Convenience wrapper for client.models.generate_content with retry on 409/429/503."""
    call_kwargs = {"model": model, "contents": contents, **kwargs}
    if config is not None:
        call_kwargs["config"] = config
    return call_with_retry(
        client.models.generate_content,
        max_retries=max_retries,
        **call_kwargs,
    )


def generate_content_stream_with_retry(
    client: genai.Client,
    *,
    model: str,
    contents: Any,
    config: Any = None,
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    """Convenience wrapper for client.models.generate_content_stream with retry on 409/429/503."""
    call_kwargs = {"model": model, "contents": contents, **kwargs}
    if config is not None:
        call_kwargs["config"] = config
    return call_with_retry(
        client.models.generate_content_stream,
        max_retries=max_retries,
        **call_kwargs,
    )


class _InFlightEntry:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[Exception] = None


class InFlightDeduplicator:
    """
    Coalesces concurrent duplicate calls so that only one in-flight request
    hits Google AI Studio, preventing concurrency race conditions and 409 Conflict.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, _InFlightEntry] = {}

    def execute(self, key: str, fn: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._entries:
                entry = self._entries[key]
                is_leader = False
            else:
                entry = _InFlightEntry()
                self._entries[key] = entry
                is_leader = True

        if not is_leader:
            logger.info("Coalescing concurrent in-flight request for key=%.32s; awaiting active call", key)
            finished = entry.event.wait(timeout=45.0)
            if not finished:
                logger.warning("In-flight leader timed out for key=%.32s; executing independent call", key)
                return fn()
            if entry.error is not None:
                raise entry.error
            return entry.result

        try:
            result = fn()
            entry.result = result
            return result
        except Exception as exc:
            entry.error = exc
            raise
        finally:
            with self._lock:
                self._entries.pop(key, None)
            entry.event.set()


in_flight_deduplicator = InFlightDeduplicator()

