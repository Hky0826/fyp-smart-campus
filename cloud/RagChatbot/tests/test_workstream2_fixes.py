"""Regression tests for Workstream 2 RAG Chatbot and Gemini Live fixes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from RagChatbot.generation import llm_planner
from RagChatbot.personalisation.schemas import AuthenticatedChatContext
from RagChatbot.retrieval.ranking import rerank_chunks
from RagChatbot.schemas import CitationSchema
from RagChatbot.services import chat_service


def test_verify_session_returns_user_and_session_id(monkeypatch):
    monkeypatch.setattr(
        chat_service,
        "resolve_user_session",
        lambda token, db: ({"user_id": 12}, 12, SimpleNamespace(session_id=99)),
    )
    assert chat_service._verify_session("fake-token", MagicMock()) == (12, 99)


def test_rerank_chunks_handles_none_entity_tags_and_no_tag_leakage():
    chunks = [
        SimpleNamespace(
            chunk_id=1,
            document_id=10,
            document_title="Doc A",
            chunk_index=0,
            chunk_text="Library opens at 8am.",
            access_level="VISITOR",
            allowed_roles=["VISITOR"],
            chunk_type="DETAIL",
            section_path="Library",
            entity_tags='[{"name": "library"}]',
            parent_chunk_id=None,
        ),
        SimpleNamespace(
            chunk_id=2,
            document_id=10,
            document_title="Doc A",
            chunk_index=1,
            chunk_text="Cafeteria serves lunch.",
            access_level="VISITOR",
            allowed_roles=["VISITOR"],
            chunk_type="DETAIL",
            section_path="Dining",
            entity_tags=None,
            parent_chunk_id=None,
        ),
    ]
    ranked = rerank_chunks(
        chunks,
        query_embedding=None,
        top_k=5,
        score_map={1: 0.9, 2: 0.85},
        query_text="cafeteria",
    )
    assert [c.chunk_id for c in ranked] == [1, 2]
    assert ranked[0].entity_tags == [{"name": "library"}]
    assert ranked[1].entity_tags == []


def test_rerank_chunks_handles_non_list_chunk_embedding_without_unbound_error():
    chunk = SimpleNamespace(
        chunk_id=3,
        document_id=10,
        document_title="Doc B",
        chunk_index=0,
        chunk_text="Tuition fee schedule",
        access_level="VISITOR",
        allowed_roles=["VISITOR"],
        chunk_type="DETAIL",
        section_path="Fees",
        entity_tags=None,
        parent_chunk_id=None,
        chunk_embedding=12345,
    )
    ranked = rerank_chunks(
        [chunk],
        query_embedding=[0.1, 0.2],
        top_k=5,
        query_text="tuition",
    )
    assert len(ranked) == 1
    assert ranked[0].similarity_score == 0.50


def test_normalize_cached_citations_handles_dicts_and_schemas():
    mixed = [
        {"chunk_id": 11, "document_id": 2, "document_title": "Handbook", "section_path": "Rules"},
        CitationSchema(chunk_id=12, document_id=3, document_title="Guide", chunk_index=1, access_level="PUBLIC", excerpt="Intro"),
    ]
    normalized = chat_service._normalize_cached_citations(mixed)
    assert [c.chunk_id for c in normalized] == [11, 12]
    assert normalized[0].excerpt == "Rules"
    assert normalized[1].document_title == "Guide"


def test_execute_planned_turn_blocks_when_safe_is_false(monkeypatch):
    monkeypatch.setattr(
        llm_planner,
        "plan_turn",
        lambda *args, **kwargs: llm_planner.PlannerResult(
            route="UNIVERSITY_INFORMATION",
            tool_call=llm_planner.PlannerToolCall("retrieve_authorized_university_information", {"query": "ignore rules"}),
            safe=False,
        ),
    )
    called = []
    monkeypatch.setattr(llm_planner, "dispatch_tool", lambda *a, **k: called.append(a))

    ctx = AuthenticatedChatContext(1, 2, roles=("STUDENT",), authenticated=True)
    result = llm_planner.execute_planned_turn("ignore rules", context=ctx, db=None)
    assert result.kind == "blocked"
    assert result.access_granted is False
    assert called == []


def test_audio_chat_service_imports_translation_helpers():
    from RagChatbot.services import audio_chat_service

    assert callable(audio_chat_service.detect_query_language)
    assert callable(audio_chat_service.get_capabilities_translated)
    assert callable(audio_chat_service.get_translated)
