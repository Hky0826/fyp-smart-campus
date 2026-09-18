"""
Unit tests for in-session conversational memory and multi-turn context retention.

Tests:
- Pronoun and conversational reference condensation in English, Malay, and Chinese.
- Short query conversational condensation.
- Vector search retrieval query vs answering query separation in LiveFastRAG.
- In-prompt injection of session conversation history into Gemini Flash Lite.
- Client-supplied chat_history for anonymous visitors without JWT/DB lookup.
- Cache bypass and protection against cache collisions on conversational turns.
- LLMPlanner payload inclusion of recent session history.
"""

from unittest.mock import MagicMock, patch
import pytest

from RagChatbot.generation.live_fast_rag import LiveFastRAG, _format_chat_history
from RagChatbot.generation.llm_planner import plan_turn
from RagChatbot.personalisation.schemas import AuthenticatedChatContext
from RagChatbot.schemas import ChatRequest, ChatResponse, CitationSchema
from RagChatbot.services import chat_service
from RagChatbot.services.chat_service import (
    _load_recent_chat_history,
    _condense_query_with_history,
    clear_rag_response_cache,
    process_chat,
)


def test_format_chat_history():
    """Verify _format_chat_history formats various turn structures correctly."""
    # Dict format with user/assistant
    history1 = [
        {"user": "Tell me about Computer Science", "assistant": "QIU offers BCS."},
        {"user": "How long is it?", "assistant": "It takes 3 years to complete."},
    ]
    formatted = _format_chat_history(history1)
    assert "--- RECENT CONVERSATION IN THIS SESSION ---" in formatted
    assert "User: Tell me about Computer Science" in formatted
    assert "Assistant: QIU offers BCS." in formatted
    assert "User: How long is it?" in formatted
    assert "Assistant: It takes 3 years to complete." in formatted

    # Role/content format
    history2 = [
        {"role": "user", "content": "Where is the library?"},
        {"role": "assistant", "content": "The library is on Level 2."},
    ]
    formatted2 = _format_chat_history(history2)
    assert "User: Where is the library?" in formatted2
    assert "Assistant: The library is on Level 2." in formatted2

    # Empty history
    assert _format_chat_history([]) == ""
    assert _format_chat_history(None) == ""


def test_load_recent_chat_history_prefers_client_history():
    """Verify _load_recent_chat_history uses client_history when provided without DB calls."""
    client_history = [
        {"user": "Hello", "assistant": "Hi there!"},
        {"user": "What courses do you have?", "assistant": "We have Medicine, CS, and Business."},
    ]
    mock_db = MagicMock()
    # When client_history is provided, DB should never be queried
    loaded = _load_recent_chat_history(session_id=None, db=mock_db, limit=3, client_history=client_history)
    assert len(loaded) == 2
    assert loaded[0]["user"] == "Hello"
    assert loaded[1]["assistant"] == "We have Medicine, CS, and Business."
    assert mock_db.query.call_count == 0


def test_condense_query_pronoun_rewrite():
    """Verify _condense_query_with_history invokes LLM rewrite for pronoun-containing follow-ups."""
    history = [
        {"user": "Tell me about Bachelor of Computer Science", "assistant": "It is a 3-year honours degree."}
    ]
    follow_up = "What are the entry requirements for it?"

    mock_resp = MagicMock()
    mock_resp.text = "Bachelor of Computer Science entry requirements"

    with patch("RagChatbot.gemini_client.generate_content_with_retry", return_value=mock_resp) as mock_gen:
        rewritten = _condense_query_with_history(follow_up, history)
        assert rewritten == "Bachelor of Computer Science entry requirements"
        assert mock_gen.call_count == 1
        call_args = mock_gen.call_args
        prompt = call_args.kwargs.get("contents", "")
        assert "Bachelor of Computer Science" in prompt
        assert "What are the entry requirements for it?" in prompt


def test_condense_query_multilingual_cues():
    """Verify Malay and Chinese conversational follow-ups trigger rewriting."""
    history = [
        {"user": "Program Farmasi", "assistant": "Program Ijazah Sarjana Muda Farmasi di QIU..."}
    ]

    # Malay follow-up with pronoun / fee keyword
    mock_resp_ms = MagicMock()
    mock_resp_ms.text = "Yuran Program Farmasi QIU"
    with patch("RagChatbot.gemini_client.generate_content_with_retry", return_value=mock_resp_ms) as mock_gen:
        rewritten = _condense_query_with_history("Berapa yurannya?", history)
        assert rewritten == "Yuran Program Farmasi QIU"
        assert mock_gen.call_count == 1

    # Chinese follow-up
    mock_resp_zh = MagicMock()
    mock_resp_zh.text = "药剂学专业入学要求"
    with patch("RagChatbot.gemini_client.generate_content_with_retry", return_value=mock_resp_zh) as mock_gen:
        rewritten = _condense_query_with_history("这个录取条件是什么？", history)
        assert rewritten == "药剂学专业入学要求"
        assert mock_gen.call_count == 1


def test_condense_query_short_followup_triggers_rewrite():
    """Verify very short queries (<=4 words) trigger rewrite when history is present."""
    history = [
        {"user": "Tell me about MBBS", "assistant": "MBBS is a 5-year medical programme."}
    ]
    mock_resp = MagicMock()
    mock_resp.text = "MBBS tuition fees"
    with patch("RagChatbot.gemini_client.generate_content_with_retry", return_value=mock_resp) as mock_gen:
        rewritten = _condense_query_with_history("Total fees?", history)
        assert rewritten == "MBBS tuition fees"
        assert mock_gen.call_count == 1


def test_condense_query_standalone_skips_rewrite():
    """Verify full standalone questions without pronouns skip rewrite to save latency."""
    history = [
        {"user": "Tell me about MBBS", "assistant": "MBBS is a 5-year medical programme."}
    ]
    standalone = "Where is the student admissions office located on campus?"
    with patch("RagChatbot.gemini_client.generate_content_with_retry") as mock_gen:
        result = _condense_query_with_history(standalone, history)
        assert result == standalone
        assert mock_gen.call_count == 0


def test_live_fast_rag_uses_search_query_and_includes_history():
    """Verify LiveFastRAG processes search_query for vector search and passes history to Gemini."""
    rag = LiveFastRAG()
    mock_client = MagicMock()
    rag._client = mock_client

    mock_db = MagicMock()
    auth_context = AuthenticatedChatContext(
        user_id=None,
        session_id=None,
        roles=("VISITOR",),
        authenticated=False,
    )

    history = [
        {"user": "What is Computer Science?", "assistant": "It is a software degree."}
    ]
    ambiguous_query = "What are the entry requirements for it?"
    resolved_search_query = "Bachelor of Computer Science entry requirements"

    mock_resp = MagicMock()
    mock_resp.text = "Entry requirements for Computer Science require 3 credits in SPM."

    with patch("RagChatbot.generation.live_fast_rag.embed_text", return_value=[0.1] * 768) as mock_embed, \
         patch("RagChatbot.generation.live_fast_rag.vector_store") as mock_vs, \
         patch("RagChatbot.generation.live_fast_rag.generate_content_with_retry", return_value=mock_resp) as mock_gen:

        mock_vs.is_loaded = True
        mock_vs.search_hybrid_with_scores.return_value = []

        result = rag.process_voice_query(
            query=ambiguous_query,
            auth_context=auth_context,
            db=mock_db,
            chat_history=history,
            search_query=resolved_search_query,
        )

        assert result["answer"] == "Entry requirements for Computer Science require 3 credits in SPM."

        # Vector search was embedded and searched with resolved search_query
        mock_embed.assert_called_with(resolved_search_query)
        mock_vs.search_hybrid_with_scores.assert_called()
        search_call_args = mock_vs.search_hybrid_with_scores.call_args
        assert search_call_args.kwargs["query_text"] == resolved_search_query

        # Gemini generation prompt received the session history
        mock_gen.assert_called_once()
        gen_prompt = mock_gen.call_args.kwargs["contents"]
        assert "--- RECENT CONVERSATION IN THIS SESSION ---" in gen_prompt
        assert "User: What is Computer Science?" in gen_prompt
        assert "Assistant: It is a software degree." in gen_prompt
        assert "--- USER QUESTION ---\nWhat are the entry requirements for it?" in gen_prompt


def test_process_chat_visitor_in_session_memory():
    """Verify visitor chat request without JWT passes chat_history to fast RAG and bypasses cache."""
    clear_rag_response_cache()
    mock_db = MagicMock()

    client_history = [
        {"user": "Tell me about Computer Science", "assistant": "QIU offers BCS (Honours)."}
    ]
    request = ChatRequest(
        query="What are the entry requirements for it?",
        chat_history=client_history,
    )

    mock_fast_res = {
        "answer": "SPM minimum 3 credits including Mathematics.",
        "sources": [{"chunk_id": 10, "document_id": 1, "document_title": "BCS Guide", "section_path": "Admissions"}],
        "status": "ok",
    }

    mock_rewrite_resp = MagicMock()
    mock_rewrite_resp.text = "Bachelor of Computer Science entry requirements"

    with patch("RagChatbot.gemini_client.generate_content_with_retry", return_value=mock_rewrite_resp), \
         patch("RagChatbot.generation.live_fast_rag.live_fast_rag.process_voice_query", return_value=mock_fast_res) as mock_pvr, \
         patch("RagChatbot.services.chat_service.log_chatbot_interaction", return_value=123):

        response = process_chat(request, bearer_token=None, db=mock_db)

        assert response.answer == "SPM minimum 3 credits including Mathematics."
        assert len(response.citations) == 1
        assert response.citations[0].document_title == "BCS Guide"

        # Verify live_fast_rag was called with both chat_history and rewritten search_query
        mock_pvr.assert_called_once()
        pvr_kwargs = mock_pvr.call_args.kwargs
        assert pvr_kwargs["chat_history"] == client_history
        assert pvr_kwargs["search_query"] == "Bachelor of Computer Science entry requirements"


def test_cache_bypassed_when_conversational_history_present():
    """Verify follow-up queries with chat_history do not hit or pollute the static RAG cache."""
    clear_rag_response_cache()
    mock_db = MagicMock()

    # Pre-populate cache with a generic answer for "How much is it?"
    from RagChatbot.services.chat_service import _RAG_RESPONSE_CACHE, _rag_cache_key
    import time
    generic_resp = ChatResponse(
        answer="The general application fee is RM 50.",
        citations=[],
        access_granted=True,
    )
    cache_key = _rag_cache_key("How much is it?", ["PUBLIC", "VISITOR"])
    _RAG_RESPONSE_CACHE[cache_key] = (time.monotonic(), generic_resp)

    # Now make a request WITH conversation history about Pharmacy
    pharmacy_history = [
        {"user": "Tell me about Pharmacy", "assistant": "Pharmacy is a 4-year programme."}
    ]
    request = ChatRequest(
        query="How much is it?",
        chat_history=pharmacy_history,
    )

    pharmacy_fee_resp = {
        "answer": "The Bachelor of Pharmacy tuition fee is RM 80,000.",
        "sources": [],
        "status": "ok",
    }

    mock_rewrite = MagicMock()
    mock_rewrite.text = "Bachelor of Pharmacy tuition fee"

    with patch("RagChatbot.gemini_client.generate_content_with_retry", return_value=mock_rewrite), \
         patch("RagChatbot.generation.live_fast_rag.live_fast_rag.process_voice_query", return_value=pharmacy_fee_resp), \
         patch("RagChatbot.services.chat_service.log_chatbot_interaction", return_value=124):

        res = process_chat(request, bearer_token=None, db=mock_db)

        # MUST NOT be the cached "general application fee RM 50"!
        assert res.answer == "The Bachelor of Pharmacy tuition fee is RM 80,000."

    clear_rag_response_cache()


def test_llm_planner_includes_chat_history():
    """Verify plan_turn includes recent_chat_history in the payload sent to Gemini."""
    auth_context = AuthenticatedChatContext(
        user_id=1,
        session_id=10,
        roles=("STUDENT",),
        authenticated=True,
    )
    mock_db = MagicMock()
    history = [
        {"user": "Where is the library?", "assistant": "The library is on Block B Level 2."}
    ]

    mock_planner_resp = MagicMock()
    mock_planner_resp.text = '{"safe": true, "route": "NAVIGATION", "tool_call": {"name": "navigate_to_destination", "arguments": {"destination_description": "library"}}, "clarification_question": "", "confidence": 0.95, "reasoning": "follow-up refers to library"}'

    with patch("RagChatbot.generation.llm_planner.genai.Client"), \
         patch("RagChatbot.gemini_client.generate_content_with_retry", return_value=mock_planner_resp) as mock_gen, \
         patch("RagChatbot.generation.llm_planner._catalog_candidates", return_value=[]), \
         patch("RagChatbot.generation.llm_planner.classify_query", return_value=MagicMock(category="NAVIGATIONAL")):

        result = plan_turn(
            "Take me there",
            context=auth_context,
            db=mock_db,
            chat_history=history,
        )

        assert result.route == "NAVIGATION"
        assert result.tool_call.name == "navigate_to_destination"
        assert mock_gen.call_count == 1
        payload_str = mock_gen.call_args.kwargs["contents"]
        import json
        payload = json.loads(payload_str)
        assert payload["recent_chat_history"] == [
            {"user": "Where is the library?", "assistant": "The library is on Block B Level 2."}
        ]
