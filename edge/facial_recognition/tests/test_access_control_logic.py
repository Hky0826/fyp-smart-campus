import unittest

import numpy as np

from edge.facial_recognition.src.config import AccessControlConfig
from edge.facial_recognition.src.face.matching import FaceTemplate
from edge.facial_recognition.src.face.quality import QualityResult
from edge.facial_recognition.src.face.spoofing import SpoofResult
from edge.facial_recognition.src.face.types import DetectedFace
from edge.facial_recognition.src.pipelines.access_control import AccessControlPipeline, MULTIPLE_FACE_REASON


class FakeDetector:
    def __init__(self, faces):
        self.faces = faces

    def detect(self, frame):
        return self.faces


class FakeEmbedder:
    def __init__(self, vector):
        self.vector = np.asarray(vector, dtype=np.float32)

    def embed(self, face_image):
        return self.vector


class FakeRepository:
    def __init__(self, templates):
        self.templates = templates
        self.events = []

    def load_templates(self):
        return self.templates

    def log_auth_event(self, user_id, status, confidence):
        self.events.append((user_id, status, confidence))


class FakeSpoof:
    def __init__(self, state="live"):
        self.state = state
        self.calls = 0

    def check(self, frame, face):
        self.calls += 1
        return SpoofResult(self.state, 0.9, "test")


class AlwaysQuality:
    def check(self, frame, face):
        return QualityResult(True)


def face(x1=10, y1=10, x2=80, y2=80):
    return DetectedFace([x1, y1, x2, y2], 0.9)


class AccessControlLogicTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((120, 120, 3), dtype=np.uint8)

    def test_access_control_uses_stronger_detector(self):
        self.assertEqual(AccessControlConfig().detector_model_path.name, "scrfd_10g.hef")

    def test_access_control_uses_arcface_r50_embedder(self):
        self.assertEqual(AccessControlConfig().embedding_model_path.name, "arcface_r50.hef")

    def pipeline(self, faces, live_vector, templates, spoof_state="live", threshold=0.75):
        return AccessControlPipeline(
            detector=FakeDetector(faces),
            embedder=FakeEmbedder(live_vector),
            repository=FakeRepository(templates),
            config=AccessControlConfig(recognition_threshold=threshold),
            spoof_detector=FakeSpoof(spoof_state),
            quality_checker=AlwaysQuality(),
        )

    def test_access_control_rejects_multiple_faces(self):
        pipeline = self.pipeline(
            [face(), face(20, 20, 90, 90)],
            [1.0, 0.0],
            [FaceTemplate("user_001", np.array([1.0, 0.0]), "front")],
        )

        result = pipeline.process_frame(self.frame)

        self.assertFalse(result["access_granted"])
        self.assertEqual(result["reason"], MULTIPLE_FACE_REASON)
        self.assertEqual(result["face_count"], 2)

    def test_access_control_rejects_spoofing_failure(self):
        pipeline = self.pipeline(
            [face()],
            [1.0, 0.0],
            [FaceTemplate("user_001", np.array([1.0, 0.0]), "front")],
            spoof_state="spoof",
        )

        result = pipeline.process_frame(self.frame)

        self.assertFalse(result["access_granted"])
        self.assertFalse(result["spoofing_passed"])
        self.assertEqual(result["reason"], "Spoofing/liveness check failed.")

    def test_access_control_rejects_unknown_face(self):
        pipeline = self.pipeline(
            [face()],
            [0.0, 1.0],
            [FaceTemplate("user_001", np.array([1.0, 0.0]), "front")],
            threshold=0.8,
        )

        result = pipeline.process_frame(self.frame)

        self.assertFalse(result["access_granted"])
        self.assertEqual(result["identity"], "unknown")
        self.assertEqual(result["reason"], "Unknown face or low-confidence match")

    def test_access_control_supports_multi_template_matching(self):
        templates = [
            FaceTemplate("user_001", np.array([1.0, 0.0]), "front"),
            FaceTemplate("user_001", np.array([0.0, 1.0]), "left_30"),
        ]
        pipeline = self.pipeline([face()], [0.0, 1.0], templates, threshold=0.8)

        result = pipeline.process_frame(self.frame)

        self.assertTrue(result["access_granted"])
        self.assertEqual(result["identity"], "user_001")
        self.assertEqual(result["matched_template"], "left_30")


if __name__ == "__main__":
    unittest.main()
