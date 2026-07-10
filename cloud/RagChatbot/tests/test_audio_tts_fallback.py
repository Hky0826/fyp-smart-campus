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


def test_generate_audio_from_text_falls_back_after_missing_model(monkeypatch):
    """A bad configured TTS model should fall back before giving up."""
    response_validator._UNAVAILABLE_TTS_MODELS.clear()
    monkeypatch.setattr(response_validator.rag_settings, "AUDIO_TTS_MODEL", "missing-model")
    monkeypatch.setattr(response_validator.rag_settings, "AUDIO_TTS_FALLBACK_MODELS", "working-model")

    calls: list[str] = []

    def generate_content(*, model, contents, config):
        calls.append(model)
        if model == "missing-model":
            raise RuntimeError("404 NOT_FOUND")
        return _fake_audio_response(b"pcm")

    fake_client = Mock()
    fake_client.models.generate_content = generate_content
    monkeypatch.setattr(response_validator.genai, "Client", Mock(return_value=fake_client))

    assert response_validator.generate_audio_from_text("short answer") == b"pcm"
    assert calls == ["missing-model", "working-model"]
    assert "missing-model" in response_validator._UNAVAILABLE_TTS_MODELS


def _fake_audio_response(data: bytes):
    inline_data = Mock(mime_type="audio/pcm", data=data)
    part = Mock(inline_data=inline_data)
    candidate = Mock()
    candidate.content.parts = [part]
    response = Mock()
    response.candidates = [candidate]
    return response


class _TimeoutFuture:
    def __init__(self) -> None:
        self.cancelled = False

    def result(self, timeout=None):
        raise concurrent.futures.TimeoutError()

    def cancel(self):
        self.cancelled = True
        return True
