"""Face processing primitives for access control pipelines."""

from .detection import YuNetDetector
from .embedding import SFaceEmbedder
from .matching import FaceTemplate, MatchResult, TemplateMatcher
from .types import DetectedFace

__all__ = [
    "DetectedFace",
    "FaceTemplate",
    "MatchResult",
    "SFaceEmbedder",
    "TemplateMatcher",
    "YuNetDetector",
]
