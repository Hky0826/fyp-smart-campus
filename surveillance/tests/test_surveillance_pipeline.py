"""End-to-end unit tests for SurveillancePipeline."""

import tempfile
import unittest
from pathlib import Path
import numpy as np

from surveillance.config import SurveillanceConfig
from surveillance.database import SurveillanceUserRepository
from surveillance.models.loader import MockHailoModelRunner
from surveillance.models.yolox import YOLOXPersonDetector
from surveillance.models.yunet import YuNetFaceDetector, YuNetDetectedFace
from surveillance.models.auraface import AuraFaceEmbedder
from surveillance.pipeline import SurveillancePipeline
from surveillance.utils.matching import FaceTemplate, TemplateMatcher
from surveillance.utils.alignment import FaceAligner


class MockYOLOXPersonDetector(YOLOXPersonDetector):
    def __init__(self, detections=None):
        self.detections = detections or []

    def detect(self, frame):
        return self.detections


class MockYuNetFaceDetector(YuNetFaceDetector):
    def __init__(self, faces=None):
        self.faces = faces or []

    def detect(self, image):
        return self.faces


class MockAuraFaceEmbedder(AuraFaceEmbedder):
    def __init__(self, embedding=None):
        self.embedding = embedding if embedding is not None else np.ones((512,), dtype=np.float32)

    def embed(self, aligned_face_bgr):
        return self.embedding


class TestSurveillancePipeline(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_surveillance.db"
        self.repo = SurveillanceUserRepository(self.db_path)

        # Enroll test template in repo
        test_vec = np.ones((512,), dtype=np.float32)
        test_vec /= np.linalg.norm(test_vec)
        self.repo.apply_delta(
            [
                {
                    "user_id": 99,
                    "is_active": 1,
                    "embeddings": [
                        {
                            "model_name": "auraface",
                            "template_name": "front",
                            "embedding": test_vec.tobytes(),
                        }
                    ],
                }
            ]
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pipeline_execution_and_identity_persistence(self):
        config = SurveillanceConfig(
            database_path=self.db_path,
            snapshot_enabled=False,
            person_detection_threshold=0.3,
            recognition_threshold=0.5,
        )

        person_det = MockYOLOXPersonDetector(
            detections=[np.array([100, 100, 300, 500, 0.9], dtype=np.float32)]
        )
        face_det = MockYuNetFaceDetector(
            faces=[
                YuNetDetectedFace(
                    bbox=(120, 110, 220, 210),
                    score=0.95,
                    landmarks=np.array([[140, 140], [180, 140], [160, 160], [145, 190], [175, 190]]),
                )
            ]
        )
        test_vec = np.ones((512,), dtype=np.float32)
        test_vec /= np.linalg.norm(test_vec)
        embedder = MockAuraFaceEmbedder(embedding=test_vec)

        pipeline = SurveillancePipeline(
            person_detector=person_det,
            face_detector=face_det,
            embedder=embedder,
            repository=self.repo,
            config=config,
        )

        dummy_frame = np.zeros((640, 640, 3), dtype=np.uint8)

        # Frame 1: Person detected + Face recognized -> User 99
        res1 = pipeline.process_frame(dummy_frame)
        self.assertTrue(res1["success"])
        self.assertEqual(len(res1["results"]), 1)
        item1 = res1["results"][0]
        self.assertEqual(item1["user_id"], "99")
        self.assertEqual(item1["status"], "recognized")

        # Frame 2: Person still tracked, but face detector returns NO faces (occluded face)
        face_det.faces = []
        res2 = pipeline.process_frame(dummy_frame)
        self.assertTrue(res2["success"])
        item2 = res2["results"][0]
        # Identity must persist from ByteTrack track record!
        self.assertEqual(item2["user_id"], "99")
        self.assertEqual(item2["status"], "recognized")
        self.assertEqual(item2["identity_source"], "track")


if __name__ == "__main__":
    unittest.main()
