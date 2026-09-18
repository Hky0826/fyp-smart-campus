"""Unit tests for Gemini retry handling and in-flight request deduplication."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from RagChatbot.gemini_client import (
    InFlightDeduplicator,
    acall_with_retry,
    call_with_retry,
    is_retryable_gemini_error,
)


class MockGeminiClientError(Exception):
    """Simulates google.genai.errors.ClientError."""
    def __init__(self, code: int, message: str = "", status: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def test_is_retryable_gemini_error():
    assert is_retryable_gemini_error(MockGeminiClientError(code=409, message="Conflict"))
    assert is_retryable_gemini_error(MockGeminiClientError(code=429, message="Resource exhausted"))
    assert is_retryable_gemini_error(MockGeminiClientError(code=503, message="Unavailable"))
    assert is_retryable_gemini_error(Exception("409 Conflict: resource aborted"))
    assert is_retryable_gemini_error(Exception("gRPC status ABORTED"))
    assert is_retryable_gemini_error(Exception("Failed to connect to stream"))
    assert is_retryable_gemini_error(Exception("Session already exists"))
    assert not is_retryable_gemini_error(MockGeminiClientError(code=400, message="Bad Request"))
    assert not is_retryable_gemini_error(MockGeminiClientError(code=404, message="Not Found"))
    assert not is_retryable_gemini_error(ValueError("invalid value"))


def test_call_with_retry_succeeds_first_try():
    fn = MagicMock(return_value="success")
    result = call_with_retry(fn, "arg1", kw="val", max_retries=3, initial_delay=0.01)
    assert result == "success"
    assert fn.call_count == 1


def test_call_with_retry_recovers_after_409():
    call_count = 0

    def flaky_call():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise MockGeminiClientError(code=409, message="Aborted: concurrent call collision")
        return "recovered"

    result = call_with_retry(flaky_call, max_retries=3, initial_delay=0.01)
    assert result == "recovered"
    assert call_count == 3


def test_call_with_retry_fails_immediately_on_non_retryable_error():
    fn = MagicMock(side_effect=MockGeminiClientError(code=400, message="Bad Request"))
    with pytest.raises(MockGeminiClientError):
        call_with_retry(fn, max_retries=3, initial_delay=0.01)
    assert fn.call_count == 1


def test_call_with_retry_exhausts_retries():
    fn = MagicMock(side_effect=MockGeminiClientError(code=409, message="Conflict"))
    with pytest.raises(MockGeminiClientError):
        call_with_retry(fn, max_retries=2, initial_delay=0.01)
    assert fn.call_count == 3  # initial + 2 retries


def test_in_flight_deduplicator_coalesces_concurrent_calls():
    dedup = InFlightDeduplicator()
    call_count = 0
    gate = threading.Event()

    def slow_call():
        nonlocal call_count
        call_count += 1
        gate.wait(timeout=2.0)
        return {"answer": "grounded_response", "count": call_count}

    results = []
    threads = []

    def worker():
        res = dedup.execute("identical_query_key", slow_call)
        results.append(res)

    # Launch 5 concurrent threads with identical key
    for _ in range(5):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    # Allow leader to run
    time.sleep(0.05)
    gate.set()

    for t in threads:
        t.join(timeout=3.0)

    assert len(results) == 5
    # The actual underlying function must have been called only ONCE
    assert call_count == 1
    # All 5 threads must have received the exact same response
    for r in results:
        assert r["answer"] == "grounded_response"
        assert r["count"] == 1


def test_in_flight_deduplicator_propagates_exceptions():
    dedup = InFlightDeduplicator()
    gate = threading.Event()

    def failing_call():
        gate.wait(timeout=2.0)
        raise RuntimeError("API failure")

    errors = []
    threads = []

    def worker():
        try:
            dedup.execute("failing_key", failing_call)
        except Exception as exc:
            errors.append(exc)

    for _ in range(3):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    time.sleep(0.05)
    gate.set()

    for t in threads:
        t.join(timeout=3.0)

    assert len(errors) == 3
    for err in errors:
        assert isinstance(err, RuntimeError)
        assert str(err) == "API failure"


@pytest.mark.anyio
async def test_acall_with_retry_recovers_after_409():
    call_count = 0

    async def flaky_async_call():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise MockGeminiClientError(code=409, message="Aborted: conflict")
        return "async_recovered"

    res = await acall_with_retry(flaky_async_call, max_retries=3, initial_delay=0.01)
    assert res == "async_recovered"
    assert call_count == 3
