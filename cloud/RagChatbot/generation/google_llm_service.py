"""
Google AI Studio LLM service for answer generation.

Calls the configured Gemini model using only the authorized context
that has already passed RBAC and prompt injection checks.
The API key is loaded from the backend configuration and is never
returned in responses or logged.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Dict, Any

from google import genai
from google.genai import types

from RagChatbot.config import rag_settings
from RagChatbot.generation.prompt_builder import build_prompt
from RagChatbot.retrieval.ranking import RankedChunk

logger = logging.getLogger(__name__)


def generate_answer(query: str, chunks: List[RankedChunk], chat_history: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Generate a grounded answer using the Google Gemini model.

    This function is called only after:
      1. The query has passed prompt injection checks.
      2. Chunks have been RBAC-filtered and re-ranked.

    Args:
        query: The sanitized user query.
        chunks: Authorized, re-ranked document chunks to use as context.
        chat_history: Optional list of previous interactions (dicts with 'user' and 'assistant' keys).

    Returns:
        The generated answer string.

    Raises:
        RuntimeError: If the Google API call fails.
    """
    system_prompt, user_message = build_prompt(query, chunks, chat_history)

    try:
        client = genai.Client(api_key=rag_settings.GOOGLE_API_KEY)

        response = client.models.generate_content(
            model=rag_settings.LLM_MODEL,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=rag_settings.MAX_OUTPUT_TOKENS,
                temperature=rag_settings.TEMPERATURE,
            ),
        )

        # Extract the text from the first candidate
        answer = response.text.strip()
        logger.info(
            "Generation complete. query_len=%d, chunks_used=%d, answer_len=%d",
            len(query),
            len(chunks),
            len(answer),
        )
        return answer

    except Exception as exc:
        logger.error("Google LLM generation failed: %s", exc)
        raise RuntimeError(f"Answer generation failed: {exc}") from exc


def generate_no_access_response() -> str:
    """
    Return a polite, pre-defined response when the user has no access to
    any relevant documents. This avoids calling the LLM unnecessarily
    and ensures a consistent message.
    """
    return (
        "I'm sorry, but I don't have any documents available that match your question "
        "based on your current access level. Please contact the campus administrator "
        "if you believe you should have access to this information."
    )
