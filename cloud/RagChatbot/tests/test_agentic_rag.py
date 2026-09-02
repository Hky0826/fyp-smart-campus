import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOUD_ROOT = REPO_ROOT / "cloud"
for p in [str(REPO_ROOT), str(CLOUD_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

for mod in ["google", "google.genai", "google.genai.types", "google.generativeai", "sqlalchemy", "sqlalchemy.orm", "jwt", "pydantic", "numpy"]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            m = MagicMock()
            sys.modules[mod] = m

from RagChatbot.agent.graph import run_agentic_rag, AgentExecutionResult
from RagChatbot.agent.nodes import (
    decompose_query_node,
    grade_documents_node,
    groundedness_critic_node,
    retrieve_and_hydrate_node,
    rewrite_query_node,
    synthesize_answer_node,
)
from RagChatbot.agent.state import AgentState, SubGoal
from RagChatbot.config import rag_settings
from RagChatbot.personalisation.schemas import AuthenticatedChatContext
from RagChatbot.retrieval.ranking import RankedChunk


class TestAgenticRAG(unittest.TestCase):
    def setUp(self):
        self.auth_context = AuthenticatedChatContext(
            user_id=1,
            session_id=100,
            roles=("ADMIN", "VISITOR"),
            admin_id="ADM001",
        )
        self.mock_db = MagicMock()

    def test_fast_path_decomposition(self):
        """Simple short queries should be marked as fast path without extra LLM hops."""
        state = AgentState(
            user_query="Where is the library?",
            auth_context=self.auth_context,
            allowed_access_levels=["PUBLIC", "ADMIN"],
        )
        out = decompose_query_node(state, db=self.mock_db)
        self.assertTrue(out.is_fast_path)
        self.assertEqual(len(out.sub_goals), 1)
        self.assertEqual(out.sub_goals[0].query, "Where is the library?")

    @patch("RagChatbot.agent.nodes.get_gemini_client")
    def test_compound_query_decomposition(self, mock_client_factory):
        """Compound multi-part queries should be decomposed into atomic sub-goals."""
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '{"acoustic_bridge": "Checking fees and entry requirements...", "sub_goals": [{"query": "tuition fee for BCS", "category": "FEES_SCHOLARSHIPS", "faculty_code": "FOCS"}, {"query": "entry requirements for BCS", "category": "ADMISSIONS", "faculty_code": "FOCS"}]}'
        mock_client.models.generate_content.return_value = mock_response

        state = AgentState(
            user_query="What is the tuition fee for BCS and what are the entry requirements as well as prerequisite subjects?",
            auth_context=self.auth_context,
            allowed_access_levels=["PUBLIC", "ADMIN"],
        )
        out = decompose_query_node(state, db=self.mock_db)
        self.assertEqual(len(out.sub_goals), 2)
        self.assertEqual(out.sub_goals[0].query, "tuition fee for BCS")
        self.assertEqual(out.sub_goals[1].query, "entry requirements for BCS")
        self.assertIn("fees and entry requirements", out.acoustic_bridge)

    @patch("RagChatbot.agent.nodes.get_gemini_client")
    def test_document_grading_crag(self, mock_client_factory):
        """Document grading should accurately flag irrelevant or relevant chunks."""
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '{"relevant": true}'
        mock_client.models.generate_content.return_value = mock_response

        chunk = RankedChunk(
            chunk_id=1,
            document_id=10,
            document_title="Fees",
            chunk_index=0,
            chunk_text="Bachelor of Computer Science tuition fee is RM 45,000.",
            access_level="PUBLIC",
            similarity_score=0.65,
        )
        sub_goal = SubGoal(query="What is the fee for BCS?", retrieved_chunks=[chunk])
        state = AgentState(
            user_query="What is the fee for BCS?",
            auth_context=self.auth_context,
            allowed_access_levels=["PUBLIC"],
            sub_goals=[sub_goal],
            all_retrieved_chunks=[chunk],
        )
        out = grade_documents_node(state)
        self.assertTrue(out.sub_goals[0].is_relevant)

    @patch("RagChatbot.agent.nodes.get_gemini_client")
    def test_query_rewriter(self, mock_client_factory):
        """Query rewriter should expand failed queries within maximum iteration limits."""
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '{"rewritten_query": "Bachelor of Computer Science tuition fees schedule"}'
        mock_client.models.generate_content.return_value = mock_response

        sub_goal = SubGoal(query="cs fees", is_relevant=False, retrieved_chunks=[])
        state = AgentState(
            user_query="cs fees",
            auth_context=self.auth_context,
            allowed_access_levels=["PUBLIC"],
            sub_goals=[sub_goal],
            rewrite_count=0,
        )
        out = rewrite_query_node(state)
        self.assertEqual(out.rewrite_count, 1)
        self.assertEqual(out.sub_goals[0].query, "Bachelor of Computer Science tuition fees schedule")

    @patch("RagChatbot.agent.nodes.get_gemini_client")
    def test_groundedness_critic(self, mock_client_factory):
        """Groundedness critic checks for hallucinations against citations."""
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '{"grounded": true, "confidence": 0.98}'
        mock_client.models.generate_content.return_value = mock_response

        chunk = RankedChunk(
            chunk_id=1,
            document_id=10,
            document_title="Policy",
            chunk_index=0,
            chunk_text="Passing grade is 50%.",
            access_level="PUBLIC",
            similarity_score=0.9,
        )
        state = AgentState(
            user_query="What is passing grade?",
            auth_context=self.auth_context,
            allowed_access_levels=["PUBLIC"],
            all_retrieved_chunks=[chunk],
            final_answer="The passing grade for all undergraduate programmes is 50%.",
        )
        out = groundedness_critic_node(state)
        self.assertTrue(out.is_grounded)
        self.assertAlmostEqual(out.groundedness_score, 0.98)

    @patch("RagChatbot.agent.graph.get_allowed_access_levels_for_user")
    @patch("RagChatbot.agent.nodes.embed_text")
    @patch("RagChatbot.agent.nodes.retrieve_chunks")
    @patch("RagChatbot.agent.nodes.get_gemini_client")
    def test_full_agentic_rag_pipeline(self, mock_gemini, mock_retrieve, mock_embed, mock_rbac):
        """Test full graph execution from query to grounded answer with citations."""
        mock_rbac.return_value = ["PUBLIC", "ADMIN"]
        mock_embed.return_value = [0.1] * 768
        
        chunk = RankedChunk(
            chunk_id=1,
            document_id=10,
            document_title="BCS Handbook",
            chunk_index=0,
            chunk_text="Bachelor of Computer Science tuition fee is RM 45,000.",
            access_level="PUBLIC",
            similarity_score=0.85,
        )
        mock_retrieve.return_value = [chunk]

        mock_client = MagicMock()
        mock_gemini.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = "The tuition fee for Bachelor of Computer Science is RM 45,000."
        mock_client.models.generate_content.return_value = mock_response

        result = run_agentic_rag(
            query="What is the tuition fee for BCS?",
            auth_context=self.auth_context,
            db=self.mock_db,
        )

        self.assertIsInstance(result, AgentExecutionResult)
        self.assertTrue(result.access_granted)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].document_title, "BCS Handbook")
        self.assertIn("45,000", result.answer)


if __name__ == "__main__":
    unittest.main()
