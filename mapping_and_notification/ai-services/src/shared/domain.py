"""
shared/domain.py
----------------
Re-export module for backward compatibility.
Delegates to versioned models in `src.shared.models.v1.domain`.
"""

from src.shared.models.v1.domain import (
    BoundingBox,
    Grid,
    ImageMetadata,
    Point,
    ProcessingResult,
    Wall,
    WallGrid,
)

__all__ = [
    "ImageMetadata",
    "Point",
    "BoundingBox",
    "Grid",
    "WallGrid",
    "Wall",
    "ProcessingResult",
]
