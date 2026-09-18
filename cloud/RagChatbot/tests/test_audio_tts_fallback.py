"""Regression tests for audio-chat TTS fallback behavior."""

from __future__ import annotations

import concurrent.futures
from unittest.mock import Mock

from RagChatbot.generation import response_validator
from RagChatbot.services import audio_chat_service


def test_tts_base64_returns_none_as_live_handles_audio():
    """Standalone TTS is deprecated; audio output is handled by Gemini Live."""
    assert audio_chat_service._tts_base64("x" * 1000) is None
    assert audio_chat_service._tts_base64("short answer") is None


def test_generate_audio_from_text_returns_none():
    """generate_audio_from_text is a safe stub returning None."""
    assert response_validator.generate_audio_from_text("short answer") is None


def test_generate_audio_from_text_stream_yields_empty():
    """Streaming TTS stub yields empty iterator as Gemini Live handles real-time voice."""
    assert list(response_validator.generate_audio_from_text_stream("short answer")) == []
