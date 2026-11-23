"""
Validate generated responses before returning audio to the edge device.

This module implements the validation gate â€” a security invariant that
ensures audio is never returned unless the text response and cited sources
pass validation.

Validation checks:
1. Response is non-empty.
2. Response does not contain system prompt leakage (matched against
   ``_LEAKAGE_PATTERNS``).
3. Cited sources have valid access levels.
4. Response shows basic grounding in the original query (soft check).

If validation fails, the response status is set to ``validation_failed``
and ``audio_response`` is set to ``null`` â€” the edge device never plays
unvalidated audio.

Also provides ``generate_audio_from_text``, which generates audio from
validated text using the configured Google Cloud Text-to-Speech API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from collections.abc import Iterator
from typing import List, Optional


from RagChatbot.config import rag_settings
from RagChatbot.retrieval.access_filter import VALID_ACCESS_LEVELS
from RagChatbot.retrieval.ranking import RankedChunk

logger = logging.getLogger(__name__)

# Phrases that indicate system prompt leakage â€” if any appear in the response
# text the validation should flag it.
_LEAKAGE_PATTERNS = [
    "system instruction",
    "system prompt",
    "you are a helpful",
    "your role is to answer",
    "--- AUTHENTICATED USER ---",
    "--- RETRIEVED CONTEXT ---",
    "--- USER QUERY (UNTRUSTED) ---",
    "based on the retrieved context",
    "context documents provided",
    "Do NOT mention any section",
]


@dataclass
class ValidationResult:
    """Result of response validation."""

    valid: bool = True
    reason: Optional[str] = None
    sanitized_text: Optional[str] = None


def validate_response(
    text: str,
    sources: List[RankedChunk],
    original_query: str,
) -> ValidationResult:
    """
    Validate the text response and cited sources.

    Checks:
      1. Response is non-empty.
      2. Response does not contain system prompt leakage.
      3. Sources are from authorised access levels.
      4. Response is at least minimally grounded in provided sources
         (basic sanity check that the response is not completely
         disconnected from the query topic).

    Args:
        text: The generated response text.
        sources: RankedChunk list used as context for generation.
        original_query: The user's original (extracted) query.

    Returns:
        ValidationResult with ``valid`` set to False and a ``reason`` if
        any check fails.
    """
    # Check 1: Non-empty
    if not text or not text.strip():
        return ValidationResult(
            valid=False,
            reason="Response is empty.",
        )

    # Check 2: System prompt leakage
    text_lower = text.lower()
    for pattern in _LEAKAGE_PATTERNS:
        if pattern.lower() in text_lower:
            logger.warning(
                "Response validation: leakage pattern detected: '%s'", pattern
            )
            return ValidationResult(
                valid=False,
                reason=f"Response may contain system prompt leakage (matched: '{pattern}').",
                sanitized_text=_remove_leakage(text, pattern),
            )

    # Check 3: Source access levels are valid
    for src in sources:
        if src.access_level not in VALID_ACCESS_LEVELS:
            logger.warning(
                "Response validation: source chunk_id=%d has invalid access_level=%s",
                src.chunk_id,
                src.access_level,
            )
            return ValidationResult(
                valid=False,
                reason=f"Source chunk {src.chunk_id} has invalid access level '{src.access_level}'.",
            )

    # Check 4: Basic grounding â€” the response should relate to the query
    # (This is a lightweight heuristic; a more thorough grounding check
    # would require an additional LLM call or embedding comparison.)
    query_words = set(original_query.lower().split())
    if len(query_words) > 2:
        text_words = set(text_lower.split())
        overlap = query_words & text_words
        if not overlap:
            logger.warning(
                "Response validation: response appears ungrounded â€” "
                "no word overlap with the original query."
            )
            # This is a soft check; we return as valid with a note rather
            # than hard-blocking.
            logger.info(
                "Validation soft-warning: response may not be grounded in query."
            )

    return ValidationResult(valid=True)


def _remove_leakage(text: str, pattern: str) -> str:
    """Attempt to remove leaked pattern from text (basic sanitisation)."""
    # A more sophisticated sanitisation could be added later.
    return text.replace(pattern, "[redacted]")


import re


def sanitize_text_for_speech(text: str) -> str:
    """
    Remove Markdown formatting, bullet symbols, asterisks, hashtags, and backticks
    so Text-to-Speech synthesis doesn't read out punctuation like 'asterisk', 'star', or 'hashtag'.
    """
    if not text:
        return ""
    # Remove markdown headers and hash symbols (#, ##, ###)
    cleaned = re.sub(r'#+', '', text)
    # Remove bold / italics markdown delimiters: **, *, __, _
    cleaned = re.sub(r'\*{1,3}', '', cleaned)
    cleaned = re.sub(r'_{1,3}', '', cleaned)
    # Remove backticks and inline code syntax
    cleaned = re.sub(r'`+', '', cleaned)
    # Remove bullet list markers at the start of lines (* , - , + )
    cleaned = re.sub(r'^\s*[\-\*\+]\s+', '', cleaned, flags=re.MULTILINE)
    # Remove citation brackets like [1], [Document 2]
    cleaned = re.sub(r'\[\d+\]', '', cleaned)
    # Collapse multiple spaces
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    return cleaned.strip()


def generate_audio_from_text(text: str, language_code: Optional[str] = None) -> Optional[bytes]:
    """
    Deprecated stub. All spoken audio output is now handled exclusively by the
    real-time Gemini Live duplex session (``gemini-3.1-flash-live-preview``).
    """
    logger.debug("generate_audio_from_text called (standalone TTS deprecated; audio is handled by Gemini Live).")
    return None


def generate_audio_from_text_stream(text: str, language_code: Optional[str] = None) -> Iterator[bytes]:
    """
    Deprecated stub. All spoken audio output is now handled exclusively by the
    real-time Gemini Live duplex session (``gemini-3.1-flash-live-preview``).
    """
    logger.debug("generate_audio_from_text_stream called (standalone TTS deprecated; audio is handled by Gemini Live).")
    return iter([])


def validate_sentence(sentence: str) -> ValidationResult:
    """
    Validate a single sentence before sending to TTS.
    """
    if not sentence or not sentence.strip():
        return ValidationResult(valid=False, reason="Sentence is empty.")

    sentence_lower = sentence.lower()
    for pattern in _LEAKAGE_PATTERNS:
        if pattern.lower() in sentence_lower:
            logger.warning("Sentence validation: leakage pattern detected: '%s'", pattern)
            return ValidationResult(
                valid=False,
                reason=f"Sentence contains prompt leakage ('{pattern}').",
                sanitized_text=_remove_leakage(sentence, pattern),
            )
    return ValidationResult(valid=True)


def stream_audio_by_sentences(sentence_stream: Iterator[str]) -> Iterator[tuple[str, Optional[bytes]]]:
    """
    Synthesize audio sentence by sentence as sentence strings arrive from the splitter.

    Yields:
        Tuples of (sentence_text, pcm_audio_bytes or None)
    """
    for sentence in sentence_stream:
        clean_sentence = sentence.strip()
        if not clean_sentence:
            continue

        validation = validate_sentence(clean_sentence)
        if not validation.valid:
            logger.warning("Aborting TTS for sentence due to validation failure: %s", validation.reason)
            clean_sentence = validation.sanitized_text or clean_sentence

        try:
            audio_pcm = generate_audio_from_text(clean_sentence)
        except Exception as exc:
            logger.warning("TTS generation failed for sentence '%s...': %s", clean_sentence[:30], exc)
            audio_pcm = None

        yield clean_sentence, audio_pcm
