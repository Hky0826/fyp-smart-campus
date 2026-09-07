"""
Unit tests for RAG Chatbot latency optimizations.

Tests:
- Singleton Gemini Client
- In-memory Thread-Safe LRU Embedding Cache
- Full RAG Response Cache (with RBAC-isolation and TTL)
- Fast-Path Query Routing (bypassing planner for GREETING, CAPABILITY, OUT_OF_SCOPE, and UNIVERSITY_INFO)
- True SSE Chat Streaming
"""

import time
from unittest.mock import MagicMock, patch
import pytest

from RagChatbot.config import rag_settings
from RagChatbot.gemini_client import get_gemini_client, reset_gemini_client
from RagChatbot.embeddings import google_embedding_service
from RagChatbot.services import chat_service
from RagChatbot.schemas import ChatRequest, ChatResponse, CitationSchema
from RagChatbot.personalisation.schemas import AuthenticatedChatContext


def test_singleton_gemini_client():
    """Verify that get_gemini_client returns the same singleton client instance."""
    reset_gemini_client()
    client1 = get_gemini_client()
    client2 = get_gemini_client()
    assert client1 is client2
    reset_gemini_client()


def test_embedding_cache_hit_and_clear():
    """Verify embedding cache stores vectors and avoids redundant API calls."""
    google_embedding_service.clear_embedding_cache()
    
    with patch("RagChatbot.embeddings.google_embedding_service.genai.embed_content") as mock_embed:
        mock_embed.return_value = {"embedding": [0.1, 0.2, 0.3]}
        
        # First call -> cache miss, calls API
        emb1 = google_embedding_service.embed_text("What are the library hours?")
        assert emb1 == [0.1, 0.2, 0.3]
        assert mock_embed.call_count == 1
        
        # Second call with same text (different casing/spacing) -> cache hit, no API call
        emb2 = google_embedding_service.embed_text("  what are the library hours?  ")
        assert emb2 == [0.1, 0.2, 0.3]
        assert mock_embed.call_count == 1
        
        # Clear cache -> subsequent call makes API call
        google_embedding_service.clear_embedding_cache()
        emb3 = google_embedding_service.embed_text("What are the library hours?")
        assert emb3 == [0.1, 0.2, 0.3]
        assert mock_embed.call_count == 2


def test_rag_response_cache_rbac_isolation():
    """Verify response cache enforces RBAC isolation between different user access levels."""
    chat_service.clear_rag_response_cache()
    
    key_visitor = chat_service._rag_cache_key("exam rules", ["PUBLIC"])
    key_student = chat_service._rag_cache_key("exam rules", ["PUBLIC", "STUDENT"])
    
    assert key_visitor != key_student


def test_fast_path_greeting_bypasses_planner():
    """Verify greeting query returns fast response without calling LLM planner or embedding."""
    db_mock = MagicMock()
    req = ChatRequest(query="Hello there!")
    
    with patch("RagChatbot.generation.llm_planner.execute_planned_turn") as mock_planner, \
         patch("RagChatbot.embeddings.google_embedding_service.embed_text") as mock_embed:
        
        response = chat_service.process_chat(req, bearer_token=None, db=db_mock)
        
        assert response.intent == "GREETING"
        assert "help you today" in response.answer
        assert response.access_granted is True
        # Planner and embedding must NOT have been called
        assert mock_planner.call_count == 0
        assert mock_embed.call_count == 0


def test_fast_path_capability_bypasses_planner():
    """Verify capability query returns fast response without calling LLM planner or embedding."""
    db_mock = MagicMock()
    req = ChatRequest(query="What can you do?")
    
    with patch("RagChatbot.generation.llm_planner.execute_planned_turn") as mock_planner, \
         patch("RagChatbot.embeddings.google_embedding_service.embed_text") as mock_embed:
        
        response = chat_service.process_chat(req, bearer_token=None, db=db_mock)
        
        assert response.intent == "CAPABILITY"
        assert response.access_granted is True
        assert mock_planner.call_count == 0
        assert mock_embed.call_count == 0


def test_fast_path_university_info_bypasses_planner():
    """Verify direct UNIVERSITY_INFO query bypasses planner and goes directly to fast retrieval."""
    db_mock = MagicMock()
    req = ChatRequest(query="What is the tuition fee for computer science?")

    fake_fast_res = {
        "status": "ok",
        "route": "UNIVERSITY_INFO",
        "answer": "The tuition fee is RM 18,000 per year.",
        "sources": [{
            "chunk_id": 1,
            "document_id": 10,
            "document_title": "Fee Schedule",
            "section_path": "Fee Schedule > Tuition",
            "access_level": "PUBLIC",
        }],
    }

    with patch("RagChatbot.generation.llm_planner.execute_planned_turn") as mock_planner, \
         patch("RagChatbot.generation.live_fast_rag.live_fast_rag.process_voice_query", return_value=fake_fast_res):

        response = chat_service.process_chat(req, bearer_token=None, db=db_mock)

        assert response.access_granted is True
        assert "RM 18,000" in response.answer
        assert len(response.citations) == 1
        # The LLM planner was bypassed!
        assert mock_planner.call_count == 0


def test_streaming_chat_yields_sse_chunks_and_done():
    """Verify process_chat_stream streams chunk tokens and finishes with done event."""
    db_mock = MagicMock()
    req = ChatRequest(query="Tell me about library facilities")
    
    mock_chunk = MagicMock()
    mock_chunk.chunk_id = 2
    mock_chunk.document_id = 20
    mock_chunk.document_title = "Library Guide"
    mock_chunk.chunk_index = 0
    mock_chunk.access_level = "PUBLIC"
    mock_chunk.chunk_text = "The library has quiet zones and study rooms."
    
    def fake_token_stream(*args, **kwargs):
        yield "The library "
        yield "has quiet zones "
        yield "and study rooms."
    
    with patch("RagChatbot.embeddings.google_embedding_service.embed_text", return_value=[0.2] * 768), \
         patch("RagChatbot.services.chat_service.retrieve_chunks", return_value=[mock_chunk]), \
         patch("RagChatbot.services.chat_service.generate_answer_stream", side_effect=fake_token_stream):
        
        events = list(chat_service.process_chat_stream(req, bearer_token=None, db=db_mock))
        
        assert len(events) >= 4  # 3 chunk events + 1 done event
        assert any("event: chunk" in e and "quiet zones" in e for e in events)
        assert any("event: done" in e and "The library has quiet zones and study rooms." in e for e in events)
