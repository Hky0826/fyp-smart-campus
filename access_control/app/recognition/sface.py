"""OpenCV SFace backend with explicit embedding compatibility checks."""
from pathlib import Path
import logging
from time import monotonic, perf_counter

import cv2
import numpy as np

from ..domain import Embedding
logger = logging.getLogger(__name__)


class IncompatibleEmbeddingError(ValueError):
    pass


class SFaceRecognizer:
    def __init__(self, model_path, model_name='opencv_sface', model_version='2021dec'):
        if not Path(model_path).is_file():
            raise FileNotFoundError(f'SFace model not found: {model_path}')
        self.model_name = model_name
        self.model_version = model_version
        self.last_inference_ms = 0.0
        self._recognizer = cv2.FaceRecognizerSF.create(str(model_path), '')

    def embed(self, frame, detection):
        started = perf_counter()
        x, y, width, height = detection.box.as_xywh()
        row = np.concatenate((np.asarray([x, y, width, height], np.float32), detection.landmarks.reshape(-1), np.asarray([detection.confidence], np.float32)))
        aligned = self._recognizer.alignCrop(frame.image, row)
        vector = np.asarray(self._recognizer.feature(aligned), np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 1e-12:
            raise ValueError('SFace produced an invalid embedding')
        vector = vector / norm
        self.last_inference_ms = (perf_counter() - started) * 1000
        return Embedding(vector, self.model_name, self.model_version, int(vector.size), frame.frame_id, monotonic())

    @staticmethod
    def similarity(probe, reference):
        if not probe.compatible_with(reference):
            raise IncompatibleEmbeddingError(f'cannot compare {probe.model_name}/{probe.model_version}/{probe.dimension} with {reference.model_name}/{reference.model_version}/{reference.dimension}')
        first = np.asarray(probe.vector, np.float32).reshape(-1)
        second = np.asarray(reference.vector, np.float32).reshape(-1)
        return float(np.dot(first, second) / max(float(np.linalg.norm(first) * np.linalg.norm(second)), 1e-12))
