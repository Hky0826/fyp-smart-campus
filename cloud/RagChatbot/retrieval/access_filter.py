"""
Access-level filter utilities.

Provides helper functions to validate and filter document chunks based on
a user's allowed access levels before passing them to the retriever.
These filters run entirely in backend code — the LLM never makes access
control decisions.
"""

from __future__ import annotations

from typing import List


# Valid access levels in hierarchy order
VALID_ACCESS_LEVELS: List[str] = ["PUBLIC", "STUDENT", "LECTURER", "ADMIN"]


def is_valid_access_level(level: str) -> bool:
    """Return True if the given string is a recognized access level."""
    return level in VALID_ACCESS_LEVELS


def filter_chunks_by_access(chunks: list, allowed_levels: List[str]) -> list:
    """
    Post-retrieval filter to remove any chunk whose access_level is not
    in the caller's allowed list.

    This acts as a second safety net after the SQL WHERE clause filter.
    Even if the database query somehow returns an unauthorized chunk, this
    function removes it before the chunk reaches the LLM.

    Args:
        chunks: List of ORM DocumentChunk objects (or similar dicts with
                an 'access_level' attribute/key).
        allowed_levels: The list of access levels the current user is
                        permitted to view.

    Returns:
        Filtered list containing only authorized chunks.
    """
    allowed_set = set(allowed_levels)
    filtered = [c for c in chunks if getattr(c, "access_level", None) in allowed_set]
    return filtered
