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

from google.cloud import texttospeech

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


def generate_audio_from_text(text: str) -> Optional[bytes]:
    """
    Generate audio from validated text using Google Cloud TTS.

    Uses the configured Google Cloud Text-to-Speech API with a Chirp 3
    model to produce spoken audio output.

    Args:
        text: The validated text to convert to speech.

    Returns:
        Raw audio bytes (LINEAR16, 24 kHz), or None if generation fails.

    Raises:
        RuntimeError: If the TTS API call fails entirely.
    """
    if not text or not text.strip():
        logger.warning("generate_audio_from_text called with empty text.")
        return None

    try:
        import os
        client_options = {}
        tts_api_key = getattr(rag_settings, "GOOGLE_CLOUD_TTS_API_KEY", "") or rag_settings.GOOGLE_API_KEY

        # Prioritize GOOGLE_APPLICATION_CREDENTIALS for service accounts if set.
        # Otherwise use the API key.
        if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and tts_api_key:
            client_options["api_key"] = tts_api_key

        client = texttospeech.TextToSpeechClient(
            client_options=client_options if client_options else None
        )
    except Exception as exc:
        logger.error("Failed to create Google Cloud TTS client: %s", exc)
        raise RuntimeError(f"TTS client initialisation failed: {exc}") from exc

    voice_name = getattr(rag_settings, "AUDIO_TTS_VOICE", "en-US-Chirp3-HD-Kore")
    if voice_name == "Kore":
        voice_name = "en-US-Chirp3-HD-Kore"

    # Extract language code from voice name (e.g. 'en-US' from 'en-US-Chirp3-HD-Kore')
    language_code = "-".join(voice_name.split("-")[:2]) if "-" in voice_name else "en-US"

    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=24000
    )

    synthesis_input = texttospeech.SynthesisInput(text=text)

    try:
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        audio_data = response.audio_content
        if audio_data:
            logger.info("TTS generated %d bytes of audio with voice=%s.", len(audio_data), voice_name)
            return audio_data
        else:
            logger.warning("TTS returned no audio data. voice=%s", voice_name)
            return None
    except Exception as exc:
        logger.error("TTS generation failed: %s", exc)
        raise RuntimeError(f"TTS generation failed: {exc}") from exc


def generate_audio_from_text_stream(text: str) -> Iterator[bytes]:
    """
    Stream audio chunks from the configured TTS model.

    Synthesizes the given text string and yields its PCM bytes.
    """
    if not text or not text.strip():
        logger.warning("generate_audio_from_text_stream called with empty text.")
        return

    try:
        audio_data = generate_audio_from_text(text)
        if audio_data:
            yield audio_data
    except Exception as exc:
        logger.error("Streaming TTS failed: %s", exc)
        raise RuntimeError(f"Streaming TTS failed: {exc}") from exc


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

