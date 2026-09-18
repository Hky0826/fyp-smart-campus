from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from RagChatbot.personalisation.schemas import AuthenticatedChatContext
from RagChatbot.services import process_user_request as request_module
from RagChatbot.services.chat_service import _RAG_RESPONSE_CACHE, _RAG_RESPONSE_CACHE_LOCK, _condense_query_with_history


def test_fast_voice_bypasses_flash_lite_classifier():
    """In fast_voice mode, UNIVERSITY_INFO queries bypass the remote Flash-Lite classifier."""
    db = MagicMock()
    fake_fast_res = {
        "status": "ok",
        "route": "UNIVERSITY_INFO",
        "answer": "Fast voice info about Bachelor of Computer Science.",
        "sources": [{"chunk_id": 101, "document_title": "CS Overview", "access_level": "PUBLIC"}],
    }

    with (
        patch.object(request_module, "_classify_with_flash_lite") as mock_classifier,
        patch.object(request_module, "resolve_auth_context", return_value=AuthenticatedChatContext(None, None)),
        patch("RagChatbot.generation.live_fast_rag.live_fast_rag.process_voice_query", return_value=fake_fast_res),
    ):
        result = request_module.process_user_request(
            transcript="Tell me about Bachelor of Computer Science",
            bearer_token=None,
            device_id="edge-test",
            session_id=None,
            db=db,
            fast_voice=True,
        )

    assert result["route"] == "UNIVERSITY_INFO"
    assert result["response_text"] == "Fast voice info about Bachelor of Computer Science."
    # Remote classifier should NOT be called because fast_voice fast-paths UNIVERSITY_INFO
    mock_classifier.assert_not_called()


def test_fast_voice_response_cache_hit():
    """Repeated voice query hits _RAG_RESPONSE_CACHE and returns in < 10ms without calling live_fast_rag."""
    db = MagicMock()
    fake_fast_res = {
        "status": "ok",
        "route": "UNIVERSITY_INFO",
        "answer": "Cached university overview.",
        "sources": [{"chunk_id": 202, "document_title": "QIU Info", "access_level": "PUBLIC"}],
    }

    # Clear cache before test
    with _RAG_RESPONSE_CACHE_LOCK:
        _RAG_RESPONSE_CACHE.clear()

    with (
        patch.object(request_module, "_classify_with_flash_lite"),
        patch.object(request_module, "resolve_auth_context", return_value=AuthenticatedChatContext(None, None)),
        patch("RagChatbot.generation.live_fast_rag.live_fast_rag.process_voice_query", return_value=fake_fast_res) as mock_live_rag,
    ):
        # 1st call: populates cache
        res1 = request_module.process_user_request(
            transcript="Can you tell me about QIU?",
            bearer_token=None,
            device_id="edge-test",
            session_id=None,
            db=db,
            fast_voice=True,
        )
        assert mock_live_rag.call_count == 1
        assert res1["response_text"] == "Cached university overview."

        # 2nd call: cache hit!
        t0 = time.monotonic()
        res2 = request_module.process_user_request(
            transcript="Can you tell me about QIU?",
            bearer_token=None,
            device_id="edge-test",
            session_id=None,
            db=db,
            fast_voice=True,
        )
        duration_ms = (time.monotonic() - t0) * 1000.0

        # live_fast_rag should NOT have been called again
        assert mock_live_rag.call_count == 1
        assert res2["response_text"] == "Cached university overview."
        assert duration_ms < 50.0  # Cache hit returns in sub-millisecond to few ms


def test_condense_query_bypasses_llm_for_substantive_degree_query():
    """Queries that already specify concrete degrees/programmes bypass the slow LLM rewriter."""
    history = [
        {"user": "Hello", "assistant": "Hi! How can I help?"},
    ]

    with patch("RagChatbot.gemini_client.generate_content_with_retry") as mock_gen:
        # A substantive query with "tell me more" but specifying "Bachelor of Computer Science"
        result = _condense_query_with_history(
            "Can you tell me more about Bachelor of Computer Science?",
            history=history,
        )
        # Should return without calling LLM
        mock_gen.assert_not_called()
        assert "Bachelor of Computer Science" in result
