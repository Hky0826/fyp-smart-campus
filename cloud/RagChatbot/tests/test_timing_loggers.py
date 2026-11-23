"""
Unit tests for Cloud and Edge Chatbot Timing Loggers.
Verifies event logging, transit time calculations, duration tracking, and file auto-flushing.
"""

import os
from pathlib import Path
import pytest

from RagChatbot.logging.timing_logger import CloudTimingLogger, calc_transit_delay_ms, parse_iso
from access_control.timing_logger import EdgeTimingLogger, calc_transit_delay_ms as edge_calc_transit


def test_iso_parsing_and_transit_calculation():
    # Valid ISO timestamp in past
    past_iso = "2026-09-18T00:00:00.000000+00:00"
    delay = calc_transit_delay_ms(past_iso)
    assert delay is not None
    assert delay > 0

    # Invalid timestamp returns None gracefully
    assert calc_transit_delay_ms("invalid-ts") is None
    assert calc_transit_delay_ms(None) is None
    assert edge_calc_transit(None) is None


def test_cloud_timing_logger_writes_to_file(tmp_path):
    # Log an event
    ts = CloudTimingLogger.log_receive(
        "TEST_RECEIVE",
        turn_id="turn_test_123",
        client_sent_at="2026-09-18T00:00:00.000000+00:00",
        audio_bytes=3200,
    )
    assert ts is not None

    send_ts = CloudTimingLogger.log_send(
        "TEST_SEND",
        turn_id="turn_test_123",
        duration_ms=45.2,
        status="ok",
    )
    assert send_ts is not None

    log_path = Path("cloud/logs/chatbot_timing.log")
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "TEST_RECEIVE" in content
    assert "turn_test_123" in content
    assert "TEST_SEND" in content


def test_edge_timing_logger_writes_to_file(tmp_path):
    # Log edge events
    client_sent_at = EdgeTimingLogger.log_send(
        "TEST_EDGE_SEND",
        turn_id="turn_edge_999",
        duration_ms=1200.0,
        audio_bytes=19200,
    )
    assert client_sent_at is not None

    recv_ts = EdgeTimingLogger.log_receive(
        "TEST_EDGE_RECEIVE",
        turn_id="turn_edge_999",
        server_sent_at=client_sent_at,
        time_since_speech_end_ms=350.5,
    )
    assert recv_ts is not None

    log_path = Path("access_control/logs/chatbot_timing.log")
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "TEST_EDGE_SEND" in content
    assert "turn_edge_999" in content
    assert "TEST_EDGE_RECEIVE" in content


def test_logger_static_methods():
    from RagChatbot.logging.timing_logger import CloudTimingLogger, cloud_timing
    from access_control.timing_logger import EdgeTimingLogger, edge_timing

    assert isinstance(CloudTimingLogger.now_iso(), str)
    assert isinstance(cloud_timing.now_iso(), str)
    assert isinstance(EdgeTimingLogger.now_iso(), str)
    assert isinstance(edge_timing.now_iso(), str)
    assert isinstance(CloudTimingLogger.now_formatted(), str)
    assert isinstance(EdgeTimingLogger.now_formatted(), str)
    assert CloudTimingLogger.calc_transit_delay_ms(None) is None
    assert EdgeTimingLogger.calc_transit_delay_ms(None) is None

