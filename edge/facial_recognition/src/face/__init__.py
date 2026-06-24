"""Face processing primitives for Hailo inference pipelines."""

from .matching import FaceTemplate, MatchResult, TemplateMatcher
from .types import DetectedFace

__all__ = ["DetectedFace", "FaceTemplate", "MatchResult", "TemplateMatcher"]
