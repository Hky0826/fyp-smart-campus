"""
Access-role filter utilities.

Provides helper functions to validate and filter document chunks based on
a user's allowed roles before passing them to the retriever.
These filters run entirely in backend code — the LLM never makes access
control decisions.
"""

from __future__ import annotations

import json
from typing import List, Any, Set

VALID_ROLES: List[str] = ["VISITOR", "STUDENT", "LECTURER", "STAFF", "ADMIN"]
VALID_ACCESS_LEVELS: List[str] = ["VISITOR", "STUDENT", "LECTURER", "STAFF", "ADMIN", "PUBLIC"]


def is_valid_access_level(level: str) -> bool:
    """Return True if the given string is a recognized access role/level."""
    return str(level).upper() in VALID_ACCESS_LEVELS


def _extract_chunk_roles(chunk: Any) -> Set[str]:
    """Helper to extract allowed roles set from chunk object or dict."""
    raw_roles = getattr(chunk, "allowed_roles", None)
    if raw_roles is None and isinstance(chunk, dict):
        raw_roles = chunk.get("allowed_roles")

    if isinstance(raw_roles, str):
        try:
            parsed = json.loads(raw_roles)
            if isinstance(parsed, list):
                return {str(r).upper() for r in parsed}
        except Exception:
            return {raw_roles.upper()}
    elif isinstance(raw_roles, (list, set, tuple)):
        return {str(r).upper() for r in raw_roles}

    # Fallback to access_level if allowed_roles is missing
    raw_lvl = getattr(chunk, "access_level", None)
    if raw_lvl is None and isinstance(chunk, dict):
        raw_lvl = chunk.get("access_level")
    if raw_lvl:
        lvl_str = str(raw_lvl).upper()
        if lvl_str == "PUBLIC":
            return {"VISITOR"}
        return {lvl_str}

    return {"VISITOR"}


def filter_chunks_by_access(chunks: list, allowed_roles: List[str]) -> list:
    """
    Post-retrieval safety filter to remove any chunk whose allowed_roles does not
    intersect with the caller's role set.
    """
    user_roles_set = {str(r).upper() for r in (allowed_roles or [])}
    user_roles_set.add("VISITOR")

    # Admins bypass role restrictions
    if user_roles_set & {"ADMIN", "SUPER_ADMIN", "SYSTEM_ADMIN", "CONTENT_ADMIN"}:
        return list(chunks)

    filtered = []
    for c in chunks:
        c_roles = _extract_chunk_roles(c)
        if "VISITOR" in c_roles or "PUBLIC" in c_roles or bool(user_roles_set & c_roles):
            filtered.append(c)

    return filtered
