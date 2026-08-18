"""
config/semantic_rules_loader.py
--------------------------------
Loads and validates semantic_rules.yaml, converting it into the format
expected by OcrNodeGenerator._classify_room_type().

This module is the single source of truth for semantic classification config.
The YAML file is loaded once at process start and cached.

Expected YAML format (semantic_rules.yaml):
    rules:
      - node_type: "CLASSROOM"
        keywords: ["lecture", "lab", ...]
      - node_type: "FOOD"
        keywords: ["kitchen", "canteen", ...]
    default_node_type: "OTHER"
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# Absolute path to the rules file — always resolved relative to this file
_RULES_FILE = Path(__file__).parent / "semantic_rules.yaml"

# Supported navigation system node types (must match frontend mapConstants.js)
SUPPORTED_NODE_TYPES = frozenset({
    "CLASSROOM",
    "CORRIDOR",
    "ENTRANCE",
    "STAIRWELL",
    "ELEVATOR",
    "FOOD",
    "OFFICE",
    "FACILITIES",
    "HALL",
    "WASHROOM",
    "OUTDOOR",
    "SOCIAL SPACES",
    "OTHER",
})

_DEFAULT_FALLBACK = "OTHER"


@lru_cache(maxsize=1)
def load_semantic_rules() -> Tuple[List[Tuple[List[str], str]], str]:
    """
    Load and cache semantic_rules.yaml.

    Returns:
        (rules, default_node_type)
        rules: List of (keywords, node_type) tuples in priority order (first match wins).
        default_node_type: Fallback type when no keyword matches (default: "OTHER").

    Raises:
        RuntimeError: If the YAML file is missing or malformed.
    """
    try:
        import yaml  # PyYAML — already in requirements.txt
    except ImportError:
        raise RuntimeError(
            "PyYAML is required to load semantic_rules.yaml. "
            "Run: pip install pyyaml"
        )

    if not _RULES_FILE.exists():
        raise RuntimeError(
            f"Semantic rules file not found: {_RULES_FILE}\n"
            "Expected at: src/config/semantic_rules.yaml"
        )

    try:
        with _RULES_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse semantic_rules.yaml: {exc}"
        ) from exc

    if not isinstance(data, dict) or "rules" not in data:
        raise RuntimeError(
            "semantic_rules.yaml must contain a top-level 'rules' list."
        )

    rules: List[Tuple[List[str], str]] = []
    invalid_types = []

    for entry in data["rules"]:
        node_type = str(entry.get("node_type", "")).strip()
        keywords = [str(kw).lower().strip() for kw in entry.get("keywords", [])]

        if node_type not in SUPPORTED_NODE_TYPES:
            invalid_types.append(node_type)
            logger.warning(
                "Unsupported node_type in semantic_rules.yaml — skipped",
                node_type=node_type,
                supported=list(SUPPORTED_NODE_TYPES),
            )
            continue

        if keywords:
            rules.append((keywords, node_type))

    if invalid_types:
        logger.warning(
            "Some node types in semantic_rules.yaml are not supported by the navigation system",
            invalid_types=invalid_types,
        )

    default_type = str(data.get("default_node_type", _DEFAULT_FALLBACK)).strip()
    if default_type not in SUPPORTED_NODE_TYPES:
        logger.warning(
            "default_node_type is not a supported type — falling back to 'OTHER'",
            configured=default_type,
        )
        default_type = _DEFAULT_FALLBACK

    logger.info(
        "Semantic rules loaded",
        rules_file=str(_RULES_FILE),
        rule_count=len(rules),
        default_node_type=default_type,
    )
    return rules, default_type
