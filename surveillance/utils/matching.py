"""Face embedding template matching utility."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FaceTemplate:
    """Registered face template for a user."""

    user_id: str
    identity: str
    template_name: str
    embedding: np.ndarray  # 512-d normalized float32 vector
    is_active: bool = True


@dataclass
class MatchResult:
    matched: bool
    identity: str
    user_id: Optional[str]
    similarity: float
    matched_template: Optional[str] = None


def count_templates_by_user(templates: Iterable[FaceTemplate]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for t in templates:
        counts[t.user_id] = counts.get(t.user_id, 0) + 1
    return counts


class TemplateMatcher:
    """Matches unknown query embeddings against enrolled database face templates using cosine similarity."""

    def __init__(self, threshold: float = 0.65) -> None:
        self.threshold = float(threshold)

    def match(
        self,
        query_embedding: np.ndarray,
        templates: List[FaceTemplate],
        threshold: Optional[float] = None,
        include_inactive: bool = False,
    ) -> MatchResult:
        cutoff = float(self.threshold if threshold is None else threshold)

        if query_embedding is None or query_embedding.size == 0 or not templates:
            return MatchResult(matched=False, identity="unknown", user_id=None, similarity=0.0)

        query = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
        q_norm = np.linalg.norm(query)
        if q_norm > 1e-12:
            query = query / q_norm

        best_score = -1.0
        best_template: Optional[FaceTemplate] = None

        for t in templates:
            if not include_inactive and not t.is_active:
                continue

            target = np.asarray(t.embedding, dtype=np.float32).reshape(-1)
            t_norm = np.linalg.norm(target)
            if t_norm > 1e-12:
                target = target / t_norm

            sim = float(np.dot(query, target))
            if sim > best_score:
                best_score = sim
                best_template = t

        if best_template is not None and best_score >= cutoff:
            return MatchResult(
                matched=True,
                identity=best_template.identity,
                user_id=best_template.user_id,
                similarity=best_score,
                matched_template=best_template.template_name,
            )

        return MatchResult(
            matched=False,
            identity="unknown",
            user_id=None,
            similarity=max(0.0, float(best_score)),
            matched_template=best_template.template_name if best_template else None,
        )
