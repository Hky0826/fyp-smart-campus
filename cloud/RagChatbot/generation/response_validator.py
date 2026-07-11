"""
Validate generated responses before returning audio to the edge device.

This module implements the validation gate — a security invariant that
ensures audio is never returned unless the text response and cited sources
pass validation.

Validation checks:
1. Response is non-empty.
2. Response does not contain system prompt leakage (matched against
   ``_LEAKAGE_PATTERNS``).
3. Cited sources have valid access levels.
4. Response shows basic grounding in the original query (soft check).

If validation fails, the response status is set to ``validation_failed``
and ``audio_response`` is set to ``null`` — the edge device never plays
unvalidated audio.

Also provides ``generate_audio_from_text``, which generates audio from
validated text using the configured Gemini 2.5 Flash TTS model
(``AUDIO_TTS_MODEL``, default ``gemini-2.5-flash-preview-tts``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from collections.abc import Iterator
from typing import List, Optional

from google import genai
from google.genai import types

from RagChatbot.config import rag_settings
from RagChatbot.retrieval.access_filter import VALID_ACCESS_LEVELS
from RagChatbot.retrieval.ranking import RankedChunk

logger = logging.getLogger(__name__)

# Phrases that indicate system prompt leakage — if any appear in the response
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

_UNAVAILABLE_TTS_MODELS: set[str] = set()


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

    # Check 4: Basic grounding — the response should relate to the query
    # (This is a lightweight heuristic; a more thorough grounding check
    # would require an additional LLM call or embedding comparison.)
    query_words = set(original_query.lower().split())
    if len(query_words) > 2:
        text_words = set(text_lower.split())
        overlap = query_words & text_words
        if not overlap:
            logger.warning(
                "Response validation: response appears ungrounded — "
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
    Generate audio from validated text using Gemini TTS.

    Uses the ``AUDIO_TTS_MODEL`` configured in settings with
    ``response_modalities=["AUDIO"]`` to produce spoken audio output.

    Args:
        text: The validated text to convert to speech.

    Returns:
        Raw PCM audio bytes (24 kHz mono int16), or None if generation
        fails or no audio part is returned.

    Raises:
        RuntimeError: If the Gemini API call fails entirely.
    """
    if not text or not text.strip():
        logger.warning("generate_audio_from_text called with empty text.")
        return None

    tts_prompt = (
        "Read the following text aloud in a clear, natural speaking voice:\n\n"
        f"{text}"
    )

    try:
        client = genai.Client(api_key=rag_settings.GOOGLE_API_KEY)
    except Exception as exc:
        logger.error("Failed to create Gemini client for TTS: %s", exc)
        raise RuntimeError(f"Gemini client initialisation failed: {exc}") from exc

    config = types.GenerateContentConfig(
        temperature=0.0,
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=getattr(rag_settings, "AUDIO_TTS_VOICE", "Kore")
                )
            )
        ),
    )

    last_error: Exception | None = None
    attempted_models: list[str] = []
    for model_name in _candidate_tts_models():
        attempted_models.append(model_name)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=tts_prompt,
                config=config,
            )
        except Exception as exc:
            last_error = exc
            if _is_not_found_error(exc):
                _UNAVAILABLE_TTS_MODELS.add(model_name)
            logger.warning("TTS model failed. model=%s error=%s", model_name, exc)
            continue

        audio_data = _extract_audio_data(response)
        if audio_data is not None:
            logger.info("TTS generated %d bytes of audio with model=%s.", len(audio_data), model_name)
            return audio_data

        logger.warning("TTS returned no audio part. model=%s", model_name)

    if last_error is not None:
        logger.error(
            "TTS generation failed for all models. attempted_models=%s",
            attempted_models,
        )
        raise RuntimeError(f"TTS generation failed: {last_error}") from last_error

    logger.warning("TTS returned no audio part.")
    return None


def generate_audio_from_text_stream(text: str) -> Iterator[bytes]:
    """
    Stream audio chunks from the configured Gemini TTS model.

    Yields raw PCM audio bytes (24 kHz mono int16) as the SDK returns them.
    This is used by the edge-device streaming endpoint so playback can start
    before the full TTS response has been generated.

    Raises:
        RuntimeError: If no configured/fallback TTS model can produce audio.
    """
    if not text or not text.strip():
        logger.warning("generate_audio_from_text_stream called with empty text.")
        return

    tts_prompt = (
        "Read the following text aloud in a clear, natural speaking voice:\n\n"
        f"{text}"
    )

    try:
        client = genai.Client(api_key=rag_settings.GOOGLE_API_KEY)
    except Exception as exc:
        logger.error("Failed to create Gemini client for streaming TTS: %s", exc)
        raise RuntimeError(f"Gemini client initialisation failed: {exc}") from exc

    config = types.GenerateContentConfig(
        temperature=0.0,
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=getattr(rag_settings, "AUDIO_TTS_VOICE", "Kore")
                )
            )
        ),
    )

    last_error: Exception | None = None
    attempted_models: list[str] = []
    for model_name in _candidate_tts_models():
        attempted_models.append(model_name)
        yielded_any = False
        try:
            responses = client.models.generate_content_stream(
                model=model_name,
                contents=tts_prompt,
                config=config,
            )
            for response in responses:
                audio_data = _extract_audio_data(response)
                if audio_data is None:
                    continue
                yielded_any = True
                logger.debug(
                    "Streaming TTS yielded %d bytes with model=%s.",
                    len(audio_data),
                    model_name,
                )
                yield audio_data
        except Exception as exc:
            last_error = exc
            if yielded_any:
                logger.error("Streaming TTS failed after yielding audio: %s", exc)
                raise RuntimeError(f"Streaming TTS failed: {exc}") from exc
            if _is_not_found_error(exc):
                _UNAVAILABLE_TTS_MODELS.add(model_name)
            logger.warning("Streaming TTS model failed. model=%s error=%s", model_name, exc)
            continue

        if yielded_any:
            logger.info("Streaming TTS completed with model=%s.", model_name)
            return

        logger.warning("Streaming TTS returned no audio part. model=%s", model_name)

    if last_error is not None:
        logger.error(
            "Streaming TTS failed for all models. attempted_models=%s",
            attempted_models,
        )
        raise RuntimeError(f"Streaming TTS failed: {last_error}") from last_error

    logger.warning("Streaming TTS returned no audio part.")


def _candidate_tts_models() -> list[str]:
    configured = str(getattr(rag_settings, "AUDIO_TTS_MODEL", "") or "")
    fallbacks = str(getattr(rag_settings, "AUDIO_TTS_FALLBACK_MODELS", "") or "")
    candidates: list[str] = []
    for model_name in [configured, *fallbacks.split(",")]:
        cleaned = model_name.strip()
        if cleaned and cleaned not in candidates and cleaned not in _UNAVAILABLE_TTS_MODELS:
            candidates.append(cleaned)
    return candidates


def _is_not_found_error(exc: Exception) -> bool:
    text = str(exc).upper()
    return "404" in text or "NOT_FOUND" in text or "NOT FOUND" in text


def _extract_audio_data(response: object) -> Optional[bytes]:
    try:
        candidate = response.candidates[0]
        for part in candidate.content.parts:
            if part.inline_data is not None and part.inline_data.mime_type.startswith(
                "audio/"
            ):
                return part.inline_data.data
    except (IndexError, AttributeError) as exc:
        logger.warning("Could not extract audio part from TTS response: %s", exc)
    return None
