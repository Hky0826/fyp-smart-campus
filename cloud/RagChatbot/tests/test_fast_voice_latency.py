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


def test_query_router_skips_llm_fallback_for_pharmacy_fees_and_chinese_fees(monkeypatch):
    """Academic/fee queries mentioning 'pharmacy' or non-English fee queries skip LLM nav fallback."""
    from RagChatbot.generation import query_router

    called = []

    class BoomClient:
        def __init__(self, **kwargs):
            called.append(kwargs)

    monkeypatch.setattr(query_router.genai, "Client", BoomClient)
    monkeypatch.setattr(query_router, "_load_destination_catalog", lambda db: [])

    res_en = query_router.classify_query("What are the tuition fees for Bachelor of Pharmacy?")
    res_zh = query_router.classify_query("计算机科学学费是多少？")
    res_ms = query_router.classify_query("Berapa yuran pengajian untuk kursus ini?")

    assert res_en.category == "UNIVERSITY_INFO"
    assert res_zh.category == "UNIVERSITY_INFO"
    assert res_ms.category == "UNIVERSITY_INFO"
    assert called == []


def test_fast_voice_skips_condense_query_and_forwards_allowed_levels():
    """In fast_voice mode, _condense_query_with_history is skipped and allowed_access_levels is forwarded."""
    db = MagicMock()
    fake_fast_res = {
        "status": "ok",
        "route": "UNIVERSITY_INFO",
        "answer": "Tuition is RM 18,000.",
        "sources": [{"chunk_id": 303, "document_title": "Fees", "access_level": "PUBLIC"}],
    }
    with _RAG_RESPONSE_CACHE_LOCK:
        _RAG_RESPONSE_CACHE.clear()

    with (
        patch.object(request_module, "_classify_with_flash_lite"),
        patch.object(request_module, "resolve_auth_context", return_value=AuthenticatedChatContext(None, None)),
        patch("RagChatbot.services.chat_service._condense_query_with_history") as mock_condense,
        patch("RagChatbot.generation.live_fast_rag.live_fast_rag.process_voice_query", return_value=fake_fast_res) as mock_rag,
    ):
        res = request_module.process_user_request(
            transcript="How much is it?",
            bearer_token=None,
            device_id="edge-test",
            session_id=None,
            db=db,
            fast_voice=True,
            chat_history=[{"user": "Tell me about Computer Science", "assistant": "It is a 3-year degree."}],
            allowed_levels=["PUBLIC"],
        )

    assert res["status"] == "ok"
    mock_condense.assert_not_called()
    assert mock_rag.call_args.kwargs["allowed_access_levels"] == ["PUBLIC"]


def test_process_chat_stream_greeting_does_not_delegate_to_process_chat():
    """Fast-path greeting in process_chat_stream should not re-run process_chat()."""
    from RagChatbot.schemas import ChatRequest
    from RagChatbot.services import chat_service

    db = MagicMock()
    req = ChatRequest(query="Hello!")
    with (
        patch.object(chat_service, "process_chat", side_effect=AssertionError("Should not call process_chat")) as mock_pc,
        patch.object(chat_service, "log_chatbot_interaction", return_value=55),
    ):
        events = list(chat_service.process_chat_stream(req, bearer_token=None, db=db))

    mock_pc.assert_not_called()
    assert any("event: done" in e and '"intent": "GREETING"' in e for e in events)


def test_live_fast_rag_passes_thinking_config():
    """LiveFastRAG should pass ThinkingConfig with configured budget to Flash-Lite."""
    from RagChatbot.generation.live_fast_rag import live_fast_rag
    from RagChatbot.retrieval.vector_store import vector_store

    db = MagicMock()
    captured = {}

    def fake_gen(*, client, model, contents, config, **kwargs):
        captured["config"] = config
        return SimpleNamespace(text="Grounded answer.")

    with (
        patch.object(vector_store, "is_loaded", True),
        patch("RagChatbot.generation.live_fast_rag.embed_text", return_value=[0.1] * 8),
        patch.object(vector_store, "search_hybrid_with_scores", return_value=[]),
        patch("RagChatbot.generation.live_fast_rag.generate_content_with_retry", side_effect=fake_gen),
    ):
        res = live_fast_rag.process_voice_query(
            "What are the library hours?",
            auth_context=AuthenticatedChatContext(None, None),
            db=db,
            allowed_access_levels=["PUBLIC"],
        )

    assert res["status"] == "ok"
    assert res["query_embedding"] == [0.1] * 8
    assert captured["config"].thinking_config is not None
    assert captured["config"].thinking_config.thinking_budget == 0
