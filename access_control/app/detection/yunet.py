"""OpenCV YuNet backend adapted from the legacy implementation."""
from pathlib import Path
import logging
from time import perf_counter

import cv2
import numpy as np

from ..domain import BoundingBox, FaceDetection, FramePacket
logger = logging.getLogger(__name__)


class YuNetDetector:
    def __init__(self, model_path: Path, input_size=(640, 480), confidence=0.7, nms=0.3, min_face_size=48):
        if not Path(model_path).is_file():
            raise FileNotFoundError(f'YuNet model not found: {model_path}')
        self._input_size = tuple(map(int, input_size))
        self._min_face_size = int(min_face_size)
        self.last_inference_ms = 0.0
        self._detector = cv2.FaceDetectorYN.create(str(model_path), '', self._input_size, float(confidence), float(nms), 5000)

    def set_input_size(self, width, height):
        size = int(width), int(height)
        if size != self._input_size:
            self._detector.setInputSize(size)
            self._input_size = size

    def detect(self, frame: FramePacket):
        height, width = frame.image.shape[:2]
        self.set_input_size(width, height)
        started = perf_counter()
        _, rows = self._detector.detect(frame.image)
        self.last_inference_ms = (perf_counter() - started) * 1000
        return self.convert_rows(rows, frame.frame_id, frame.captured_at, width, height, self.last_inference_ms, self._min_face_size)

    @staticmethod
    def convert_rows(rows, frame_id, detected_at, frame_width, frame_height, inference_ms=0.0, min_face_size=1):
        output = []
        if rows is None:
            return output
        for row in np.asarray(rows):
            if row.size < 15 or not np.all(np.isfinite(row[:15])):
                continue
            box = BoundingBox(*map(float, row[:4])).clipped(frame_width, frame_height)
            if box.width < min_face_size or box.height < min_face_size:
                continue
            landmarks = np.asarray(row[4:14], dtype=np.float32).reshape(5, 2)
            landmarks[:, 0] = np.clip(landmarks[:, 0], 0, max(0, frame_width - 1))
            landmarks[:, 1] = np.clip(landmarks[:, 1], 0, max(0, frame_height - 1))
            output.append(FaceDetection(box, landmarks, float(row[14]), frame_id, detected_at, inference_ms))
        return output
