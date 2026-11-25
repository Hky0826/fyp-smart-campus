"""Models package for surveillance module."""

from .loader import HailoModelRunner, HailoModelManager, MockHailoModelRunner
from .yolox import YOLOXPersonDetector, YOLOv8PersonDetector
from .yunet import YuNetFaceDetector
from .scrfd import SCRFDFaceDetector
from .auraface import AuraFaceEmbedder

__all__ = [
    "HailoModelRunner",
    "HailoModelManager",
    "MockHailoModelRunner",
    "YOLOXPersonDetector",
    "YOLOv8PersonDetector",
    "YuNetFaceDetector",
    "SCRFDFaceDetector",
    "AuraFaceEmbedder",
]
