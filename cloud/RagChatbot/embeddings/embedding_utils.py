"""
Utility helpers for working with embedding vectors.
Covers serialization, dimensionality checks, and cosine similarity.
"""

from __future__ import annotations

import json
import math
from typing import List, Union


def vector_to_mysql_string(vector: List[float]) -> str:
    """
    Serialize a Python float list to the MySQL VECTOR string format.

    MySQL 9 native VECTOR columns accept JSON-array strings via STRING_TO_VECTOR()
    when inserting, and return them via VECTOR_TO_STRING() when reading.

    Example:
        [0.1, 0.2, 0.3]  ->  "[0.10000000,0.20000000,0.30000000]"
    """
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Compute the cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Similarity score in [-1, 1]. Returns 0.0 if either vector is zero.
    """
    if len(a) != len(b):
        raise ValueError(
            f"Vector dimension mismatch: {len(a)} vs {len(b)}"
        )

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def validate_embedding_dim(embedding: List[float], expected_dim: int) -> None:
    """
    Validate that the embedding has the expected dimensionality.

    Args:
        embedding: The embedding vector to validate.
        expected_dim: The expected number of dimensions.

    Raises:
        ValueError: If the dimension does not match.
    """
    if len(embedding) != expected_dim:
        raise ValueError(
            f"Embedding dimension {len(embedding)} does not match "
            f"expected dimension {expected_dim}."
        )
