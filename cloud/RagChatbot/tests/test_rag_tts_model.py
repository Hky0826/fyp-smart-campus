"""Tests for the RAG audio TTS model integration path."""

from __future__ import annotations

import base64
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CLOUD_ROOT = PROJECT_ROOT / "cloud"
BACKEND_ROOT = CLOUD_ROOT / "dashboard" / "backend"

for path in (CLOUD_ROOT, BACKEND_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from RagChatbot.generation import response_validator
from RagChatbot.personalisation.schemas import AuthenticatedChatContext, PersonalIntent, PersonalResult
from RagChatbot.retrieval.ranking import RankedChunk
from RagChatbot.schemas import ExtractedQuery
from RagChatbot.services import audio_chat_service


class RagTtsModelTests(unittest.TestCase):
    def test_generate_audio_from_text_uses_configured_tts_model(self):
        """The deprecated TTS helper should return None as audio is handled by Gemini Live."""
        audio = response_validator.generate_audio_from_text(
            "The library closes at 10 PM."
        )
        self.assertIsNone(audio)

    def test_process_audio_chat_returns_base64_tts_after_validated_rag_answer(self):
        """A successful audio RAG answer returns validated text, while audio is emitted by Gemini Live."""
        chunk = RankedChunk(
            chunk_id=1,
            document_id=10,
            document_title="Library Guide",
            chunk_index=0,
            chunk_text="The library closes at 10 PM.",
            access_level="PUBLIC",
            similarity_score=0.99,
        )
        answer = "The library closes at 10 PM."
        fake_fast_res = {
            "status": "ok",
            "route": "UNIVERSITY_INFO",
            "answer": answer,
            "sources": [{
                "chunk_id": 1,
                "document_id": 10,
                "document_title": "Library Guide",
                "section_path": "Library Guide",
                "access_level": "PUBLIC",
            }],
        }

        with (
            patch.object(
                audio_chat_service,
                "extract_query_from_audio",
                Mock(return_value=ExtractedQuery(user_query="When does the library close?")),
            ),
            patch.object(audio_chat_service, "embed_text", Mock(return_value=[0.1, 0.2])),
            patch.object(audio_chat_service, "retrieve_chunks", Mock(return_value=[chunk])),
            patch("RagChatbot.generation.live_fast_rag.live_fast_rag.process_voice_query", return_value=fake_fast_res),
            patch.object(
                audio_chat_service,
                "validate_response",
                Mock(return_value=audio_chat_service.ValidationResult(valid=True)),
            ),
        ):
            response = audio_chat_service.process_audio_chat(
                audio_bytes=b"wav-bytes",
                mime_type="audio/wav",
                bearer_token=None,
                device_id="edge-001",
                session_id=None,
                db=Mock(),
            )

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.text_response, answer)
        self.assertIsNone(response.audio_response)
        self.assertEqual(response.sources[0].document_title, "Library Guide")

    def test_process_audio_chat_stream_handles_personal_result_status(self):
        """The streaming personal path should map PersonalResult to an audio status."""
        personal_result = PersonalResult(
            answer="Your next class is CS101 - Secure Systems.",
            access_granted=True,
            status_message=None,
            intent=PersonalIntent.TIMETABLE,
        )

        with (
            patch.object(audio_chat_service.rag_settings, "AUDIO_TTS_ENABLED", False),
            patch.object(
                audio_chat_service,
                "extract_query_from_audio",
                Mock(return_value=ExtractedQuery(user_query="What is my next class?")),
            ),
            patch.object(
                audio_chat_service,
                "resolve_auth_context",
                Mock(return_value=AuthenticatedChatContext(7, 9, authenticated=True)),
            ),
            patch.object(
                audio_chat_service,
                "handle_personal_request",
                Mock(return_value=personal_result),
            ),
        ):
            events = list(
                audio_chat_service.process_audio_chat_stream(
                    audio_bytes=b"wav-bytes",
                    mime_type="audio/wav",
                    bearer_token=None,
                    device_id="edge-001",
                    session_id=None,
                    db=Mock(),
                )
            )

        self.assertEqual([event["event"] for event in events], ["transcript", "metadata", "chunk", "done"])
        self.assertEqual(events[0]["data"]["transcribed_input"], "What is my next class?")
        self.assertEqual(events[1]["data"]["status"], "ok")
        self.assertTrue(events[1]["data"]["access_granted"])

    def test_tts_wrapper_return_time_for_100_300_700_characters(self):
        """Deprecated _tts_base64 returns None cleanly without delay."""
        for char_count in (100, 300, 700):
            text = _sample_text(char_count)
            started_at = time.perf_counter()
            audio_base64 = audio_chat_service._tts_base64(text)
            elapsed_seconds = time.perf_counter() - started_at

            self.assertEqual(len(text), char_count)
            self.assertIsNone(audio_base64)
            self.assertLess(elapsed_seconds, 0.1)

    def test_real_tts_return_time_for_100_300_700_characters(self):
        """Measure real Gemini TTS return time for common response lengths."""
        if os.getenv("RUN_REAL_TTS_TIMING_TESTS") != "1":
            self.skipTest("Set RUN_REAL_TTS_TIMING_TESTS=1 to run real TTS timing.")
        if not response_validator.rag_settings.GOOGLE_API_KEY:
            self.skipTest("GOOGLE_API_KEY is required for real TTS timing.")

        with (
            patch.object(response_validator.rag_settings, "AUDIO_TTS_VOICE", "en-US-Chirp3-HD-Kore"),
        ):
            for char_count in (100, 300, 700):
                text = _sample_text(char_count)
                started_at = time.perf_counter()
                audio = response_validator.generate_audio_from_text(text)
                elapsed_seconds = time.perf_counter() - started_at

                self.assertEqual(len(text), char_count)
                self.assertIsNotNone(audio)
                self.assertGreater(len(audio or b""), 0)
                timings.append((char_count, elapsed_seconds, len(audio or b"")))

        print("\nTTS return time results:")
        for char_count, elapsed_seconds, audio_bytes in timings:
            print(
                f"  {char_count:>3} chars -> {elapsed_seconds:.2f}s "
                f"({audio_bytes:,} audio bytes)"
            )


def _fake_audio_response(data: bytes):
    inline_data = Mock(mime_type="audio/pcm", data=data)
    part = Mock(inline_data=inline_data)
    candidate = Mock()
    candidate.content.parts = [part]
    response = Mock()
    response.candidates = [candidate]
    return response


def _sample_text(char_count: int) -> str:
    base = (
        "The Smart Campus assistant answers questions using validated campus "
        "documents and returns clear spoken responses for students and visitors. "
    )
    return (base * ((char_count // len(base)) + 1))[:char_count]


if __name__ == "__main__":
    unittest.main()
