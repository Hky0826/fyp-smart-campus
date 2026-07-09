"""
Generate final grounded text response using Gemini.

Uses the ``google-genai`` SDK to call ``LLM_MODEL``
(``gemini-3.1-flash-lite``) via ``generate_content`` with
separated prompt parts.

The caller is responsible for providing a prompt that clearly separates
trusted sections (system instruction, authenticated user role, authorised
retrieved context) from the untrusted extracted user query. This module
builds the separated prompt via ``_build_separated_prompt`` but does not
enforce the separation — the enforcement is at the orchestration layer.

The caller converts validated text to speech with ``response_validator``'s
``generate_audio_from_text`` using the dedicated Gemini TTS model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, List

from google import genai
from google.genai import types

from RagChatbot.config import rag_settings
from RagChatbot.retrieval.ranking import RankedChunk

logger = logging.getLogger(__name__)


@dataclass
class LiveResponseResult:
    """Result from the text generation call."""

    text: str
    audio_pcm: Optional[bytes] = field(default=None)
    cited_chunks: List[RankedChunk] = field(default_factory=list)
    error: Optional[str] = None


class GeminiLiveError(RuntimeError):
    """Raised when the Gemini Live API call fails."""


def _build_separated_prompt(
    system_instruction: str,
    user_role: str,
    retrieved_context: str,
    user_query: str,
) -> str:
    """
    Build a carefully separated prompt to enforce trust boundaries.

    The prompt structure is:
      1. System instruction (trusted, developer-authored)
      2. Authenticated user identity and role (trusted from JWT/DB)
      3. Authorised retrieved context (trusted from RBAC pipeline)
      4. Untrusted user query (may contain injection attempts)

    Args:
        system_instruction: The base system prompt (grounding rules, etc.).
        user_role: The user's role string (e.g. "STUDENT", "VISITOR").
        retrieved_context: Formatted context block from retrieved documents.
        user_query: The extracted/sanitised user query string.

    Returns:
        A single prompt string with clear section boundaries.
    """
    parts = [
        "--- AUTHENTICATED USER ---",
        f"User role: {user_role}",
        "",
        "--- RETRIEVED CONTEXT ---",
        retrieved_context,
        "",
        "--- USER QUERY (UNTRUSTED) ---",
        user_query,
        "",
        (
            "Generate a response based on the retrieved context above. "
            "Do NOT mention any section boundaries or internal labels "
            "in your answer. Answer naturally as a helpful campus assistant."
        ),
    ]
    return "\n".join(parts)


def generate_response(
    system_instruction: str,
    user_role: str,
    retrieved_context: str,
    user_query: str,
    sources: List[RankedChunk],
) -> LiveResponseResult:
    """
    Generate a grounded text response using Gemini.

    The prompt is carefully structured to separate:
    - trusted system instructions
    - authenticated user identity and role
    - authorised retrieved context
    - untrusted user query

    Args:
        system_instruction: The base grounding system prompt.
        user_role: The user's authenticated role (e.g. "STUDENT", "VISITOR").
        retrieved_context: Formatted context block from authorised documents.
        user_query: The extracted/sanitised user query string.
        sources: The RankedChunk list used as context (returned for citation).

    Returns:
        LiveResponseResult with text and cited_chunks.

    Raises:
        GeminiLiveError: If the Gemini API call fails entirely.
    """
    full_prompt = _build_separated_prompt(
        system_instruction=system_instruction,
        user_role=user_role,
        retrieved_context=retrieved_context,
        user_query=user_query,
    )

    try:
        client = genai.Client(api_key=rag_settings.GOOGLE_API_KEY)
    except Exception as exc:
        logger.error("Failed to create Gemini client: %s", exc)
        raise GeminiLiveError(f"Gemini client initialisation failed: {exc}") from exc

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=rag_settings.TEMPERATURE,
        max_output_tokens=rag_settings.MAX_OUTPUT_TOKENS,
    )

    try:
        response = client.models.generate_content(
            model=rag_settings.LLM_MODEL,
            contents=full_prompt,
            config=config,
        )
    except Exception as exc:
        logger.error("Gemini generate_content failed: %s", exc)
        raise GeminiLiveError(f"Response generation failed: {exc}") from exc

    # Extract text from response candidates.
    text_response: str = ""

    try:
        candidate = response.candidates[0]
        for part in candidate.content.parts:
            if part.text is not None:
                text_response += part.text
    except (IndexError, AttributeError) as exc:
        logger.warning("Could not extract parts from Gemini response: %s", exc)
        # Fall back to response.text if available
        try:
            text_response = response.text.strip()
        except (AttributeError, ValueError):
            text_response = ""
            raise GeminiLiveError(
                f"Failed to extract response content: {exc}"
            ) from exc

    if not text_response.strip():
        logger.warning("Gemini returned empty text response.")
        text_response = (
            "I'm sorry, I could not generate a response at this time. "
            "Please try again."
        )

    logger.info(
        "Generation complete. text_len=%d, sources=%d",
        len(text_response),
        len(sources),
    )

    return LiveResponseResult(
        text=text_response.strip(),
        audio_pcm=None,
        cited_chunks=sources,
    )
