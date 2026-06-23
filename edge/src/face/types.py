"""Shared face data structures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class DetectedFace:
    bbox: Sequence[float]
    confidence: float
    landmarks: Optional[np.ndarray] = None

    def xyxy_int(self) -> List[int]:
        x1, y1, x2, y2 = self.bbox
        return [int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))]

    def width(self) -> float:
        x1, _, x2, _ = self.bbox
        return max(0.0, float(x2) - float(x1))

    def height(self) -> float:
        _, y1, _, y2 = self.bbox
        return max(0.0, float(y2) - float(y1))
