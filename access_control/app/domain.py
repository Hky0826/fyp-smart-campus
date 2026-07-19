"""Pipeline data shared by replaceable backends."""
from __future__ import annotations
from dataclasses import dataclass, field
from time import monotonic
from typing import Any
import numpy as np

@dataclass(frozen=True, slots=True)
class BoundingBox:
    x: float; y: float; width: float; height: float
    @property
    def x2(self): return self.x + self.width
    @property
    def y2(self): return self.y + self.height
    @property
    def area(self): return max(0.0, self.width) * max(0.0, self.height)
    @property
    def aspect_ratio(self): return self.width / self.height if self.height > 0 else 0.0
    @property
    def center(self): return self.x + self.width / 2, self.y + self.height / 2
    def clipped(self, frame_width: int, frame_height: int) -> "BoundingBox":
        x1, y1 = max(0.0, min(self.x, frame_width)), max(0.0, min(self.y, frame_height))
        x2, y2 = max(0.0, min(self.x2, frame_width)), max(0.0, min(self.y2, frame_height))
        return BoundingBox(x1, y1, max(0.0, x2-x1), max(0.0, y2-y1))
    def as_xywh(self): return tuple(int(round(v)) for v in (self.x, self.y, self.width, self.height))
    def as_xyxy(self): return tuple(int(round(v)) for v in (self.x, self.y, self.x2, self.y2))

@dataclass(frozen=True, slots=True)
class FramePacket:
    frame_id: int; captured_at: float; image: np.ndarray
    metadata: dict[str, Any] = field(default_factory=dict)
    @classmethod
    def create(cls, frame_id, image): return cls(frame_id, monotonic(), image)

@dataclass(frozen=True, slots=True)
class FaceDetection:
    box: BoundingBox; landmarks: np.ndarray; confidence: float; frame_id: int; detected_at: float
    inference_ms: float = 0.0

@dataclass(frozen=True, slots=True)
class Embedding:
    vector: np.ndarray; model_name: str; model_version: str; dimension: int; frame_id: int; created_at: float
    def compatible_with(self, other: "Embedding") -> bool:
        return (self.model_name, self.model_version, self.dimension) == (other.model_name, other.model_version, other.dimension)

@dataclass(frozen=True, slots=True)
class IdentityMatch:
    identity_id: str; display_name: str; similarity: float; embedding: Embedding