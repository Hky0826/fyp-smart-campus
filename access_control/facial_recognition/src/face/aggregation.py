"""Quality-ranked multi-frame embedding aggregation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EmbeddingAggregationConfig:
    min_embedding_samples: int = 2
    max_embedding_samples: int = 10
    embedding_outlier_threshold: float = 0.25
    candidate_consistency_ratio: float = 0.8


@dataclass(frozen=True)
class EmbeddingSample:
    embedding: np.ndarray
    quality_score: float
    frame_timestamp: float
    candidate_id: str | None = None


class TrackEmbeddingAggregator:
    def __init__(self, config: EmbeddingAggregationConfig | None = None) -> None:
        self.config = config or EmbeddingAggregationConfig()
        if not 1 <= self.config.min_embedding_samples <= self.config.max_embedding_samples:
            raise ValueError("embedding sample limits are inconsistent")
        self._samples: list[EmbeddingSample] = []

    @staticmethod
    def _normalize(embedding: np.ndarray) -> np.ndarray:
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size == 0 or not np.all(np.isfinite(vector)):
            raise ValueError("embedding must be finite and non-empty")
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            raise ValueError("embedding norm must be positive")
        return vector / norm

    def add_sample(
        self,
        embedding: np.ndarray,
        quality_score: float,
        frame_timestamp: float,
        candidate_id: str | None = None,
    ) -> None:
        normalized = self._normalize(embedding)
        if self._samples and normalized.shape != self._samples[0].embedding.shape:
            raise ValueError("embedding dimensions changed within a track")
        self._samples.append(
            EmbeddingSample(normalized, float(np.clip(quality_score, 0.0, 1.0)), float(frame_timestamp), candidate_id)
        )
        self._samples.sort(key=lambda item: (item.quality_score, item.frame_timestamp), reverse=True)
        del self._samples[self.config.max_embedding_samples:]

    def has_enough_samples(self) -> bool:
        return len(self._inlier_samples()) >= self.config.min_embedding_samples

    def get_aggregated_embedding(self) -> np.ndarray:
        inliers = self._inlier_samples()
        if len(inliers) < self.config.min_embedding_samples:
            raise ValueError("insufficient inlier embedding samples")
        return self._normalize(np.mean([sample.embedding for sample in inliers], axis=0))

    def consistent_candidate(self) -> str | None:
        inliers = self._inlier_samples()
        if not inliers:
            return None
        counts = Counter(sample.candidate_id for sample in inliers if sample.candidate_id is not None)
        if not counts:
            return None
        candidate, count = counts.most_common(1)[0]
        return candidate if count / len(inliers) >= self.config.candidate_consistency_ratio else None

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def reset(self) -> None:
        self._samples.clear()

    def _inlier_samples(self) -> list[EmbeddingSample]:
        if len(self._samples) <= 2:
            return list(self._samples)
        matrix = np.stack([sample.embedding for sample in self._samples])
        centroid = self._normalize(np.mean(matrix, axis=0))
        distances = 1.0 - matrix @ centroid
        return [
            sample for sample, distance in zip(self._samples, distances)
            if float(distance) <= self.config.embedding_outlier_threshold
        ]
