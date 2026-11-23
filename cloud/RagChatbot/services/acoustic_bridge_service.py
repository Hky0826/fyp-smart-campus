"""Instant acoustic bridge generation for low perceived latency in audio chat."""

from __future__ import annotations

import base64
import logging
import threading
from typing import Optional, Tuple

from RagChatbot.config import rag_settings
def _get_or_synthesize_bridge(text: str) -> Optional[bytes]:
    """Deprecated. All audio output is handled exclusively by Gemini Live."""
    return None


def get_acoustic_bridge(query_text: str) -> Tuple[str, Optional[bytes]]:
    """
    Returns an immediate spoken filler phrase and 24kHz PCM audio.
    Executes in <5ms on cache hit to eliminate user perceived latency.
    """
    q_lower = query_text.lower()
    
    if any(k in q_lower for k in ["fee", "tuition", "cost", "scholarship", "ptptn"]):
        bridge_text = "Checking tuition fees and scholarship details for you..."
    elif any(k in q_lower for k in ["where", "location", "room", "block", "find", "map"]):
        bridge_text = "Checking the campus map and location for you..."
    elif any(k in q_lower for k in ["course", "degree", "program", "requirement", "bcs", "entry"]):
        bridge_text = "Looking up the programme requirements and details..."
    elif any(k in q_lower for k in ["qiu", "quest", "university", "about"]):
        bridge_text = "Let me look up information about Quest International University for you..."
    elif any(k in q_lower for k in ["timetable", "schedule", "class", "exam"]):
        bridge_text = "Looking up your campus timetable and schedule..."
    else:
        bridge_text = "Checking university records for you..."

    audio_pcm = _get_or_synthesize_bridge(bridge_text)
    return bridge_text, audio_pcm
