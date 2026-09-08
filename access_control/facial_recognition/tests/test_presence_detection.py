"""Unit tests for camera-based presence and attention detection."""

import unittest
from typing import List, Optional

import numpy as np

from access_control.facial_recognition.src.face.presence import (
    PresenceCandidate,
    PresenceConfig,
    PresenceDetector,
    PresenceState,
    calculate_head_pose_from_landmarks,
)
from access_control.facial_recognition.src.face.types import DetectedFace


def make_landmarks(
    left_eye: tuple[float, float] = (400, 300),
    right_eye: tuple[float, float] = (500, 300),
    nose: tuple[float, float] = (450, 360),
    left_mouth: tuple[float, float] = (415, 420),
    right_mouth: tuple[float, float] = (485, 420),
) -> np.ndarray:
    """Create 5-point YuNet landmark array."""
    return np.array([left_eye, right_eye, nose, left_mouth, right_mouth], dtype=np.float32)


def make_face(
    bbox: tuple[float, float, float, float] = (350, 200, 550, 480),
    confidence: float = 0.95,
    track_id: Optional[int] = 1,
    landmarks: Optional[np.ndarray] = None,
) -> DetectedFace:
    """Create a DetectedFace with default frontal landmarks."""
    if landmarks is None:
        landmarks = make_landmarks()
    return DetectedFace(
        bbox=list(bbox),
        confidence=confidence,
        landmarks=landmarks,
        track_id=track_id,
    )


class FakeClock:
    """Deterministic monotonic clock for simulation testing."""

    def __init__(self, initial_time: float = 100.0):
        self.current_time = initial_time

    def time(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> float:
        self.current_time += seconds
        return self.current_time


class TestHeadPoseEstimation(unittest.TestCase):
    """Verify geometric head pose estimation from 5-point landmarks."""

    def test_frontal_landmarks(self):
        landmarks = make_landmarks(
            left_eye=(400, 300),
            right_eye=(500, 300),
            nose=(450, 350),
            left_mouth=(420, 410),
            right_mouth=(480, 410),
        )
        valid, yaw, pitch, roll = calculate_head_pose_from_landmarks(landmarks)
        self.assertTrue(valid)
        self.assertLess(yaw, 10.0, f"Expected low yaw for frontal face, got {yaw}")
        self.assertLess(pitch, 15.0, f"Expected low pitch for frontal face, got {pitch}")
        self.assertLess(roll, 5.0, f"Expected low roll for horizontal eyes, got {roll}")

    def test_turned_head_yaw(self):
        # Nose shifted strongly to the right (face turned right)
        landmarks = make_landmarks(
            left_eye=(400, 300),
            right_eye=(500, 300),
            nose=(490, 350),  # nose close to right eye
            left_mouth=(410, 410),
            right_mouth=(495, 410),
        )
        valid, yaw, pitch, roll = calculate_head_pose_from_landmarks(landmarks)
        self.assertTrue(valid)
        self.assertGreater(yaw, 25.0, f"Expected high yaw for turned face, got {yaw}")

    def test_pitched_head_tilt(self):
        # Eyes and mouth vertically compressed (looking up or down)
        landmarks = make_landmarks(
            left_eye=(400, 250),
            right_eye=(500, 250),
            nose=(450, 310),
            left_mouth=(410, 470),
            right_mouth=(490, 470),
        )
        valid, yaw, pitch, roll = calculate_head_pose_from_landmarks(landmarks)
        self.assertTrue(valid)
        self.assertGreater(pitch, 20.0, f"Expected high pitch for tilted face, got {pitch}")

    def test_invalid_or_missing_landmarks(self):
        valid, yaw, pitch, roll = calculate_head_pose_from_landmarks(None)
        self.assertFalse(valid)
        self.assertEqual(yaw, 90.0)

        # Invalid shape
        bad_shape = np.zeros((3, 2), dtype=np.float32)
        valid, yaw, pitch, roll = calculate_head_pose_from_landmarks(bad_shape)
        self.assertFalse(valid)


class TestPresenceDetector(unittest.TestCase):
    """Comprehensive test suite for hands-free chatbot activation scenarios."""

    def setUp(self):
        self.clock = FakeClock(100.0)
        self.config = PresenceConfig(
            enabled=True,
            dwell_seconds=3.0,
            grace_period_seconds=0.4,
            cooldown_seconds=5.0,
            interaction_zone=(0.15, 0.10, 0.85, 0.90),
            min_face_size_ratio=0.15,
            max_yaw_degrees=25.0,
            max_pitch_degrees=20.0,
            max_movement_speed=0.45,
            min_confidence=0.50,
        )
        self.intents_detected = []
        self.detector = PresenceDetector(
            config=self.config,
            on_intent_detected=lambda: self.intents_detected.append(self.clock.time()),
            clock=self.clock.time,
        )

    def test_scenario_1_person_stands_facing_terminal_for_3_seconds(self):
        """1. Person stands facing terminal for >= 3s -> triggers activation once."""
        face = make_face(track_id=1)

        # Frame 0: t = 100.0s -> initial detection
        st0 = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st0.state, PresenceState.PRESENCE_DETECTED)
        self.assertEqual(st0.dwell_progress, 0.0)
        self.assertFalse(st0.intent_detected)
        self.assertEqual(len(self.intents_detected), 0)

        # Advance 1.5s -> t = 101.5s
        self.clock.advance(1.5)
        st1 = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st1.state, PresenceState.DWELLING)
        self.assertAlmostEqual(st1.dwell_progress, 0.5, places=2)
        self.assertFalse(st1.intent_detected)
        self.assertEqual(len(self.intents_detected), 0)

        # Advance 1.5s -> t = 103.0s (total 3.0s dwell)
        self.clock.advance(1.5)
        st2 = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st2.state, PresenceState.TRIGGERED)
        self.assertEqual(st2.dwell_progress, 1.0)
        self.assertTrue(st2.intent_detected)
        self.assertEqual(len(self.intents_detected), 1)
        self.assertEqual(self.intents_detected[0], 103.0)

        # Next frame: state transitions to CHATBOT_ACTIVE, no duplicate trigger
        self.clock.advance(0.2)
        st3 = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st3.state, PresenceState.CHATBOT_ACTIVE)
        self.assertFalse(st3.intent_detected)
        self.assertEqual(len(self.intents_detected), 1)

    def test_scenario_2_person_stays_less_than_3_seconds(self):
        """2. Person stays < 3s -> no activation."""
        face = make_face(track_id=1)
        self.detector.update([face], frame_shape=(720, 1280))

        # Advance 2.0s
        self.clock.advance(2.0)
        st = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st.state, PresenceState.DWELLING)
        self.assertAlmostEqual(st.dwell_progress, 2.0 / 3.0, places=2)
        self.assertFalse(st.intent_detected)
        self.assertEqual(len(self.intents_detected), 0)

    def test_scenario_3_person_leaves_at_2_seconds(self):
        """3. Person leaves at 2s -> timer resets to 0 after grace period."""
        face = make_face(track_id=1)
        self.detector.update([face], frame_shape=(720, 1280))
        self.clock.advance(2.0)
        self.detector.update([face], frame_shape=(720, 1280))

        # Person leaves; frame with no faces at t = 102.1s (missing 0.1s <= 0.4s grace period)
        self.clock.advance(0.1)
        st_grace = self.detector.update([], frame_shape=(720, 1280))
        self.assertEqual(st_grace.state, PresenceState.DWELLING)
        self.assertGreater(st_grace.dwell_progress, 0.0)

        # Missing exceeds 0.4s grace period (missing 0.5s > 0.4s)
        self.clock.advance(0.4)
        st_reset = self.detector.update([], frame_shape=(720, 1280))
        self.assertEqual(st_reset.state, PresenceState.IDLE)
        self.assertEqual(st_reset.dwell_progress, 0.0)
        self.assertEqual(st_reset.dwell_seconds, 0.0)
        self.assertIsNone(st_reset.candidate_track_id)
        self.assertEqual(len(self.intents_detected), 0)

    def test_scenario_4_person_returns_after_leaving(self):
        """4. Person returns after leaving -> new 3s timer starts from 0 (no accumulation)."""
        face = make_face(track_id=1)
        self.detector.update([face], frame_shape=(720, 1280))
        self.clock.advance(2.0)
        self.detector.update([face], frame_shape=(720, 1280))

        # Leaves and grace period expires
        self.clock.advance(1.0)
        self.detector.update([], frame_shape=(720, 1280))
        self.assertEqual(self.detector.state, PresenceState.IDLE)

        # Returns at t = 105.0s
        self.clock.advance(2.0)
        st_return = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st_return.state, PresenceState.PRESENCE_DETECTED)
        self.assertEqual(st_return.dwell_progress, 0.0)
        self.assertEqual(st_return.dwell_seconds, 0.0)

        # After only 1.5s, dwell should be ~0.5, NOT triggered from previous 2.0s
        self.clock.advance(1.5)
        st_mid = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st_mid.state, PresenceState.DWELLING)
        self.assertAlmostEqual(st_mid.dwell_progress, 0.5, places=2)
        self.assertFalse(st_mid.intent_detected)

        # Requires full 3.0s from return to trigger (another 1.5s)
        self.clock.advance(1.5)
        st_trig = self.detector.update([face], frame_shape=(720, 1280))
        self.assertTrue(st_trig.intent_detected)
        self.assertEqual(len(self.intents_detected), 1)

    def test_scenario_5_walking_person_moving_across_frame(self):
        """5. Walking person moving across frame -> flagged as transit/walking, no activation."""
        # Rapid movement across the frame: x shifts 300px per 0.25s on 1280w frame (~0.93 norm/sec > 0.45)
        face1 = make_face(bbox=(100, 200, 300, 480), track_id=10)
        self.detector.update([face1], frame_shape=(720, 1280))

        self.clock.advance(0.25)
        face2 = make_face(bbox=(400, 200, 600, 480), track_id=10)
        self.detector.update([face2], frame_shape=(720, 1280))

        self.clock.advance(0.25)
        face3 = make_face(bbox=(700, 200, 900, 480), track_id=10)
        st3 = self.detector.update([face3], frame_shape=(720, 1280))

        # Rapid movement causes valid_attention=False, so dwell is rejected/reset
        self.assertFalse(st3.intent_detected)
        self.assertEqual(len(self.intents_detected), 0)

    def test_scenario_6_distant_background_face_rejected(self):
        """6. Distant/background face (<0.15 size ratio) -> rejected."""
        # Face height = 50px on 720p frame -> ratio = 50/720 = 0.069 < 0.15
        distant_face = make_face(bbox=(400, 200, 440, 250), track_id=2)
        st = self.detector.update([distant_face], frame_shape=(720, 1280))
        self.assertEqual(st.state, PresenceState.IDLE)
        self.assertEqual(st.dwell_progress, 0.0)
        self.assertFalse(st.attention_valid)
        self.assertFalse(st.intent_detected)

    def test_scenario_7_remains_after_chatbot_activates(self):
        """7. Remains after chatbot activates -> no repeat activations (CHATBOT_ACTIVE)."""
        face = make_face(track_id=1)
        self.detector.update([face], frame_shape=(720, 1280))
        self.clock.advance(3.0)
        st_trigger = self.detector.update([face], frame_shape=(720, 1280))
        self.assertTrue(st_trigger.intent_detected)
        self.assertEqual(len(self.intents_detected), 1)

        # Remains for 10 more seconds while chat is active
        for _ in range(10):
            self.clock.advance(1.0)
            st = self.detector.update([face], frame_shape=(720, 1280), is_chat_active=True)
            self.assertEqual(st.state, PresenceState.CHATBOT_ACTIVE)
            self.assertFalse(st.intent_detected)

        # Callback must still have been called exactly once
        self.assertEqual(len(self.intents_detected), 1)

    def test_scenario_8_detection_loss_within_400ms_grace_period(self):
        """8. Detection loss within 400ms grace period -> dwell continues."""
        face = make_face(track_id=1)
        self.detector.update([face], frame_shape=(720, 1280))
        self.clock.advance(1.0)
        self.detector.update([face], frame_shape=(720, 1280))

        # Temporary frame drop of 250ms (<= 400ms)
        self.clock.advance(0.25)
        st_drop = self.detector.update([], frame_shape=(720, 1280))
        self.assertEqual(st_drop.state, PresenceState.DWELLING)
        self.assertGreater(st_drop.dwell_progress, 0.0)

        # Face recovered at next frame (additional 0.15s)
        self.clock.advance(0.15)
        st_rec = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st_rec.state, PresenceState.DWELLING)
        self.assertAlmostEqual(st_rec.dwell_progress, 1.4 / 3.0, places=2)

        # Advance remaining time to 3.0s
        self.clock.advance(1.6)
        st_trig = self.detector.update([face], frame_shape=(720, 1280))
        self.assertTrue(st_trig.intent_detected)

    def test_scenario_9_detection_loss_exceeding_400ms_grace_period(self):
        """9. Detection loss exceeding 400ms grace period -> dwell resets."""
        face = make_face(track_id=1)
        self.detector.update([face], frame_shape=(720, 1280))
        self.clock.advance(1.5)
        self.detector.update([face], frame_shape=(720, 1280))

        # Camera gap of 500ms (> 400ms grace period)
        self.clock.advance(0.5)
        st_lost = self.detector.update([], frame_shape=(720, 1280))
        self.assertEqual(st_lost.state, PresenceState.IDLE)
        self.assertEqual(st_lost.dwell_progress, 0.0)
        self.assertIsNone(st_lost.candidate_track_id)

    def test_scenario_10_multiple_faces_visible(self):
        """10. Multiple faces visible -> candidate tracking continuity preserved."""
        # Face 1 is central and large; Face 2 is smaller and off-center
        face1 = make_face(bbox=(300, 150, 600, 500), track_id=1)
        face2 = make_face(bbox=(700, 200, 850, 400), track_id=2)

        # Initial frame selects Face 1
        st0 = self.detector.update([face1, face2], frame_shape=(720, 1280))
        self.assertEqual(st0.candidate_track_id, 1)

        # Next frames with both faces -> retains Face 1 due to track continuity
        self.clock.advance(1.0)
        st1 = self.detector.update([face1, face2], frame_shape=(720, 1280))
        self.assertEqual(st1.candidate_track_id, 1)
        self.assertAlmostEqual(st1.dwell_progress, 1.0 / 3.0, places=2)

    def test_scenario_11_cooldown_period_after_chat_ends(self):
        """11. Chatbot ends -> enters cooldown; dwell does not start until cooldown finishes."""
        face = make_face(track_id=1)
        # Put into active chat
        self.detector.notify_chat_started()
        self.assertEqual(self.detector.state, PresenceState.CHATBOT_ACTIVE)

        # End chat
        self.detector.notify_chat_ended()
        self.assertEqual(self.detector.state, PresenceState.COOLDOWN)

        # User is in front of camera at t = 102.0s (2s into 5s cooldown)
        self.clock.advance(2.0)
        st_cool = self.detector.update([face], frame_shape=(720, 1280))
        self.assertEqual(st_cool.state, PresenceState.COOLDOWN)
        self.assertEqual(st_cool.dwell_progress, 0.0)
        self.assertFalse(st_cool.intent_detected)

        # Advance past 5.0s cooldown -> t = 105.5s
        self.clock.advance(3.5)
        st_idle = self.detector.update([face], frame_shape=(720, 1280))
        # Cooldown completed, starts new presence detection
        self.assertEqual(st_idle.state, PresenceState.PRESENCE_DETECTED)
        self.assertEqual(st_idle.dwell_progress, 0.0)

    def test_scenario_12_feature_disabled(self):
        """12. Feature disabled (enabled=False) -> inactive."""
        disabled_config = PresenceConfig(enabled=False)
        detector = PresenceDetector(config=disabled_config, clock=self.clock.time)
        face = make_face(track_id=1)

        for _ in range(5):
            self.clock.advance(1.0)
            st = detector.update([face], frame_shape=(720, 1280))
            self.assertEqual(st.state, PresenceState.IDLE)
            self.assertEqual(st.dwell_progress, 0.0)
            self.assertFalse(st.intent_detected)


if __name__ == "__main__":
    unittest.main()
