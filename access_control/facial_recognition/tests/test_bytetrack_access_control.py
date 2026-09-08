"""Unit tests for ByteTrack and Track-then-Recognize persistence in access control and kiosk."""

import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from access_control.facial_recognition.src.api.kiosk import (
    KioskStateStore,
    KioskTimingConfig,
    _detect_owner_presence,
)
from access_control.facial_recognition.src.config import AccessControlConfig, RuntimeConfig
from access_control.facial_recognition.src.face.alignment import AlignmentResult
from access_control.facial_recognition.src.face.association import IdentityManager
from access_control.facial_recognition.src.face.bytetrack import ByteTracker, STrack
from access_control.facial_recognition.src.face.matching import FaceTemplate, TemplateMatcher
from access_control.facial_recognition.src.face.quality import FaceQualityResult
from access_control.facial_recognition.src.face.spoofing import SpoofResult
from access_control.facial_recognition.src.face.tracking import FaceTrack, FaceTracker, FaceTrackerConfig
from access_control.facial_recognition.src.face.types import AuthenticationResult, DetectedFace
from access_control.facial_recognition.src.pipelines.access_audio import EdgeAuthToken
from access_control.facial_recognition.src.pipelines.access_control import AccessControlPipeline


LANDMARKS = np.array([[30, 35], [60, 35], [45, 50], [34, 65], [56, 65]], dtype=np.float32)


class CountingEmbedder:
    """Mock embedder that tracks how many times embed() is called."""

    def __init__(self, vectors: np.ndarray | list[np.ndarray]) -> None:
        if isinstance(vectors, list):
            self.vectors = [np.asarray(v, dtype=np.float32) for v in vectors]
        else:
            self.vectors = [np.asarray(vectors, dtype=np.float32)]
        self.call_count = 0

    def embed(self, face_image: np.ndarray) -> np.ndarray:
        idx = min(self.call_count, len(self.vectors) - 1)
        self.call_count += 1
        return self.vectors[idx].copy()


class FakeClock:
    def __init__(self, now=100.0):
        self.now = now

    def monotonic(self):
        return self.now

    def advance(self, seconds=0.3):
        self.now += seconds


class MockDetector:
    def __init__(self, faces: list[DetectedFace]) -> None:
        self.faces = faces

    def detect(self, frame: np.ndarray) -> list[DetectedFace]:
        return self.faces


class MockRepository:
    def __init__(self, templates: list[FaceTemplate]) -> None:
        self.templates = templates
        self.events: list[tuple] = []

    def load_templates(self) -> list[FaceTemplate]:
        return self.templates

    def log_auth_event(self, user_id, status, confidence, **kwargs) -> None:
        self.events.append((user_id, status, confidence))


class MockSpoof:
    def check(self, frame, face):
        return SpoofResult("live", 0.95, "test")

    def reset(self):
        pass


class MockQuality:
    def check(self, frame, face):
        return FaceQualityResult(True, overall_score=0.95)


class MockAligner:
    def align(self, frame, face):
        return AlignmentResult(True, np.zeros((112, 112, 3), dtype=np.uint8), np.eye(2, 3, dtype=np.float32))


def make_face(x1=20, y1=20, x2=80, y2=80, conf=0.9, landmarks=LANDMARKS) -> DetectedFace:
    lms = None if landmarks is None else np.asarray(landmarks, dtype=np.float32) + [x1 - 20, y1 - 20]
    return DetectedFace([x1, y1, x2, y2], conf, lms)


class ByteTrackFaceTrackerTests(unittest.TestCase):
    """Verify ByteTracker and FaceTracker functionality on face bounding boxes."""

    def test_bytetrack_tracks_smooth_face_motion(self):
        tracker = FaceTracker(FaceTrackerConfig(min_stable_frames=1, min_stable_duration_ms=0))
        t0 = 100.0

        # Frame 1
        tracks1 = tracker.update([make_face(20, 20, 80, 80)], timestamp=t0)
        self.assertEqual(len(tracks1), 1)
        track_id = tracks1[0].track_id

        # Frame 2: Slightly moved face
        tracks2 = tracker.update([make_face(22, 21, 82, 81)], timestamp=t0 + 0.033)
        self.assertEqual(len(tracks2), 1)
        self.assertEqual(tracks2[0].track_id, track_id)

        # Frame 3: Further moved face
        tracks3 = tracker.update([make_face(25, 23, 85, 83)], timestamp=t0 + 0.066)
        self.assertEqual(len(tracks3), 1)
        self.assertEqual(tracks3[0].track_id, track_id)
        self.assertTrue(tracks3[0].stable)

    def test_bytetrack_recovers_low_confidence_face(self):
        tracker = FaceTracker(FaceTrackerConfig(track_high_thresh=0.6, track_low_thresh=0.2, new_track_thresh=0.6))
        t0 = 100.0

        # High confidence detection on frame 1
        tr1 = tracker.update([make_face(20, 20, 80, 80, conf=0.9)], timestamp=t0)
        self.assertEqual(len(tr1), 1)
        track_id = tr1[0].track_id

        # Low confidence detection (e.g. face turned slightly, conf drops to 0.35)
        # ByteTrack's 2nd association stage should match this to the existing track
        tr2 = tracker.update([make_face(21, 20, 81, 80, conf=0.35)], timestamp=t0 + 0.033)
        self.assertEqual(len(tr2), 1)
        self.assertEqual(tr2[0].track_id, track_id)

    def test_bytetrack_preserves_track_across_missed_frame(self):
        tracker = FaceTracker(FaceTrackerConfig(track_buffer=30))
        t0 = 100.0

        # Frame 1: Face detected
        tr1 = tracker.update([make_face(20, 20, 80, 80)], timestamp=t0)
        track_id = tr1[0].track_id

        # Frame 2: Detector missed the face
        tr2 = tracker.update([], timestamp=t0 + 0.033)
        visible2 = [t for t in tr2 if t.visible]
        self.assertEqual(len(visible2), 0)

        # Frame 3: Face reappears close to predicted Kalman position
        tr3 = tracker.update([make_face(21, 20, 81, 80)], timestamp=t0 + 0.066)
        visible3 = [t for t in tr3 if t.visible]
        self.assertEqual(len(visible3), 1)
        self.assertEqual(visible3[0].track_id, track_id)


class AccessControlIdentityPersistenceTests(unittest.TestCase):
    """Verify that recognition runs once per track, and zero times on subsequent frames."""

    def test_zero_re_recognition_on_subsequent_active_track_frames(self):
        template_vec = np.array([1.0, 0.0], dtype=np.float32)
        template = FaceTemplate("user_001", template_vec, "front")
        embedder = CountingEmbedder(template_vec)
        detector = MockDetector([make_face(20, 20, 80, 80)])
        config = AccessControlConfig(
            recognition_threshold=0.75,
            min_embedding_samples=1,
            max_embedding_samples=3,
            min_stable_frames=1,
            min_stable_duration_ms=0,
        )

        pipeline = AccessControlPipeline(
            detector=detector,
            embedder=embedder,
            repository=MockRepository([template]),
            config=config,
            aligner=MockAligner(),
            spoof_detector=MockSpoof(),
            quality_checker=MockQuality(),
        )

        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # Frame 1: First arrival, initial recognition runs
        res1 = pipeline.process_frame(frame)
        self.assertEqual(res1["authentication_result"], AuthenticationResult.GRANT.value)
        self.assertEqual(res1["user_id"], "user_001")
        self.assertEqual(embedder.call_count, 1)

        # Frames 2 through 10: Person remains in front of the camera (same active track)
        for i in range(2, 11):
            res_i = pipeline.process_frame(frame)
            self.assertEqual(res_i["authentication_result"], AuthenticationResult.GRANT.value)
            self.assertEqual(res_i["user_id"], "user_001")
            self.assertEqual(res_i["track_id"], res1["track_id"])

        # Crucial assertion: Heavy embedder was called ONLY ONCE across 10 frames!
        self.assertEqual(embedder.call_count, 1)

    def test_new_track_triggers_recognition_again(self):
        template_vec = np.array([1.0, 0.0], dtype=np.float32)
        template = FaceTemplate("user_001", template_vec, "front")
        embedder = CountingEmbedder(template_vec)
        detector = MockDetector([make_face(20, 20, 80, 80)])
        config = AccessControlConfig(
            recognition_threshold=0.75,
            min_embedding_samples=1,
            max_embedding_samples=3,
            min_stable_frames=1,
            min_stable_duration_ms=0,
        )

        pipeline = AccessControlPipeline(
            detector=detector,
            embedder=embedder,
            repository=MockRepository([template]),
            config=config,
            aligner=MockAligner(),
            spoof_detector=MockSpoof(),
            quality_checker=MockQuality(),
        )

        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # Frame 1: First person
        res1 = pipeline.process_frame(frame)
        self.assertEqual(embedder.call_count, 1)

        # A completely different face appears at a different location
        detector.faces = [make_face(200, 200, 280, 280)]
        res2 = pipeline.process_frame(frame)
        self.assertNotEqual(res1["track_id"], res2["track_id"])
        # New track requires recognition
        self.assertEqual(embedder.call_count, 2)

    def test_failed_or_low_threshold_keeps_checking_until_granted(self):
        template_vec = np.array([1.0, 0.0], dtype=np.float32)
        template = FaceTemplate("user_001", template_vec, "front")
        # Frame 1: Low similarity (0.40) -> DENY_NO_MATCH
        # Frame 2: Low similarity (0.45) -> DENY_NO_MATCH
        # Frame 3: High similarity (1.00) -> GRANT!
        vectors = [
            np.array([0.4, 0.6], dtype=np.float32),
            np.array([0.45, 0.55], dtype=np.float32),
            np.array([1.0, 0.0], dtype=np.float32),
        ]
        embedder = CountingEmbedder(vectors)
        detector = MockDetector([make_face(20, 20, 80, 80)])
        clock = FakeClock()
        config = AccessControlConfig(
            recognition_threshold=0.75,
            min_embedding_samples=1,
            max_embedding_samples=1,
            min_stable_frames=1,
            min_stable_duration_ms=0,
        )

        pipeline = AccessControlPipeline(
            detector=detector,
            embedder=embedder,
            repository=MockRepository([template]),
            config=config,
            aligner=MockAligner(),
            spoof_detector=MockSpoof(),
            quality_checker=MockQuality(),
            clock=clock.monotonic,
        )

        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # Frame 1: Below threshold -> Failed authentication / DENY_NO_MATCH
        res1 = pipeline.process_frame(frame)
        self.assertEqual(res1["authentication_result"], AuthenticationResult.DENY_NO_MATCH.value)
        self.assertEqual(embedder.call_count, 1)

        # Advance clock past _recognition_interval (0.25s)
        clock.advance(0.3)

        # Frame 2: Still below threshold -> Keeps on checking!
        res2 = pipeline.process_frame(frame)
        self.assertEqual(res2["authentication_result"], AuthenticationResult.DENY_NO_MATCH.value)
        self.assertEqual(embedder.call_count, 2)

        # Advance clock past interval
        clock.advance(0.3)

        # Frame 3: Person adjusts face / angle, similarity exceeds threshold -> Access Granted!
        res3 = pipeline.process_frame(frame)
        self.assertEqual(res3["authentication_result"], AuthenticationResult.GRANT.value)
        self.assertEqual(res3["user_id"], "user_001")
        self.assertEqual(embedder.call_count, 3)

        # Advance clock past interval
        clock.advance(0.3)

        # Frame 4: Track is now successfully recognized. Fast path takes over!
        res4 = pipeline.process_frame(frame)
        self.assertEqual(res4["authentication_result"], AuthenticationResult.GRANT.value)
        # Embedder was NOT called again once granted
        self.assertEqual(embedder.call_count, 3)


class KioskChatbotPresenceTests(unittest.TestCase):
    """Verify chatbot presence fast-path and fallback re-identification."""

    def setUp(self):
        self.owner_embedding = np.array([1.0, 0.0], dtype=np.float32)
        self.other_embedding = np.array([0.0, 1.0], dtype=np.float32)
        self.token = EdgeAuthToken(
            access_token="jwt-token",
            session_id=1,
            user_id=101,
            email="alice@test.edu",
            roles=("STUDENT",),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        )
        self.store = KioskStateStore(RuntimeConfig(sync_device_id="door-1", sync_device_name="Door 1"))

    def test_chatbot_presence_verifies_identity_even_with_same_track(self):
        embedder = CountingEmbedder(self.owner_embedding)
        face_det = make_face(20, 20, 80, 80)
        detector = MockDetector([face_det])
        config = AccessControlConfig(recognition_threshold=0.75, min_stable_frames=1, min_stable_duration_ms=0)
        pipeline = AccessControlPipeline(
            detector=detector,
            embedder=embedder,
            repository=MockRepository([]),
            config=config,
            aligner=MockAligner(),
            spoof_detector=MockSpoof(),
            quality_checker=MockQuality(),
        )

        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # Establish track in pipeline
        desc = pipeline.describe_faces(frame, include_embeddings=True)
        owner_track_id = desc["faces"][0]["track_id"]
        self.assertIsNotNone(owner_track_id)
        embedder_calls_after_init = embedder.call_count

        # Start chat session with owner_face_track_id
        session = self.store.start_chat_session(
            token=self.token,
            owner_embedding=self.owner_embedding,
            owner_face_track_id=str(owner_track_id),
        )
        self.assertEqual(session.owner_face_track_id, str(owner_track_id))

        # Perform 5 presence checks
        for _ in range(5):
            present, new_tid, bboxes = _detect_owner_presence(
                pipeline, frame, self.owner_embedding, owner_track_id=self.store.current_owner_track_id()
            )
            self.assertTrue(present)
            self.assertEqual(new_tid, owner_track_id)

        # A spatial track can be reused by another person; verify identity each check.
        self.assertEqual(embedder.call_count, embedder_calls_after_init + 5)
        embedder.vectors = [self.other_embedding]
        present, _, _ = _detect_owner_presence(
            pipeline, frame, self.owner_embedding, owner_track_id=owner_track_id
        )
        self.assertFalse(present)

    def test_chatbot_presence_fallback_reacquires_owner_with_new_track(self):
        embedder = CountingEmbedder(self.owner_embedding)
        face_det = make_face(20, 20, 80, 80)
        detector = MockDetector([face_det])
        config = AccessControlConfig(recognition_threshold=0.75, min_stable_frames=1, min_stable_duration_ms=0)
        pipeline = AccessControlPipeline(
            detector=detector,
            embedder=embedder,
            repository=MockRepository([]),
            config=config,
            aligner=MockAligner(),
            spoof_detector=MockSpoof(),
            quality_checker=MockQuality(),
        )

        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # Session was started with an old track ID (e.g. "999") that is no longer active
        self.store.start_chat_session(
            token=self.token,
            owner_embedding=self.owner_embedding,
            owner_face_track_id="999",
        )

        # Presence check detects track ID 1 (not 999). It should fall back to Tier 2 (embedding check),
        # recognize the owner, and report the new track ID.
        present, new_tid, bboxes = _detect_owner_presence(
            pipeline, frame, self.owner_embedding, owner_track_id=self.store.current_owner_track_id()
        )
        self.assertTrue(present)
        self.assertIsNotNone(new_tid)
        self.assertNotEqual(new_tid, 999)

        # Update store with new track ID
        self.store.update_owner_track_id(new_tid)
        self.assertEqual(self.store.current_owner_track_id(), str(new_tid))

        # Subsequent checks still verify the owner identity
        embed_calls = embedder.call_count
        present2, tid2, _ = _detect_owner_presence(
            pipeline, frame, self.owner_embedding, owner_track_id=self.store.current_owner_track_id()
        )
        self.assertTrue(present2)
        self.assertEqual(tid2, new_tid)
        # Spatial tracking does not replace identity verification.
        self.assertEqual(embedder.call_count, embed_calls + 1)

    def test_chatbot_presence_fails_for_different_person(self):
        # Embedder returns another person's embedding
        embedder = CountingEmbedder(self.other_embedding)
        detector = MockDetector([make_face(20, 20, 80, 80)])
        config = AccessControlConfig(recognition_threshold=0.75, min_stable_frames=1, min_stable_duration_ms=0)
        pipeline = AccessControlPipeline(
            detector=detector,
            embedder=embedder,
            repository=MockRepository([]),
            config=config,
            aligner=MockAligner(),
            spoof_detector=MockSpoof(),
            quality_checker=MockQuality(),
        )

        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # Session was for owner, but another person is present
        self.store.start_chat_session(
            token=self.token,
            owner_embedding=self.owner_embedding,
            owner_face_track_id="999",
        )

        present, new_tid, bboxes = _detect_owner_presence(
            pipeline, frame, self.owner_embedding, owner_track_id="999"
        )
        self.assertFalse(present)
        self.assertIsNone(new_tid)


if __name__ == "__main__":
    unittest.main()
