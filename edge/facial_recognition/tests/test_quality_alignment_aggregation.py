import unittest

import numpy as np

from edge.facial_recognition.src.face.aggregation import EmbeddingAggregationConfig, TrackEmbeddingAggregator
from edge.facial_recognition.src.face.alignment import FaceAligner
from edge.facial_recognition.src.face.quality import FaceQualityChecker, FaceQualityConfig
from edge.facial_recognition.src.face.types import DetectedFace


LANDMARKS = np.array([[70, 75], [130, 75], [100, 105], [78, 135], [122, 135]], dtype=np.float32)


class QualityAlignmentAggregationTests(unittest.TestCase):
    def setUp(self):
        checker = np.indices((200, 200)).sum(axis=0) % 2
        self.good_frame = np.repeat((checker * 100 + 80).astype(np.uint8)[:, :, None], 3, axis=2)
        self.face = DetectedFace([40, 35, 160, 170], 0.95, LANDMARKS)
        self.quality = FaceQualityChecker(config=FaceQualityConfig(min_sharpness=0.05, min_contrast=20))

    def test_dark_face(self):
        result = self.quality.check(np.zeros_like(self.good_frame), self.face)
        self.assertIn("face_too_dark", result.failure_reasons)

    def test_overexposed_face(self):
        result = self.quality.check(np.full_like(self.good_frame, 255), self.face)
        self.assertIn("face_overexposed", result.failure_reasons)

    def test_blurred_face(self):
        result = self.quality.check(np.full_like(self.good_frame, 128), self.face)
        self.assertIn("face_too_blurry", result.failure_reasons)

    def test_too_small_face(self):
        tiny = DetectedFace([80, 80, 100, 100], 0.9, LANDMARKS * 0.2)
        result = self.quality.check(self.good_frame, tiny)
        self.assertIn("face_too_small", result.failure_reasons)

    def test_severely_rotated_face(self):
        rotated = LANDMARKS.copy()
        rotated[0, 1], rotated[1, 1] = 45, 125
        result = self.quality.check(self.good_frame, DetectedFace(self.face.bbox, 0.9, rotated))
        self.assertIn("face_roll_too_large", result.failure_reasons)

    def test_boundary_truncated_face(self):
        result = self.quality.check(self.good_frame, DetectedFace([0, 30, 130, 170], 0.9, LANDMARKS))
        self.assertIn("face_boundary_truncated", result.failure_reasons)

    def test_alignment_rejects_missing_and_reversed_eyes(self):
        aligner = FaceAligner()
        missing = aligner.align(self.good_frame, DetectedFace(self.face.bbox, 0.9, None))
        reversed_points = LANDMARKS.copy()
        reversed_points[[0, 1]] = reversed_points[[1, 0]]
        reversed_result = aligner.align(self.good_frame, DetectedFace(self.face.bbox, 0.9, reversed_points))
        self.assertFalse(missing.success)
        self.assertEqual(reversed_result.failure_reason, "eyes_not_ordered")

    def test_aggregation_rejects_outlier_and_normalizes(self):
        aggregator = TrackEmbeddingAggregator(EmbeddingAggregationConfig(
            min_embedding_samples=3, max_embedding_samples=5, embedding_outlier_threshold=0.2,
        ))
        aggregator.add_sample([1, 0], 0.8, 1.0, "one")
        aggregator.add_sample([0.99, 0.01], 0.9, 2.0, "one")
        aggregator.add_sample([0.98, -0.02], 0.7, 3.0, "one")
        aggregator.add_sample([-1, 0], 1.0, 4.0, "two")
        result = aggregator.get_aggregated_embedding()
        self.assertAlmostEqual(float(np.linalg.norm(result)), 1.0, places=6)
        self.assertGreater(result[0], 0.99)
        self.assertEqual(aggregator.consistent_candidate(), "one")


if __name__ == "__main__":
    unittest.main()
