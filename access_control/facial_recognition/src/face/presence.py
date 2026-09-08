"""Hands-free presence and attention detector for edge access-control kiosk.

Monitors face detections and tracking continuity to identify when a user
intentionally stands in front of the terminal facing the camera for a
continuous dwell duration (~3 seconds), triggering hands-free chatbot activation.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence

import numpy as np

from .types import DetectedFace

logger = logging.getLogger(__name__)


class PresenceState(str, Enum):
    IDLE = "IDLE"
    PRESENCE_DETECTED = "PRESENCE_DETECTED"
    DWELLING = "DWELLING"
    TRIGGERED = "TRIGGERED"
    CHATBOT_ACTIVE = "CHATBOT_ACTIVE"
    COOLDOWN = "COOLDOWN"


@dataclass(frozen=True)
class PresenceConfig:
    """Configuration options for presence and attention detection."""

    enabled: bool = True
    dwell_seconds: float = 3.0
    grace_period_seconds: float = 0.4
    cooldown_seconds: float = 5.0
    # Normalized interaction zone (x_min, y_min, x_max, y_max) relative to frame dimensions
    interaction_zone: tuple[float, float, float, float] = (0.15, 0.10, 0.85, 0.90)
    # Minimum face height / frame height ratio to reject distant background faces
    min_face_size_ratio: float = 0.15
    # Maximum allowed head yaw (degrees) for frontal attention
    max_yaw_degrees: float = 25.0
    # Maximum allowed head pitch (degrees) for frontal attention
    max_pitch_degrees: float = 20.0
    # Maximum normalized screen displacement per second before flagging transit/walking
    max_movement_speed: float = 0.45
    # Minimum detection confidence
    min_confidence: float = 0.50


@dataclass
class PresenceCandidate:
    """Evaluated face candidate for interaction attention."""

    track_id: Optional[int | str]
    bbox: list[int]
    center_norm: tuple[float, float]
    size_ratio: float
    yaw: float
    pitch: float
    roll: float
    is_frontal: bool
    inside_zone: bool
    size_valid: bool
    valid_attention: bool
    score: float


@dataclass
class PresenceStatus:
    """Snapshot status emitted on every evaluated camera frame."""

    state: PresenceState
    dwell_progress: float = 0.0
    dwell_seconds: float = 0.0
    candidate_bbox: Optional[list[int]] = None
    candidate_track_id: Optional[int | str] = None
    attention_valid: bool = False
    intent_detected: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "dwell_progress": round(self.dwell_progress, 3),
            "dwell_seconds": round(self.dwell_seconds, 2),
            "candidate_bbox": self.candidate_bbox,
            "candidate_track_id": self.candidate_track_id,
            "attention_valid": self.attention_valid,
            "intent_detected": self.intent_detected,
        }


def calculate_head_pose_from_landmarks(
    landmarks: np.ndarray | None,
) -> tuple[bool, float, float, float]:
    """Calculate (is_valid, yaw, pitch, roll) in degrees from 5-point YuNet landmarks.

    Landmarks format:
    0: right eye, 1: left eye, 2: nose tip, 3: right mouth corner, 4: left mouth corner.
    """
    if landmarks is None or landmarks.shape != (5, 2) or not np.all(np.isfinite(landmarks)):
        return False, 90.0, 90.0, 90.0

    p0, p1, nose, p3, p4 = landmarks
    # Order eyes left-to-right on image x-axis
    left_eye = p0 if p0[0] <= p1[0] else p1
    right_eye = p1 if p0[0] <= p1[0] else p0
    left_mouth = p3 if p3[0] <= p4[0] else p4
    right_mouth = p4 if p3[0] <= p4[0] else p3

    eye_distance = float(np.linalg.norm(right_eye - left_eye))
    if eye_distance < 1.0:
        return False, 90.0, 90.0, 90.0

    eye_mid = (left_eye + right_eye) * 0.5
    mouth_mid = (left_mouth + right_mouth) * 0.5

    # Horizontal yaw: offset of nose from eye midpoint normalized by inter-eye distance
    yaw = abs(float(nose[0] - eye_mid[0])) / max(eye_distance, 1e-6) * 90.0

    # In-plane roll
    roll = abs(float(np.degrees(np.arctan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]))))

    # Vertical pitch: expected ratio of eye-to-mouth vertical distance vs inter-eye distance (~1.15)
    vertical = float(mouth_mid[1] - eye_mid[1])
    expected_vertical = max(eye_distance * 1.15, 1e-6)
    pitch = abs(vertical / expected_vertical - 1.0) * 45.0

    return True, float(yaw), float(pitch), float(roll)


class PresenceDetector:
    """State machine and attention detector for hands-free chatbot activation."""

    def __init__(
        self,
        config: PresenceConfig | None = None,
        clock: Callable[[], float] | None = None,
        on_intent_detected: Optional[Callable[[], None]] = None,
        on_interaction_intent_detected: Optional[Callable[[PresenceCandidate], None]] = None,
    ) -> None:
        self.config = config or PresenceConfig()
        self._clock = clock or time.monotonic

        self._state = PresenceState.IDLE
        self._candidate_track_id: Optional[int | str] = None
        self._candidate_bbox: Optional[list[int]] = None
        self._candidate_center_history: list[tuple[float, tuple[float, float]]] = []

        self._dwell_start_time: Optional[float] = None
        self._last_seen_time: Optional[float] = None
        self._cooldown_start_time: Optional[float] = None
        self._last_log_time: float = 0.0

        # Event callbacks
        self.on_presence_started: Optional[Callable[[PresenceCandidate], None]] = None
        self.on_presence_lost: Optional[Callable[[], None]] = None
        self.on_dwell_progress: Optional[Callable[[float, float], None]] = None
        if on_interaction_intent_detected is not None:
            self.on_interaction_intent_detected: Optional[Callable[[PresenceCandidate], None]] = on_interaction_intent_detected
        elif on_intent_detected is not None:
            self.on_interaction_intent_detected = lambda _cand: on_intent_detected()
        else:
            self.on_interaction_intent_detected = None

    @property
    def state(self) -> PresenceState:
        return self._state

    @property
    def candidate_track_id(self) -> Optional[int | str]:
        return self._candidate_track_id

    def notify_chat_started(self) -> None:
        """Inform the detector that a chatbot session is currently active."""
        if self._state != PresenceState.CHATBOT_ACTIVE:
            logger.info("PresenceDetector: Chatbot session started; presence activation suppressed")
        self._state = PresenceState.CHATBOT_ACTIVE
        self._reset_dwell()

    def notify_chat_ended(self) -> None:
        """Inform the detector that a chatbot session closed, starting cooldown."""
        now = self._clock()
        self._state = PresenceState.COOLDOWN
        self._cooldown_start_time = now
        self._reset_dwell()
        logger.info(
            "PresenceDetector: Chatbot session ended; entering %.1fs cooldown",
            self.config.cooldown_seconds,
        )

    def reset(self) -> None:
        """Reset the detector back to clean IDLE state."""
        self._state = PresenceState.IDLE
        self._cooldown_start_time = None
        self._reset_dwell()

    def _reset_dwell(self) -> None:
        had_candidate = self._candidate_track_id is not None
        self._candidate_track_id = None
        self._candidate_bbox = None
        self._candidate_center_history.clear()
        self._dwell_start_time = None
        self._last_seen_time = None
        if had_candidate and self.on_presence_lost is not None:
            try:
                self.on_presence_lost()
            except Exception:
                logger.exception("Error in on_presence_lost callback")

    def update(
        self,
        faces: Sequence[DetectedFace],
        tracks: Sequence[Any] | None = None,
        frame_shape: tuple[int, int] = (720, 1280),
        is_chat_active: bool = False,
        is_auth_transition: bool = False,
        timestamp: float | None = None,
    ) -> PresenceStatus:
        """Process one camera frame through the presence state machine."""
        now = timestamp if timestamp is not None else self._clock()
        frame_h, frame_w = frame_shape[0], frame_shape[1]

        # Feature disabled check
        if not self.config.enabled:
            return PresenceStatus(state=PresenceState.IDLE)

        # Active chat check
        if is_chat_active or self._state == PresenceState.CHATBOT_ACTIVE:
            self._state = PresenceState.CHATBOT_ACTIVE
            self._reset_dwell()
            return PresenceStatus(state=PresenceState.CHATBOT_ACTIVE)

        # Cooldown check
        if self._state == PresenceState.COOLDOWN:
            if self._cooldown_start_time is not None:
                elapsed_cooldown = now - self._cooldown_start_time
                if elapsed_cooldown >= self.config.cooldown_seconds:
                    logger.info("PresenceDetector: Cooldown finished; returning to IDLE")
                    self._state = PresenceState.IDLE
                    self._cooldown_start_time = None
                else:
                    return PresenceStatus(state=PresenceState.COOLDOWN)
            else:
                self._state = PresenceState.IDLE

        # Critical authentication transition check (e.g. door grant hold)
        if is_auth_transition:
            return PresenceStatus(
                state=self._state,
                dwell_progress=0.0,
                dwell_seconds=0.0,
                candidate_bbox=self._candidate_bbox,
                candidate_track_id=self._candidate_track_id,
            )

        # Evaluate candidate faces
        candidates = self._evaluate_candidates(faces, tracks, frame_w, frame_h, now)
        valid_candidates = [c for c in candidates if c.valid_attention]

        selected_candidate = self._select_candidate(valid_candidates)

        # State machine update
        status = self._update_dwell_state(selected_candidate, now)
        return status

    def _evaluate_candidates(
        self,
        faces: Sequence[DetectedFace],
        tracks: Sequence[Any] | None,
        frame_w: int,
        frame_h: int,
        now: float,
    ) -> list[PresenceCandidate]:
        candidates: list[PresenceCandidate] = []
        track_map: dict[int, Any] = {}
        if tracks:
            for tr in tracks:
                tid = getattr(tr, "track_id", None)
                if tid is not None:
                    track_map[tid] = tr

        zx1, zy1, zx2, zy2 = self.config.interaction_zone
        zone_cx = (zx1 + zx2) * 0.5
        zone_cy = (zy1 + zy2) * 0.5

        for idx, face in enumerate(faces):
            track_id = face.track_id
            if track_id is None and tracks and idx < len(tracks):
                track_id = getattr(tracks[idx], "track_id", None)

            x1, y1, x2, y2 = [float(v) for v in face.bbox]
            cx_norm = ((x1 + x2) * 0.5) / max(float(frame_w), 1.0)
            cy_norm = ((y1 + y2) * 0.5) / max(float(frame_h), 1.0)
            face_h = max(0.0, y2 - y1)
            size_ratio = face_h / max(float(frame_h), 1.0)

            inside_zone = zx1 <= cx_norm <= zx2 and zy1 <= cy_norm <= zy2
            size_valid = size_ratio >= self.config.min_face_size_ratio
            conf_valid = face.confidence >= self.config.min_confidence

            pose_valid, yaw, pitch, roll = calculate_head_pose_from_landmarks(face.landmarks)
            is_frontal = (
                pose_valid
                and yaw <= self.config.max_yaw_degrees
                and pitch <= self.config.max_pitch_degrees
            )

            # Movement velocity check for rapid transit / walking
            is_walking = self._check_is_walking(track_id, (cx_norm, cy_norm), now)
            valid_attention = inside_zone and size_valid and is_frontal and conf_valid and not is_walking

            dist_to_center = math.hypot(cx_norm - zone_cx, cy_norm - zone_cy)
            score = size_ratio * max(0.0, 1.0 - dist_to_center)

            candidates.append(
                PresenceCandidate(
                    track_id=track_id,
                    bbox=face.xyxy_int(),
                    center_norm=(cx_norm, cy_norm),
                    size_ratio=size_ratio,
                    yaw=yaw,
                    pitch=pitch,
                    roll=roll,
                    is_frontal=is_frontal,
                    inside_zone=inside_zone,
                    size_valid=size_valid,
                    valid_attention=valid_attention,
                    score=score,
                )
            )

        return candidates

    def _check_is_walking(
        self,
        track_id: Optional[int | str],
        center_norm: tuple[float, float],
        now: float,
    ) -> bool:
        if track_id is None or self._candidate_track_id is None or str(track_id) != str(self._candidate_track_id):
            return False

        self._candidate_center_history.append((now, center_norm))
        cutoff = now - 1.0
        self._candidate_center_history = [item for item in self._candidate_center_history if item[0] >= cutoff]

        if len(self._candidate_center_history) >= 3:
            t0, (x0, y0) = self._candidate_center_history[0]
            dt = now - t0
            if dt > 0.2:
                dist = math.hypot(center_norm[0] - x0, center_norm[1] - y0)
                speed = dist / dt
                if speed > self.config.max_movement_speed:
                    return True
        return False

    def _select_candidate(self, valid_candidates: list[PresenceCandidate]) -> Optional[PresenceCandidate]:
        if not valid_candidates:
            return None

        # 1. Track continuity: prefer current candidate if still valid
        if self._candidate_track_id is not None:
            for cand in valid_candidates:
                if cand.track_id is not None and str(cand.track_id) == str(self._candidate_track_id):
                    return cand

        # 2. Select highest scoring candidate (largest + closest to center)
        return max(valid_candidates, key=lambda c: c.score)

    def _update_dwell_state(
        self,
        candidate: Optional[PresenceCandidate],
        now: float,
    ) -> PresenceStatus:
        if candidate is not None:
            # Case 1: Starting dwell on new candidate
            if self._candidate_track_id is None:
                self._candidate_track_id = candidate.track_id
                self._candidate_bbox = candidate.bbox
                self._dwell_start_time = now
                self._last_seen_time = now
                self._state = PresenceState.PRESENCE_DETECTED
                self._candidate_center_history = [(now, candidate.center_norm)]
                logger.info(
                    "Presence candidate detected: track_id=%s, bbox=%s",
                    candidate.track_id,
                    candidate.bbox,
                )
                if self.on_presence_started is not None:
                    try:
                        self.on_presence_started(candidate)
                    except Exception:
                        logger.exception("Error in on_presence_started callback")

                return PresenceStatus(
                    state=self._state,
                    dwell_progress=0.0,
                    dwell_seconds=0.0,
                    candidate_bbox=self._candidate_bbox,
                    candidate_track_id=self._candidate_track_id,
                    attention_valid=True,
                    intent_detected=False,
                )

            # Case 2: Candidate changed to a different person
            if (
                candidate.track_id is not None
                and self._candidate_track_id is not None
                and str(candidate.track_id) != str(self._candidate_track_id)
            ):
                logger.info(
                    "Presence candidate switched from track_id=%s to track_id=%s; resetting dwell",
                    self._candidate_track_id,
                    candidate.track_id,
                )
                self._reset_dwell()
                self._candidate_track_id = candidate.track_id
                self._candidate_bbox = candidate.bbox
                self._dwell_start_time = now
                self._last_seen_time = now
                self._state = PresenceState.PRESENCE_DETECTED
                self._candidate_center_history = [(now, candidate.center_norm)]
                if self.on_presence_started is not None:
                    try:
                        self.on_presence_started(candidate)
                    except Exception:
                        logger.exception("Error in on_presence_started callback")

                return PresenceStatus(
                    state=self._state,
                    dwell_progress=0.0,
                    dwell_seconds=0.0,
                    candidate_bbox=self._candidate_bbox,
                    candidate_track_id=self._candidate_track_id,
                    attention_valid=True,
                    intent_detected=False,
                )

            # Case 3: Same candidate continuing dwell
            self._last_seen_time = now
            self._candidate_bbox = candidate.bbox
            assert self._dwell_start_time is not None
            dwell_time = max(0.0, now - self._dwell_start_time)
            progress = min(1.0, dwell_time / max(self.config.dwell_seconds, 1e-6))
            self._state = PresenceState.DWELLING

            if self.on_dwell_progress is not None:
                try:
                    self.on_dwell_progress(progress, dwell_time)
                except Exception:
                    logger.exception("Error in on_dwell_progress callback")

            # Check for dwell threshold reached
            if dwell_time >= self.config.dwell_seconds:
                logger.info(
                    "Dwell threshold reached (%.2fs >= %.2fs) for track_id=%s; automatic chatbot activation triggered",
                    dwell_time,
                    self.config.dwell_seconds,
                    candidate.track_id,
                )
                self._state = PresenceState.TRIGGERED
                if self.on_interaction_intent_detected is not None:
                    try:
                        self.on_interaction_intent_detected(candidate)
                    except Exception:
                        logger.exception("Error in on_interaction_intent_detected callback")

                self._state = PresenceState.CHATBOT_ACTIVE
                self._reset_dwell()

                return PresenceStatus(
                    state=PresenceState.TRIGGERED,
                    dwell_progress=1.0,
                    dwell_seconds=dwell_time,
                    candidate_bbox=candidate.bbox,
                    candidate_track_id=candidate.track_id,
                    attention_valid=True,
                    intent_detected=True,
                )

            return PresenceStatus(
                state=self._state,
                dwell_progress=progress,
                dwell_seconds=dwell_time,
                candidate_bbox=self._candidate_bbox,
                candidate_track_id=self._candidate_track_id,
                attention_valid=True,
                intent_detected=False,
            )

        # No valid candidate this frame
        if self._candidate_track_id is not None:
            assert self._last_seen_time is not None
            missing_elapsed = now - self._last_seen_time
            if missing_elapsed <= self.config.grace_period_seconds:
                # Within grace period: maintain dwell progress
                assert self._dwell_start_time is not None
                dwell_time = max(0.0, now - self._dwell_start_time)
                progress = min(1.0, dwell_time / max(self.config.dwell_seconds, 1e-6))
                return PresenceStatus(
                    state=self._state,
                    dwell_progress=progress,
                    dwell_seconds=dwell_time,
                    candidate_bbox=self._candidate_bbox,
                    candidate_track_id=self._candidate_track_id,
                    attention_valid=False,
                    intent_detected=False,
                )

            # Exceeded grace period: candidate lost and dwell resets
            logger.info(
                "Presence candidate track_id=%s lost (missing for %.3fs > %.3fs); resetting dwell timer",
                self._candidate_track_id,
                missing_elapsed,
                self.config.grace_period_seconds,
            )
            self._reset_dwell()
            self._state = PresenceState.IDLE
            if self.on_dwell_progress is not None:
                try:
                    self.on_dwell_progress(0.0, 0.0)
                except Exception:
                    logger.exception("Error in on_dwell_progress callback")

            return PresenceStatus(
                state=PresenceState.IDLE,
                dwell_progress=0.0,
                dwell_seconds=0.0,
                candidate_bbox=None,
                candidate_track_id=None,
                attention_valid=False,
                intent_detected=False,
            )

        self._state = PresenceState.IDLE
        return PresenceStatus(
            state=PresenceState.IDLE,
            dwell_progress=0.0,
            dwell_seconds=0.0,
            candidate_bbox=None,
            candidate_track_id=None,
            attention_valid=False,
            intent_detected=False,
        )
