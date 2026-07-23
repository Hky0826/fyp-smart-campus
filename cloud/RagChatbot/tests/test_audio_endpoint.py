"""
Tests for the /api/chatbot/chat/audio endpoint and text-path regression.

Uses FastAPI TestClient with mocked service dependencies to verify:
- Audio multipart upload succeeds
- Missing audio returns 422
- Oversized audio returns 400
- Wrong MIME type returns 400
- Empty audio returns 400
- Text chat endpoint still works (regression)
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from RagChatbot.router import router


# ── Lightweight test app ──────────────────────────────────────────────────────
# Mount only the chatbot router so tests are isolated from the full app.
_app = FastAPI()
_app.include_router(router, prefix="/api")

# Override get_db so no real database connection is needed.
_mock_db = MagicMock()
_app.dependency_overrides = {}


@pytest.fixture(autouse=True)
def _override_db():
    """Provide a fake DB session for every test."""
    from app.core.database import get_db

    def _fake_get_db():
        yield _mock_db

    _app.dependency_overrides[get_db] = _fake_get_db
    yield
    _app.dependency_overrides.clear()


client = TestClient(_app, raise_server_exceptions=False)

# A minimal valid WAV header (44 bytes) followed by silence.
_MINIMAL_WAV = (
    b"RIFF"
    b"\x2c\x00\x00\x00"  # file size - 8
    b"WAVE"
    b"fmt "
    b"\x10\x00\x00\x00"  # PCM chunk size
    b"\x01\x00"  # PCM format
    b"\x01\x00"  # mono
    b"\x40\x1f\x00\x00"  # sample rate 8000
    b"\x80\x3e\x00\x00"  # byte rate
    b"\x02\x00"  # block align
    b"\x10\x00"  # bits per sample
    b"data"
    b"\x00\x00\x00\x00"  # data chunk size
)


# ── Audio endpoint tests ─────────────────────────────────────────────────────


class TestChatAudioEndpoint:
    """Tests for POST /api/chatbot/chat/audio."""

    @patch("RagChatbot.router.process_audio_chat")
    def test_audio_upload_returns_response(self, mock_process):
        """Valid audio upload should call process_audio_chat and return result."""
        from RagChatbot.schemas import AudioChatResponse

        mock_process.return_value = AudioChatResponse(
            transcribed_input="When does the library close?",
            text_response="The library closes at 10 PM.",
            status="ok",
            access_granted=True,
        )

        response = client.post(
            "/api/chatbot/chat/audio",
            files={"audio": ("test.wav", BytesIO(_MINIMAL_WAV), "audio/wav")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["transcribed_input"] == "When does the library close?"
        assert data["text_response"] == "The library closes at 10 PM."
        assert data["access_granted"] is True

        # Verify the service was called with correct arguments
        mock_process.assert_called_once()
        call_kwargs = mock_process.call_args
        assert isinstance(call_kwargs.kwargs["audio_bytes"], bytes)
        assert call_kwargs.kwargs["mime_type"] == "audio/wav"
        assert call_kwargs.kwargs["bearer_token"] is None

    @patch("RagChatbot.router.process_audio_chat")
    def test_audio_upload_with_device_id_and_session(self, mock_process):
        """Optional device_id and session_id should be forwarded to the service."""
        from RagChatbot.schemas import AudioChatResponse

        mock_process.return_value = AudioChatResponse(
            text_response="ok",
            status="ok",
            access_granted=True,
        )

        response = client.post(
            "/api/chatbot/chat/audio",
            files={"audio": ("test.wav", BytesIO(_MINIMAL_WAV), "audio/wav")},
            data={"device_id": "edge-001", "session_id": "42"},
        )

        assert response.status_code == 200
        call_kwargs = mock_process.call_args.kwargs
        assert call_kwargs["device_id"] == "edge-001"
        assert call_kwargs["session_id"] == 42

    @patch("RagChatbot.router.process_audio_chat_stream")
    def test_audio_stream_upload_returns_metadata_and_audio_chunks(self, mock_stream):
        """Streaming upload should emit metadata, PCM chunks, and done events."""
        meta_payload = {
            "transcribed_input": "When does the library close?",
            "text_response": "The library closes at 10 PM.",
            "status": "ok",
            "access_granted": True,
        }
        mock_stream.return_value = iter([
            {"event": "metadata", "data": meta_payload},
            {
                "event": "audio",
                "data": {
                    "encoding": "pcm_s16le",
                    "sample_rate": 24000,
                    "chunk": base64.b64encode(b"pcm-1").decode("ascii"),
                    "text": "The library closes at 10 PM.",
                },
            },
            {"event": "done", "data": meta_payload},
        ])

        response = client.post(
            "/api/chatbot/chat/audio/stream",
            files={"audio": ("test.wav", BytesIO(_MINIMAL_WAV), "audio/wav")},
        )

        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines() if line]
        assert [event["event"] for event in events] == ["metadata", "audio", "done"]
        assert events[0]["data"]["status"] == "ok"
        assert base64.b64decode(events[1]["data"]["chunk"]) == b"pcm-1"


    def test_missing_audio_returns_422(self):
        """Sending no audio file should return a 422 validation error."""
        response = client.post("/api/chatbot/chat/audio")
        assert response.status_code == 422

    def test_empty_audio_returns_400(self):
        """An empty audio file should return 400."""
        response = client.post(
            "/api/chatbot/chat/audio",
            files={"audio": ("empty.wav", BytesIO(b""), "audio/wav")},
        )
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_oversized_audio_returns_400(self):
        """An audio file exceeding the size limit should return 400."""
        # Create a fake oversized payload (20 bytes over any reasonable limit)
        oversized = b"\x00" * (10 * 1024 * 1024 + 1)
        response = client.post(
            "/api/chatbot/chat/audio",
            files={"audio": ("huge.wav", BytesIO(oversized), "audio/wav")},
        )
        assert response.status_code == 400
        assert "size" in response.json()["detail"].lower()

    def test_wrong_content_type_returns_400(self):
        """A non-audio MIME type should return 400."""
        response = client.post(
            "/api/chatbot/chat/audio",
            files={"audio": ("image.png", BytesIO(b"not audio"), "image/png")},
        )
        assert response.status_code == 400
        assert "audio" in response.json()["detail"].lower()

    @patch("RagChatbot.router.process_audio_chat")
    def test_service_error_returns_500(self, mock_process):
        """An unexpected exception from the service should return 500."""
        mock_process.side_effect = RuntimeError("kaboom")

        response = client.post(
            "/api/chatbot/chat/audio",
            files={"audio": ("test.wav", BytesIO(_MINIMAL_WAV), "audio/wav")},
        )

        assert response.status_code == 500
        assert "unexpected" in response.json()["detail"].lower()


# ── Text chat regression test ────────────────────────────────────────────────


class TestChatRegression:
    """Verify that the existing POST /api/chatbot/chat endpoint still works."""

    @patch("RagChatbot.router.process_chat")
    def test_text_chat_still_works(self, mock_process):
        """The text chat endpoint should continue to return ChatResponse."""
        from RagChatbot.schemas import ChatResponse

        mock_process.return_value = ChatResponse(
            answer="The semester starts on September 1.",
            citations=[],
            access_granted=True,
        )

        response = client.post(
            "/api/chatbot/chat",
            json={"query": "When does the semester start?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "The semester starts on September 1."
        assert data["access_granted"] is True
        mock_process.assert_called_once()
