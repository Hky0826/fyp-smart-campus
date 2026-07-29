"""
Inference Timing Logger for RAG Chatbot.

Logs stage-by-stage inference performance metrics to a file and system logger:
  1. Prompt Injection Check Time (prompt_injection_ms)
  2. Prompt Classification Time (prompt_classification_ms)
  3. Embedding Return Time (embedding_return_ms)
  4. Embedding Database Search Time (embedding_db_search_ms)
  5. RAG (LLM Generation) Time (rag_ms)
  6. TTS Time (tts_ms)
  7. Total Inference Time (total_inference_ms)
"""

from __future__ import annotations

import datetime
import json
import hashlib
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from RagChatbot.config import rag_settings

logger = logging.getLogger("RagChatbot.inference")


@dataclass
class InferenceMetrics:
    """Structure holding timing breakdown (in milliseconds) for chatbot inference."""
    prompt_injection_ms: float = 0.0
    prompt_classification_ms: float = 0.0
    embedding_return_ms: float = 0.0
    embedding_db_search_ms: float = 0.0
    rag_ms: float = 0.0
    tts_ms: float = 0.0
    time_to_first_tts_ms: float = 0.0
    total_inference_ms: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Return timings rounded to 2 decimal places."""
        return {
            "prompt_injection_ms": round(self.prompt_injection_ms, 2),
            "prompt_classification_ms": round(self.prompt_classification_ms, 2),
            "embedding_return_ms": round(self.embedding_return_ms, 2),
            "embedding_db_search_ms": round(self.embedding_db_search_ms, 2),
            "rag_ms": round(self.rag_ms, 2),
            "tts_ms": round(self.tts_ms, 2),
            "time_to_first_tts_ms": round(self.time_to_first_tts_ms, 2),
            "total_inference_ms": round(self.total_inference_ms, 2),
        }


class StageTimer:
    """Utility context manager to measure duration of a stage in milliseconds."""
    def __init__(self) -> None:
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> StageTimer:
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.elapsed_ms = (time.monotonic() - self._start) * 1000.0


def _resolve_log_path(file_setting: str) -> Path:
    """Resolve the absolute path for the inference log file."""
    path = Path(file_setting)
    if not path.is_absolute():
        # Place relative log files inside the cloud/ or project base directory
        base_dir = Path(__file__).resolve().parents[2]  # cloud/ directory
        path = base_dir / file_setting
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_inference_metrics(
    *,
    request_type: str,  # "text" or "audio"
    user_id: Optional[int],
    session_id: Optional[int],
    query_text: Optional[str],
    metrics: InferenceMetrics,
    status: str = "ok",
) -> None:
    """
    Log chatbot inference metrics to system logger and append JSON-L record to file.

    Args:
        request_type: Mode of request ("text" or "audio").
        user_id: Authenticated user ID or None.
        session_id: JWT session ID or None.
        query_text: User input prompt or summary.
        metrics: Populated InferenceMetrics instance.
        status: Final status of request ("ok", "blocked", "error", etc.).
    """
    if not rag_settings.RAG_INFERENCE_LOG_ENABLED:
        return

    timestamp_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    timings = metrics.to_dict()

    record = {
        "timestamp": timestamp_str,
        "request_type": request_type,
        "status": status,
        "user_id": user_id,
        "session_id": session_id,
        "query_hash": hashlib.sha256((query_text or "").encode("utf-8", errors="ignore")).hexdigest() if query_text else None,
        "query_length": len(query_text or ""),
        "query_category": "personal" if (query_text or "").startswith("[PERSONAL") else "chat",
        "query_text": "[REDACTED]" if query_text else None,
        "timings_ms": timings,
    }

    # 1. Log human-readable summary to system logger
    logger.info(
        "INFERENCE_METRICS [%s] type=%s user_id=%s session_id=%s status=%s "
        "total=%.2fms (injection=%.2fms classification=%.2fms embedding=%.2fms db_search=%.2fms rag=%.2fms tts=%.2fms first_tts=%.2fms)",
        timestamp_str,
        request_type,
        user_id,
        session_id,
        status,
        timings["total_inference_ms"],
        timings["prompt_injection_ms"],
        timings["prompt_classification_ms"],
        timings["embedding_return_ms"],
        timings["embedding_db_search_ms"],
        timings["rag_ms"],
        timings["tts_ms"],
        timings["time_to_first_tts_ms"],
    )

    # 2. Append JSON Line record to inference log file
    try:
        log_file_path = _resolve_log_path(rag_settings.RAG_INFERENCE_LOG_FILE)
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("Failed to write inference log record to file: %s", exc)
