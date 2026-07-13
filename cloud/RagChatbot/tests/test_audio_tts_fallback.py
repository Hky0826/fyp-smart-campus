"""Regression tests for audio-chat TTS fallback behavior."""

from __future__ import annotations

import concurrent.futures
from unittest.mock import Mock

from RagChatbot.generation import response_validator
from RagChatbot.services import audio_chat_service


def test_tts_base64_attempts_long_text(monkeypatch):
    """Long text responses should still attempt TTS."""
    generate_audio = Mock(return_value=b"pcm")
    monkeypatch.setattr(audio_chat_service.rag_settings, "AUDIO_TTS_ENABLED", True)
    monkeypatch.setattr(audio_chat_service.rag_settings, "AUDIO_TTS_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(audio_chat_service, "generate_audio_from_text", generate_audio)

    assert audio_chat_service._tts_base64("x" * 1000) == "cGNt"
    generate_audio.assert_called_once_with("x" * 1000)


def test_tts_base64_returns_text_only_when_tts_raises(monkeypatch):
    """Unexpected TTS SDK failures should not fail the audio-chat response."""
    monkeypatch.setattr(audio_chat_service.rag_settings, "AUDIO_TTS_ENABLED", True)
    monkeypatch.setattr(audio_chat_service.rag_settings, "AUDIO_TTS_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(
        audio_chat_service,
        "generate_audio_from_text",
        Mock(side_effect=ValueError("tts failed")),
    )

    assert audio_chat_service._tts_base64("short answer") is None


def test_tts_base64_returns_text_only_when_tts_times_out(monkeypatch):
    """Slow TTS must not block the audio-chat HTTP response."""
    monkeypatch.setattr(audio_chat_service.rag_settings, "AUDIO_TTS_ENABLED", True)
    monkeypatch.setattr(audio_chat_service.rag_settings, "AUDIO_TTS_TIMEOUT_SECONDS", 0.1)

    timeout_future = _TimeoutFuture()
    executor = Mock()
    executor.submit.return_value = timeout_future
    monkeypatch.setattr(audio_chat_service, "_TTS_EXECUTOR", executor)

    assert audio_chat_service._tts_base64("short answer") is None
    assert timeout_future.cancelled


def test_generate_audio_from_text_stream_yields_chunks(monkeypatch):
    """Streaming TTS should yield the batch audio as a single chunk."""
    monkeypatch.setattr(
        response_validator, "generate_audio_from_text", Mock(return_value=b"batch-pcm")
    )

    assert list(response_validator.generate_audio_from_text_stream("short answer")) == [
        b"batch-pcm",
    ]


class _TimeoutFuture:
    def __init__(self) -> None:
        self.cancelled = False

    def result(self, timeout=None):
        raise concurrent.futures.TimeoutError()

    def cancel(self):
        self.cancelled = True
        return True
