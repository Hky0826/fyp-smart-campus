import unittest

import numpy as np

from edge.facial_recognition.src.config import AccessControlConfig
from edge.facial_recognition.src.face.alignment import AlignmentResult
from edge.facial_recognition.src.face.matching import FaceTemplate
from edge.facial_recognition.src.face.quality import FaceQualityResult
from edge.facial_recognition.src.face.spoofing import SpoofResult
from edge.facial_recognition.src.face.types import AuthenticationResult, DetectedFace
from edge.facial_recognition.src.pipelines.access_control import AccessControlPipeline, MULTIPLE_FACE_REASON


LANDMARKS = np.array([[30, 35], [60, 35], [45, 50], [34, 65], [56, 65]], dtype=np.float32)


class FakeDetector:
    def __init__(self, faces):
        self.faces = faces

    def detect(self, frame):
        return self.faces


class FakeEmbedder:
    def __init__(self, vectors):
        vectors = np.asarray(vectors, dtype=np.float32)
        self.vectors = [vectors] if vectors.ndim == 1 else list(vectors)
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

    def log_auth_event(self, user_id, status, confidence):
        self.events.append((user_id, status, confidence))


class FakeSpoof:
    def __init__(self, state="live"):
        self.state = state
        self.calls = 0
        self.resets = 0

    def check(self, frame, face):
        self.calls += 1
        return SpoofResult(self.state, 0.9, "test")

    def reset(self):
        self.resets += 1


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def monotonic(self):
        return self.now

    def advance(self, seconds=0.1):
        self.now += seconds


class AlwaysQuality:
    def check(self, frame, face):
        return FaceQualityResult(True, overall_score=0.9)


class PassAligner:
    def align(self, frame, face):
        return AlignmentResult(True, np.zeros((112, 112, 3), dtype=np.uint8), np.eye(2, 3, dtype=np.float32))


class FailAligner:
    def align(self, frame, face):
        return AlignmentResult(False, failure_reason="invalid_landmarks")


def face(x1=10, y1=10, x2=80, y2=80, landmarks=LANDMARKS):
    shifted = None if landmarks is None else np.asarray(landmarks, dtype=np.float32) + [x1 - 10, y1 - 10]
    return DetectedFace([x1, y1, x2, y2], 0.9, shifted)


class AccessControlLogicTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((120, 120, 3), dtype=np.uint8)
        self.clock = FakeClock()

    def pipeline(self, faces, vectors, templates, *, samples=1, stable_frames=1, spoof="live", aligner=None):
        config = AccessControlConfig(
            recognition_threshold=0.75,
            recognition_delay_seconds=0.0,
            min_embedding_samples=samples,
            max_embedding_samples=max(samples, 3),
            min_stable_frames=stable_frames,
            min_stable_duration_ms=0,
        )
        return AccessControlPipeline(
            FakeDetector(faces), FakeEmbedder(vectors), FakeRepository(templates), config,
            aligner=aligner or PassAligner(), spoof_detector=FakeSpoof(spoof),
            quality_checker=AlwaysQuality(), clock=self.clock.monotonic,
        )

    def test_access_control_uses_existing_hefs(self):
        self.assertEqual(AccessControlConfig().detector_model_path.name, "scrfd_10g.hef")
        self.assertEqual(AccessControlConfig().embedding_model_path.name, "arcface_r50.hef")

    def test_multiple_faces_has_explicit_denial(self):
        pipeline = self.pipeline([face(), face(25, 20, 95, 90)], [1, 0], [])
        result = pipeline.process_frame(self.frame)
        self.assertEqual(result["reason"], MULTIPLE_FACE_REASON)
        self.assertEqual(result["authentication_result"], AuthenticationResult.DENY_MULTIPLE_FACES.value)

    def test_unstable_track_retries_before_liveness(self):
        pipeline = self.pipeline([face()], [1, 0], [], stable_frames=2)
        result = pipeline.process_frame(self.frame)
        self.assertEqual(result["authentication_result"], AuthenticationResult.RETRY_UNSTABLE_TRACK.value)

    def test_invalid_landmarks_retry_alignment(self):
        pipeline = self.pipeline([face(landmarks=None)], [1, 0], [], aligner=FailAligner())
        result = pipeline.process_frame(self.frame)
        self.assertEqual(result["authentication_result"], AuthenticationResult.RETRY_ALIGNMENT.value)

    def test_spoof_is_not_reported_as_identity_failure(self):
        pipeline = self.pipeline([face()], [1, 0], [], spoof="spoof")
        result = pipeline.process_frame(self.frame)
        self.assertEqual(result["authentication_result"], AuthenticationResult.DENY_SPOOF.value)
        self.assertFalse(result["spoofing_passed"])

    def test_collects_multiple_frames_before_grant(self):
        template = FaceTemplate("user_001", np.array([1.0, 0.0]), "front")
        pipeline = self.pipeline([face()], [[1, 0], [0.99, 0.01], [0.98, 0.02]], [template], samples=3)
        results = []
        for _ in range(3):
            results.append(pipeline.process_frame(self.frame))
            self.clock.advance()
        self.assertEqual(results[0]["authentication_result"], AuthenticationResult.RETRY_INSUFFICIENT_SAMPLES.value)
        self.assertEqual(results[1]["authentication_result"], AuthenticationResult.RETRY_INSUFFICIENT_SAMPLES.value)
        self.assertEqual(results[2]["authentication_result"], AuthenticationResult.GRANT.value)
        self.assertEqual(results[2]["sample_count"], 3)

    def test_detector_miss_preserves_track_history(self):
        template = FaceTemplate("user_001", np.array([1.0, 0.0]))
        detector = FakeDetector([face()])
        pipeline = self.pipeline(detector.faces, [1, 0], [template], samples=2)
        pipeline.detector = detector
        first = pipeline.process_frame(self.frame)
        detector.faces = []
        missed = pipeline.process_frame(self.frame)
        detector.faces = [face()]
        resumed = pipeline.process_frame(self.frame)
        self.assertEqual(first["sample_count"], 1)
        self.assertEqual(missed["authentication_result"], AuthenticationResult.RETRY_NO_FACE.value)
        self.assertEqual(resumed["authentication_result"], AuthenticationResult.GRANT.value)

    def test_track_replacement_resets_samples_and_liveness(self):
        template = FaceTemplate("user_001", np.array([1.0, 0.0]))
        detector = FakeDetector([face()])
        pipeline = self.pipeline(detector.faces, [1, 0], [template], samples=2)
        pipeline.detector = detector
        first = pipeline.process_frame(self.frame)
        detector.faces = [face(85, 20, 115, 70)]
        replaced = pipeline.process_frame(self.frame)
        self.assertEqual(first["sample_count"], 1)
        self.assertEqual(replaced["sample_count"], 1)
        self.assertNotEqual(first.get("track_id"), replaced.get("track_id"))

    def test_access_control_filters_templates(self):
        templates = [
            FaceTemplate("user_001", np.array([1.0, 0.0]), "front"),
            FaceTemplate("user_001", np.array([0.0, 1.0]), "low_light"),
            FaceTemplate("user_002", np.array([0.5, 0.5]), "right_60"),
        ]
        detector = FakeDetector([face()])
        # Match against right_60 which should be filtered out. Since max_embedding_samples is 3,
        # we process 3 frames to reach terminal state.
        pipeline = self.pipeline(detector.faces, [0.5, 0.5], templates, samples=1)
        pipeline.process_frame(self.frame)
        pipeline.process_frame(self.frame)
        result = pipeline.process_frame(self.frame)
        self.assertEqual(result["authentication_result"], AuthenticationResult.DENY_NO_MATCH.value)

        # Match against low_light which is not filtered out, so it should grant (as user_001 has low_light)
        pipeline = self.pipeline(detector.faces, [0.0, 1.0], templates, samples=1)
        result = pipeline.process_frame(self.frame)
        self.assertEqual(result["authentication_result"], AuthenticationResult.GRANT.value)


if __name__ == "__main__":
    unittest.main()
