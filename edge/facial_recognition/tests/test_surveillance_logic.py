import unittest

import numpy as np

from edge.facial_recognition.src.config import SurveillanceConfig
from edge.facial_recognition.src.face.matching import FaceTemplate
from edge.facial_recognition.src.face.types import DetectedFace
from edge.facial_recognition.src.pipelines.surveillance import SurveillancePipeline


class FakeDetector:
    def __init__(self, faces):
        self.faces = faces

    def detect(self, frame):
        return self.faces


class SequenceEmbedder:
    def __init__(self, vectors):
        self.vectors = [np.asarray(v, dtype=np.float32) for v in vectors]
        self.index = 0

    def embed(self, face_image):
        vector = self.vectors[min(self.index, len(self.vectors) - 1)]
        self.index += 1
        return vector


class FakeRepository:
    def __init__(self, templates):
        self.templates = templates
        self.events = []

    def load_templates(self):
        return self.templates

    def log_surveillance_event(
        self,
        user_id,
        recognition_status,
        confidence_score,
        matched_template=None,
        face_count=1,
        bbox=None,
        image_path=None,
        timestamp=None,
    ):
        self.events.append(
            {
                "user_id": user_id,
                "recognition_status": recognition_status,
                "confidence_score": confidence_score,
                "matched_template": matched_template,
                "face_count": face_count,
                "bbox": bbox,
                "image_path": image_path,
                "timestamp": timestamp,
            }
        )


def face(x1=10, y1=10, x2=80, y2=80):
    return DetectedFace([x1, y1, x2, y2], 0.9)


class SurveillanceLogicTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((120, 120, 3), dtype=np.uint8)

    def pipeline(self, faces, live_vectors, templates, threshold=0.62, track_max_missing_frames=8):
        return SurveillancePipeline(
            detector=FakeDetector(faces),
            embedder=SequenceEmbedder(live_vectors),
            repository=FakeRepository(templates),
            config=SurveillanceConfig(
                recognition_threshold=threshold,
                snapshot_enabled=False,
                track_max_missing_frames=track_max_missing_frames,
            ),
        )

    def test_surveillance_accepts_multiple_faces(self):
        pipeline = self.pipeline(
            [face(), face(20, 20, 90, 90)],
            [[1.0, 0.0], [0.0, 1.0]],
            [FaceTemplate("user_001", np.array([1.0, 0.0]), "front")],
            threshold=0.8,
        )

        result = pipeline.process_frame(self.frame)

        self.assertTrue(result["success"])
        self.assertEqual(result["face_count"], 2)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["status"], "recognized")
        self.assertEqual(result["results"][1]["status"], "unknown")

    def test_surveillance_does_not_call_spoofing_detection(self):
        pipeline = self.pipeline(
            [face()],
            [[1.0, 0.0]],
            [FaceTemplate("user_001", np.array([1.0, 0.0]), "front")],
        )

        self.assertFalse(hasattr(pipeline, "spoof_detector"))
        result = pipeline.process_frame(self.frame)
        self.assertEqual(result["results"][0]["status"], "recognized")

    def test_surveillance_matches_against_multiple_templates_per_user(self):
        templates = [
            FaceTemplate("user_001", np.array([1.0, 0.0]), "front"),
            FaceTemplate("user_001", np.array([0.0, 1.0]), "right_60"),
        ]
        pipeline = self.pipeline([face()], [[0.0, 1.0]], templates, threshold=0.8)

        result = pipeline.process_frame(self.frame)

        self.assertEqual(result["results"][0]["identity"], "user_001")
        self.assertEqual(result["results"][0]["matched_template"], "right_60")

    def test_surveillance_returns_unknown_below_threshold(self):
        pipeline = self.pipeline(
            [face()],
            [[0.8, 0.6]],
            [FaceTemplate("user_001", np.array([1.0, 0.0]), "front")],
            threshold=0.95,
        )

        result = pipeline.process_frame(self.frame)

        self.assertEqual(result["results"][0]["identity"], "unknown")
        self.assertEqual(result["results"][0]["status"], "unknown")

    def test_surveillance_keeps_identity_on_same_track_without_rematching(self):
        pipeline = self.pipeline(
            [face()],
            [[1.0, 0.0], [0.0, 1.0]],
            [FaceTemplate("user_001", np.array([1.0, 0.0]), "front")],
            threshold=0.8,
        )

        first = pipeline.process_frame(self.frame)
        second = pipeline.process_frame(self.frame)

        self.assertEqual(first["results"][0]["identity"], "user_001")
        self.assertEqual(second["results"][0]["identity"], "user_001")
        self.assertEqual(second["results"][0]["identity_source"], "track")
        self.assertEqual(pipeline.embedder.index, 1)

    def test_surveillance_rematches_after_track_leaves_frame(self):
        pipeline = self.pipeline(
            [face()],
            [[1.0, 0.0], [0.0, 1.0]],
            [
                FaceTemplate("user_001", np.array([1.0, 0.0]), "front"),
                FaceTemplate("user_002", np.array([0.0, 1.0]), "front"),
            ],
            threshold=0.8,
            track_max_missing_frames=1,
        )

        first = pipeline.process_frame(self.frame)
        pipeline.detector.faces = []
        pipeline.process_frame(self.frame)
        pipeline.process_frame(self.frame)
        pipeline.detector.faces = [face()]
        reentered = pipeline.process_frame(self.frame)

        self.assertEqual(first["results"][0]["identity"], "user_001")
        self.assertEqual(reentered["results"][0]["identity"], "user_002")
        self.assertEqual(reentered["results"][0]["identity_source"], "recognition")
        self.assertEqual(pipeline.embedder.index, 2)

    def test_surveillance_logs_once_per_recognized_track(self):
        pipeline = self.pipeline(
            [face()],
            [[1.0, 0.0], [0.0, 1.0]],
            [FaceTemplate("7", np.array([1.0, 0.0]), "front")],
            threshold=0.8,
        )

        pipeline.process_frame(self.frame)
        pipeline.process_frame(self.frame)

        self.assertEqual(len(pipeline.repository.events), 1)
        self.assertEqual(pipeline.repository.events[0]["user_id"], "7")
        self.assertEqual(pipeline.repository.events[0]["recognition_status"], "RECOGNIZED")

    def test_surveillance_logs_unknown_then_recognized_for_same_track(self):
        pipeline = self.pipeline(
            [face()],
            [[0.0, 1.0], [1.0, 0.0]],
            [FaceTemplate("7", np.array([1.0, 0.0]), "front")],
            threshold=0.8,
        )

        pipeline.process_frame(self.frame)
        pipeline.process_frame(self.frame)

        self.assertEqual([event["recognition_status"] for event in pipeline.repository.events], ["UNKNOWN", "RECOGNIZED"])
        self.assertIsNone(pipeline.repository.events[0]["user_id"])
        self.assertEqual(pipeline.repository.events[1]["user_id"], "7")


if __name__ == "__main__":
    unittest.main()
