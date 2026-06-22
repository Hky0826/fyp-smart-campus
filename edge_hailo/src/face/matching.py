"""Cosine-similarity matching for single and multi-template identities."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class FaceTemplate:
    user_id: str
    embedding: np.ndarray
    template_name: Optional[str] = None
    identity: Optional[str] = None
    is_active: bool = True
    metadata: Dict[str, object] = field(default_factory=dict)

    @property
    def display_identity(self) -> str:
        return str(self.identity if self.identity not in (None, "") else self.user_id)


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    user_id: Optional[str]
    identity: str
    similarity: float
    matched_template: Optional[str] = None
    is_active: bool = True
    reason: Optional[str] = None


class TemplateMatcher:
    """Best-score-per-user cosine matcher.

    Thresholds are similarity thresholds, not distance thresholds. They must be
    tuned on real camera footage from the target device.
    """

    def __init__(self, threshold: float, aggregation: str = "best") -> None:
        self.threshold = float(threshold)
        if aggregation != "best":
            raise ValueError("Only best-score aggregation is currently implemented")
        self.aggregation = aggregation

    @staticmethod
    def normalize(embedding: np.ndarray) -> np.ndarray:
        vec = np.asarray(embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if norm <= 1e-12:
            return vec
        return vec / norm

    @classmethod
    def cosine_similarity(cls, a: np.ndarray, b: np.ndarray) -> float:
        av = cls.normalize(a)
        bv = cls.normalize(b)
        if av.size == 0 or bv.size == 0 or av.shape != bv.shape:
            return -1.0
        return float(np.dot(av, bv))

    def verify(
        self,
        live_embedding: np.ndarray,
        templates: Sequence[FaceTemplate],
        target_user_id: str,
        threshold: Optional[float] = None,
        include_inactive: bool = True,
    ) -> MatchResult:
        filtered = [t for t in templates if str(t.user_id) == str(target_user_id)]
        if not filtered:
            return MatchResult(False, str(target_user_id), "unknown", 0.0, reason="target_user_not_found")
        return self.match(live_embedding, filtered, threshold=threshold, include_inactive=include_inactive)

    def match(
        self,
        live_embedding: np.ndarray,
        templates: Sequence[FaceTemplate],
        threshold: Optional[float] = None,
        include_inactive: bool = False,
    ) -> MatchResult:
        if not templates:
            return MatchResult(False, None, "unknown", 0.0, reason="no_registered_templates")

        threshold_value = self.threshold if threshold is None else float(threshold)
        grouped: Dict[str, List[FaceTemplate]] = defaultdict(list)
        for template in templates:
            if include_inactive or template.is_active:
                grouped[str(template.user_id)].append(template)

        if not grouped:
            return MatchResult(False, None, "unknown", 0.0, reason="no_active_templates")

        live = self.normalize(live_embedding)
        best: Optional[MatchResult] = None

        for user_id, user_templates in grouped.items():
            user_best_template: Optional[FaceTemplate] = None
            user_best_similarity = -1.0
            for template in user_templates:
                similarity = self.cosine_similarity(live, template.embedding)
                if similarity > user_best_similarity:
                    user_best_similarity = similarity
                    user_best_template = template

            if user_best_template is None:
                continue

            candidate = MatchResult(
                matched=user_best_similarity >= threshold_value,
                user_id=user_id,
                identity=user_best_template.display_identity,
                similarity=float(user_best_similarity),
                matched_template=user_best_template.template_name,
                is_active=user_best_template.is_active,
                reason=None if user_best_similarity >= threshold_value else "below_threshold",
            )
            if best is None or candidate.similarity > best.similarity:
                best = candidate

        if best is None:
            return MatchResult(False, None, "unknown", 0.0, reason="no_valid_templates")
        if not best.matched:
            return MatchResult(
                False,
                None,
                "unknown",
                best.similarity,
                matched_template=best.matched_template,
                reason="below_threshold",
            )
        return best


def count_templates_by_user(templates: Iterable[FaceTemplate]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for template in templates:
        counts[str(template.user_id)] += 1
    return dict(counts)
