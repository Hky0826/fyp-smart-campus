"""Matching utilities class."""

from __future__ import annotations

from typing import List, Tuple, Optional

import numpy as np


class Matcher:
    def __init__(self, threshold_distance: float = 0.40):
        self.threshold = float(threshold_distance)

    @staticmethod
    def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
        a_norm = np.linalg.norm(a)
        b_norm = np.linalg.norm(b)
        if a_norm == 0 or b_norm == 0:
            return 1.0
        sim = float(np.dot(a, b) / (a_norm * b_norm))
        return 1.0 - sim

    def find_best(self, live_emb: np.ndarray, db_embeddings: List[Tuple[int, np.ndarray]]) -> Tuple[Optional[int], float]:
        best_id = None
        best_distance = 1.0
        for user_id, vec in db_embeddings:
            d = self.cosine_distance(live_emb, vec)
            if d < best_distance:
                best_distance = d
                best_id = user_id
        score = 1.0 - best_distance
        if best_distance < self.threshold:
            return best_id, float(score)
        return None, float(score)
