"""
Edge Timing Logger for Access Control Chatbot.

Synchronized logging for end-to-end latency and transit timing:
  [EDGE -> CLOUD] : Voice activity, audio chunks, and queries sent to the Cloud
  [EDGE INTERNAL] : Client VAD detection, pre-roll flush, audio playback startup
  [EDGE <- CLOUD] : Events, transcripts, status, and audio chunks received from Cloud

Writes to access_control/logs/chatbot_timing.log with auto-flush.
"""

from __future__ import annotations

import datetime
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("AccessControl.timing")

_LOG_LOCK = threading.Lock()
_LOG_FILE_PATH: Optional[Path] = None


def get_timing_log_file_path() -> Path:
    """Resolve and ensure the edge timing log file path."""
    global _LOG_FILE_PATH
    if _LOG_FILE_PATH is None:
        base_dir = Path(__file__).resolve().parent  # access_control/ directory
        log_dir = base_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        _LOG_FILE_PATH = log_dir / "chatbot_timing.log"
    return _LOG_FILE_PATH


def now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format with milliseconds."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def now_formatted() -> str:
    """Return local timestamp in human-readable [YYYY-MM-DD HH:MM:SS.mmm]."""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def parse_iso(iso_str: str | None) -> datetime.datetime | None:
    """Parse an ISO 8601 string to a datetime object, returning None on failure."""
    if not iso_str:
        return None
    try:
        return datetime.datetime.fromisoformat(iso_str)
    except Exception:
        return None


def calc_transit_delay_ms(sent_at_iso: str | None) -> float | None:
    """
    Calculate transit delay in ms by comparing sent_at timestamp to now.
    Note: Clock drift between machines may affect this value.
    """
    sent_dt = parse_iso(sent_at_iso)
    if sent_dt is None:
        return None
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    if sent_dt.tzinfo is None:
        sent_dt = sent_dt.replace(tzinfo=datetime.timezone.utc)
    delay_ms = (now_dt - sent_dt).total_seconds() * 1000.0
    return round(delay_ms, 2)


class EdgeTimingLogger:
    """Logger dedicated to tracking kiosk chatbot timing and network round trips."""

    now_iso = staticmethod(now_iso)
    now_formatted = staticmethod(now_formatted)
    calc_transit_delay_ms = staticmethod(calc_transit_delay_ms)
    parse_iso = staticmethod(parse_iso)

    @staticmethod
    def log_event(
        direction: str,
        stage: str,
        turn_id: Optional[str] = None,
        *,
        server_sent_at: Optional[str] = None,
        transit_delay_ms: Optional[float] = None,
        duration_ms: Optional[float] = None,
        time_since_speech_end_ms: Optional[float] = None,
        **details: Any,
    ) -> str:
        """
        Record a timing entry.
        Returns the client timestamp (ISO string) generated for this event.
        """
        client_ts = now_iso()
        human_time = now_formatted()

        if server_sent_at and transit_delay_ms is None:
            transit_delay_ms = calc_transit_delay_ms(server_sent_at)

        parts = [f"[{human_time}]", f"[{direction}]", f"[{stage}]"]
        if turn_id:
            parts.append(f"turn_id={turn_id}")
        if server_sent_at:
            parts.append(f"server_sent_at={server_sent_at}")
        if transit_delay_ms is not None:
            parts.append(f"transit_delay_ms={transit_delay_ms:.1f}")
        if time_since_speech_end_ms is not None:
            parts.append(f"time_since_speech_end_ms={time_since_speech_end_ms:.1f}")
        if duration_ms is not None:
            parts.append(f"duration_ms={duration_ms:.1f}")

        for k, v in details.items():
            if v is not None:
                if isinstance(v, float):
                    parts.append(f"{k}={v:.2f}")
                else:
                    parts.append(f"{k}={v}")

        log_line = " ".join(parts)

        # 1. Output to Python logging
        logger.info(log_line)

        # 2. Append directly to log file with flush
        try:
            log_path = get_timing_log_file_path()
            with _LOG_LOCK:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(log_line + "\n")
                    f.flush()
        except Exception as exc:
            logger.error("Failed to write to chatbot_timing.log: %s", exc)

        return client_ts

    @classmethod
    def log_send(
        cls,
        stage: str,
        turn_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        **details: Any,
    ) -> str:
        """Helper for [EDGE -> CLOUD] events. Returns the ISO client_sent_at string."""
        return cls.log_event(
            "EDGE -> CLOUD",
            stage,
            turn_id=turn_id,
            duration_ms=duration_ms,
            **details,
        )

    @classmethod
    def log_internal(
        cls,
        stage: str,
        turn_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        time_since_speech_end_ms: Optional[float] = None,
        **details: Any,
    ) -> str:
        """Helper for [EDGE INTERNAL] events."""
        return cls.log_event(
            "EDGE INTERNAL",
            stage,
            turn_id=turn_id,
            duration_ms=duration_ms,
            time_since_speech_end_ms=time_since_speech_end_ms,
            **details,
        )

    @classmethod
    def log_receive(
        cls,
        stage: str,
        turn_id: Optional[str] = None,
        server_sent_at: Optional[str] = None,
        time_since_speech_end_ms: Optional[float] = None,
        **details: Any,
    ) -> str:
        """Helper for [EDGE <- CLOUD] events."""
        return cls.log_event(
            "EDGE <- CLOUD",
            stage,
            turn_id=turn_id,
            server_sent_at=server_sent_at,
            time_since_speech_end_ms=time_since_speech_end_ms,
            **details,
        )


edge_timing = EdgeTimingLogger
