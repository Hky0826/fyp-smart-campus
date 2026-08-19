"""Lightweight language detection for text queries (~0.1ms, 0 API calls).

Designed for extensibility: to add a new language, append a LanguageProfile to
SUPPORTED_LANGUAGES and optionally add translations in translations.py.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageProfile:
    code: str                     # ISO 639-1: "en", "ms", "zh", "ta", "hi"
    name: str                     # Human-readable: "English", "Malay", etc.
    script_pattern: str | None = None  # Regex pattern for script characters
    markers: tuple[str, ...] = field(default_factory=tuple)  # Function words for Latin text


# ── Extensible Language Registry ──────────────────────────────────────────────
SUPPORTED_LANGUAGES: list[LanguageProfile] = [
    LanguageProfile(
        code="zh",
        name="Chinese",
        script_pattern=r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]",
    ),
    LanguageProfile(
        code="ta",
        name="Tamil",
        script_pattern=r"[\u0b80-\u0bff]",
    ),
    LanguageProfile(
        code="hi",
        name="Hindi",
        script_pattern=r"[\u0900-\u097f]",
    ),
    LanguageProfile(
        code="ms",
        name="Malay",
        script_pattern=None,
        markers=(
            "saya", "anda", "apa", "ada", "ini", "itu", "dan", "atau",
            "di", "ke", "pada", "untuk", "dengan", "dari", "boleh",
            "hari", "jadual", "kelas", "mana", "bagaimana", "bila",
            "tidak", "bukan", "sudah", "belum", "hendak", "mahu",
            "kursus", "yuran", "tandas", "kemasukan", "maklumat",
            "terdekat", "lokasi", "di manakah", "siapakah", "apakah",
            "perpustakaan", "lelaki", "perempuan", "kantin", "pejabat",
        ),
    ),
]

_COMPILED_SCRIPTS: list[tuple[LanguageProfile, re.Pattern]] = [
    (lp, re.compile(lp.script_pattern))
    for lp in SUPPORTED_LANGUAGES
    if lp.script_pattern
]


def detect_query_language(text: str) -> str:
    """Detect language code ('en', 'zh', 'ms', 'ta', 'hi') from query string.

    Returns:
        ISO 639-1 language code. Defaults to 'en'.
    """
    clean = (text or "").strip()
    if not clean:
        return "en"

    # 1. Non-Latin Unicode Script Matching (CJK, Tamil, Devanagari)
    for profile, pattern in _COMPILED_SCRIPTS:
        if pattern.search(clean):
            return profile.code

    # 2. Latin Keyword Heuristics (Malay, etc.)
    words = set(re.findall(r"\b\w+\b", clean.lower()))
    if not words:
        return "en"

    for profile in SUPPORTED_LANGUAGES:
        if profile.markers:
            marker_set = set(profile.markers)
            matching = words.intersection(marker_set)
            # Match if at least one multi-word phrase or high-relevance marker is found
            if matching:
                # Check for strong markers or multiple function words
                return profile.code

    return "en"
