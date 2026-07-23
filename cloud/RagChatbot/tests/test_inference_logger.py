"""Unit and integration tests for chatbot inference timing logger."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from RagChatbot.config import rag_settings
from RagChatbot.logging.inference_logger import (
    InferenceMetrics,
    StageTimer,
    log_inference_metrics,
)


def test_inference_metrics_defaults():
    """Verify default values for InferenceMetrics dataclass."""
    metrics = InferenceMetrics()
    assert metrics.prompt_injection_ms == 0.0
    assert metrics.prompt_classification_ms == 0.0
    assert metrics.embedding_return_ms == 0.0
    assert metrics.embedding_db_search_ms == 0.0
    assert metrics.rag_ms == 0.0
    assert metrics.tts_ms == 0.0
    assert metrics.time_to_first_tts_ms == 0.0
    assert metrics.total_inference_ms == 0.0

    d = metrics.to_dict()
    assert d["prompt_injection_ms"] == 0.0
    assert d["prompt_classification_ms"] == 0.0
    assert d["embedding_return_ms"] == 0.0
    assert d["embedding_db_search_ms"] == 0.0
    assert d["rag_ms"] == 0.0
    assert d["tts_ms"] == 0.0
    assert d["time_to_first_tts_ms"] == 0.0
    assert d["total_inference_ms"] == 0.0


def test_stage_timer():
    """Verify StageTimer context manager accurately records elapsed milliseconds."""
    with StageTimer() as timer:
        time.sleep(0.02)

    assert timer.elapsed_ms >= 10.0


def test_log_inference_metrics_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify log_inference_metrics writes valid JSON line when logging is enabled."""
    log_file = tmp_path / "test_inference.log"
    monkeypatch.setattr(rag_settings, "RAG_INFERENCE_LOG_ENABLED", True)
    monkeypatch.setattr(rag_settings, "RAG_INFERENCE_LOG_FILE", str(log_file))

    metrics = InferenceMetrics(
        prompt_injection_ms=12.5,
        prompt_classification_ms=5.0,
        embedding_return_ms=45.2,
        embedding_db_search_ms=18.7,
        rag_ms=320.1,
        tts_ms=110.0,
        time_to_first_tts_ms=85.0,
        total_inference_ms=511.5,
    )

    log_inference_metrics(
        request_type="text",
        user_id=42,
        session_id=101,
        query_text="What is the library opening hours?",
        metrics=metrics,
        status="ok",
    )

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    assert content != ""

    record = json.loads(content)
    assert record["request_type"] == "text"
    assert record["user_id"] == 42
    assert record["session_id"] == 101
    assert record["query_text"] == "What is the library opening hours?"
    assert record["status"] == "ok"
    assert record["timings_ms"]["prompt_injection_ms"] == 12.5
    assert record["timings_ms"]["prompt_classification_ms"] == 5.0
    assert record["timings_ms"]["embedding_return_ms"] == 45.2
    assert record["timings_ms"]["embedding_db_search_ms"] == 18.7
    assert record["timings_ms"]["rag_ms"] == 320.1
    assert record["timings_ms"]["tts_ms"] == 110.0
    assert record["timings_ms"]["time_to_first_tts_ms"] == 85.0
    assert record["timings_ms"]["total_inference_ms"] == 511.5
    assert "timestamp" in record


def test_log_inference_metrics_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify log_inference_metrics does not write to file when disabled."""
    log_file = tmp_path / "test_inference_disabled.log"
    monkeypatch.setattr(rag_settings, "RAG_INFERENCE_LOG_ENABLED", False)
    monkeypatch.setattr(rag_settings, "RAG_INFERENCE_LOG_FILE", str(log_file))

    metrics = InferenceMetrics(total_inference_ms=100.0)

    log_inference_metrics(
        request_type="text",
        user_id=None,
        session_id=None,
        query_text="hello",
        metrics=metrics,
        status="ok",
    )

    assert not log_file.exists()
