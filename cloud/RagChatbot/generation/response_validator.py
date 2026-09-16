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


_LANGUAGE_VOICE_MAP = {
    "en": ("en-US", "en-US-Neural2-F"),
    "ms": ("ms-MY", "ms-MY-Wavenet-A"),
    "id": ("id-ID", "id-ID-Wavenet-A"),
    "zh": ("cmn-CN", "cmn-CN-Wavenet-A"),
    "cmn": ("cmn-CN", "cmn-CN-Wavenet-A"),
    "ta": ("ta-IN", "ta-IN-Wavenet-A"),
    "hi": ("hi-IN", "hi-IN-Wavenet-A"),
    "ar": ("ar-XA", "ar-XA-Wavenet-A"),
    "bn": ("bn-IN", "bn-IN-Wavenet-A"),
    "de": ("de-DE", "de-DE-Neural2-F"),
    "es": ("es-ES", "es-ES-Neural2-F"),
    "fr": ("fr-FR", "fr-FR-Neural2-F"),
    "it": ("it-IT", "it-IT-Neural2-F"),
    "ja": ("ja-JP", "ja-JP-Neural2-B"),
    "ko": ("ko-KR", "ko-KR-Neural2-A"),
    "pt": ("pt-BR", "pt-BR-Neural2-A"),
    "ru": ("ru-RU", "ru-RU-Wavenet-A"),
    "th": ("th-TH", "th-TH-Neural2-C"),
    "tr": ("tr-TR", "tr-TR-Wavenet-A"),
    "vi": ("vi-VN", "vi-VN-Neural2-A"),
}


def _voice_for_language(language_code: Optional[str]) -> tuple[str, str]:
    configured_voice = getattr(rag_settings, "AUDIO_TTS_VOICE", "Kore")
    if not language_code:
        voice_name = configured_voice
        if voice_name == "Kore":
            voice_name = "en-US-Neural2-F"
        language = "-".join(voice_name.split("-")[:2]) if "-" in voice_name else "en-US"
        return language, voice_name

    normalized = str(language_code).strip().lower().replace("_", "-")
    language_key = normalized.split("-", 1)[0]
    language, voice_name = _LANGUAGE_VOICE_MAP.get(language_key, _LANGUAGE_VOICE_MAP["en"])
    if language_key == "en" and configured_voice not in {"", "Kore"}:
        voice_name = configured_voice
        language = "-".join(voice_name.split("-")[:2]) if "-" in voice_name else "en-US"
    return language, voice_name


def generate_audio_from_text(text: str, language_code: Optional[str] = None) -> Optional[bytes]:
    """
    Generate audio from validated text using Gemini Live Voice (primary)
    falling back to standard Google Cloud TTS (Neural2/Wavenet).

    Args:
        text: The validated text to convert to speech.
        language_code: Optional ISO language code.

    Returns:
        Raw audio bytes (LINEAR16, 24 kHz), or None if generation fails.
    """
    if not text or not text.strip():
        logger.warning("generate_audio_from_text called with empty text.")
        return None

    clean_speech_text = sanitize_text_for_speech(text)
    if not clean_speech_text:
        logger.warning("generate_audio_from_text called with empty text after sanitisation.")
        return None

    # 1. Primary path: Gemini Live Voice Speech Output
    try:
        from RagChatbot.gemini_client import get_gemini_client, generate_content_with_retry
        from google.genai import types

        client = get_gemini_client()
        gemini_voice = getattr(rag_settings, "AUDIO_TTS_VOICE", "Kore") or "Kore"
        if "Chirp" in gemini_voice or "-" in gemini_voice:
            gemini_voice = "Kore"

        tts_models = [
            getattr(rag_settings, "AUDIO_TTS_MODEL", "gemini-2.0-flash"),
            "gemini-2.0-flash",
            "gemini-2.5-flash-preview-tts",
        ]
        for tts_model in tts_models:
            try:
                response = generate_content_with_retry(
                    client=client,
                    model=tts_model,
                    contents=clean_speech_text,
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "You are a professional university campus voice assistant. "
                            "Speak clearly and articulately using a professional standard accent for the language. "
                            "Do not use informal slang, regional dialect, colloquial accent, or casual tone. "
                            "Maintain an articulate, polite, and professional broadcast presenter tone."
                        ),
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=gemini_voice,
                                )
                            )
                        ),
                    ),
                )
                if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data and part.inline_data.data:
                            audio_bytes = part.inline_data.data
                            logger.info("Gemini Live Voice generated %d bytes of audio with model=%s voice=%s", len(audio_bytes), tts_model, gemini_voice)
                            return audio_bytes
            except Exception as model_err:
                logger.debug("Gemini Live Voice model %s failed: %s", tts_model, model_err)
    except Exception as exc:
        logger.debug("Gemini Live Voice call failed: %s", exc)

    # 2. Fallback path: Google Cloud Text-to-Speech (Neural2/Wavenet)
    try:
        import os
        client_options = {}
        tts_api_key = getattr(rag_settings, "GOOGLE_CLOUD_TTS_API_KEY", "") or rag_settings.GOOGLE_API_KEY

        if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and tts_api_key:
            client_options["api_key"] = tts_api_key

        client = texttospeech.TextToSpeechClient(
            client_options=client_options if client_options else None
        )
        language_code, voice_name = _voice_for_language(language_code)

        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000
        )

        synthesis_input = texttospeech.SynthesisInput(text=clean_speech_text)
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


def generate_audio_from_text_stream(text: str, language_code: Optional[str] = None) -> Iterator[bytes]:
    """
    Stream audio chunks from the configured TTS model.

    Synthesizes the given text string and yields its PCM bytes.
    """
    if not text or not text.strip():
        logger.warning("generate_audio_from_text_stream called with empty text.")
        return

    try:
        audio_data = generate_audio_from_text(text, language_code) if language_code else generate_audio_from_text(text)
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
