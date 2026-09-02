"""Instant acoustic bridge generation for low perceived latency in audio chat."""

from __future__ import annotations

import base64
import logging
import threading
from typing import Optional, Tuple

from RagChatbot.config import rag_settings
from RagChatbot.generation.response_validator import generate_audio_from_text

logger = logging.getLogger(__name__)

# Pre-synthesized memory cache for standard bridge phrases (0ms latency on repeated queries)
_BRIDGE_CACHE: dict[str, bytes] = {}
_BRIDGE_LOCK = threading.Lock()

_DEFAULT_BRIDGES = [
    "Checking university records for you...",
    "Let me look that up across campus documents...",
    "Searching university information for you...",
    "Checking the admissions and degree guidelines...",
    "Let me check that for you right away...",
]


def _get_or_synthesize_bridge(text: str) -> Optional[bytes]:
    """Retrieve pre-synthesized PCM or synthesize once and cache in memory."""
    with _BRIDGE_LOCK:
        if text in _BRIDGE_CACHE:
            return _BRIDGE_CACHE[text]

    try:
        audio_pcm = generate_audio_from_text(text)
        if audio_pcm:
            with _BRIDGE_LOCK:
                _BRIDGE_CACHE[text] = audio_pcm
            return audio_pcm
    except Exception as exc:
        logger.debug("Acoustic bridge synthesis fallback: %s", exc)

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
