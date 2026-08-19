"""
Prompt-injection protection layer.

Scans user-supplied queries for patterns that indicate attempts to:
  - Override system instructions
  - Bypass role-based access control
  - Exfiltrate system internals (prompts, schema, API keys)
  - Manipulate the LLM to ignore safety guidelines

This guard runs BEFORE retrieval, so no database call or LLM call is
made for blocked requests.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Injection Pattern Definitions ─────────────────────────────────────────────
# Each pattern is a compiled regular expression. Matching any one of them
# causes the query to be flagged. Patterns are case-insensitive.

_INJECTION_PATTERNS: List[re.Pattern] = [
    # Instruction override
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|old)\s+instruction", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above|your)\s+instruction", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior|above|your)\s+instruction", re.IGNORECASE),
    re.compile(r"override\s+(your\s+)?(rules|instruction|system|prompt)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a\s+)?", re.IGNORECASE),  # roleplay jailbreaks
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+are|a\s+)?", re.IGNORECASE),

    # System prompt / internals exfiltration
    re.compile(r"(print|show|reveal|output|display|repeat|tell me)\s+(your\s+)?(system\s+prompt|instructions|initial\s+prompt)", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?(system\s+prompt|hidden\s+prompt|initial\s+prompt)", re.IGNORECASE),
    re.compile(r"what\s+(are\s+)?your\s+(hidden\s+)?(instruction|rule|prompt|directive)", re.IGNORECASE),
    re.compile(r"(show|reveal|print)\s+(all\s+)?(admin|hidden|restricted|confidential)\s+(document|data|record|file)", re.IGNORECASE),

    # Access bypass
    re.compile(r"bypass\s+(role|rbac|access\s+control|permission|restriction)", re.IGNORECASE),
    re.compile(r"grant\s+(me\s+)?(admin|full|all|unrestricted)\s+access", re.IGNORECASE),
    re.compile(r"(as\s+an?\s+)?(admin|root|superuser|administrator)\s*(,\s*)?show\s+me", re.IGNORECASE),
    re.compile(r"simulate\s+(being\s+)?(an?\s+)?(admin|superuser|root|developer|administrator)", re.IGNORECASE),

    # API key / credential extraction
    re.compile(r"(print|show|reveal|give me)\s+(the\s+)?(api\s+key|secret\s+key|password|token|credential)", re.IGNORECASE),
    re.compile(r"(what\s+is|tell me)\s+(the\s+)?(google\s+)?(api\s+key|api\s+secret)", re.IGNORECASE),

    # Database schema exposure
    re.compile(r"(show|reveal|describe|dump)\s+(the\s+)?(database|db|table|schema|column|sql)", re.IGNORECASE),

    # Stack trace / error fishing
    re.compile(r"(cause|trigger|generate)\s+(an?\s+)?(error|exception|traceback|stack\s+trace)", re.IGNORECASE),

    # DAN / jailbreak keywords
    re.compile(r"\b(?:do\s+anything\s+now|DAN\s+mode|act\s+as\s+DAN|you\s+are\s+DAN|DAN\s*:)\b", re.IGNORECASE),  # "Do Anything Now"
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"developer\s+mode", re.IGNORECASE),
    re.compile(r"no\s+filter\s+mode", re.IGNORECASE),
]


@dataclass
class GuardResult:
    """Result from the prompt guard check."""

    is_safe: bool
    matched_pattern: Optional[str] = None
    sanitized_query: Optional[str] = None


def check_query(query: str) -> GuardResult:
    """
    Check a user query for prompt injection attempts.

    Args:
        query: The raw user query string.

    Returns:
        GuardResult with is_safe=True if the query appears benign,
        or is_safe=False with the matched pattern description if blocked.
    """
    if not query or not query.strip():
        return GuardResult(is_safe=False, matched_pattern="empty_query")

    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(query)
        if match:
            matched_text = match.group(0)
            logger.warning(
                "Prompt injection detected. Pattern='%s', matched='%s', "
                "query_snippet='%.80s'",
                pattern.pattern,
                matched_text,
                query,
            )
            return GuardResult(is_safe=False, matched_pattern=pattern.pattern)

    # Light sanitization: strip leading/trailing whitespace.
    # Do NOT alter the content further, as it may affect retrieval quality.
    sanitized = query.strip()

    return GuardResult(is_safe=True, sanitized_query=sanitized)
