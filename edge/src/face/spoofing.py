"""Access-control liveness heuristic adapted from the existing edge pipeline."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .types import DetectedFace

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


@dataclass(frozen=True)
class SpoofResult:
    state: str
    score: float
    reason: str


class MotionSpoofDetector:
    """Lightweight motion/pose liveness gate.

    This preserves the prototype behavior in the old `edge` pipeline. It is not
    a trained anti-spoof model, so the thresholds should be tuned on the real
    kiosk camera and deployment lighting.
    """

    def __init__(
        self,
        history_size: int = 6,
        motion_threshold: float = 3.0,
        pose_threshold: float = 0.025,
        spoof_frames: int = 10,
    ) -> None:
        self.motion_threshold = float(motion_threshold)
        self.pose_threshold = float(pose_threshold)
        self.spoof_frames = int(spoof_frames)
        self._prev_gray: Optional[np.ndarray] = None
        self._motion_history: deque[float] = deque(maxlen=history_size)
        self._pose_history: deque[float] = deque(maxlen=history_size)
        self._stagnant_frames = 0

    @staticmethod
    def _pose_proxy(landmarks: np.ndarray) -> float:
        left_eye = landmarks[0]
        right_eye = landmarks[1]
        nose = landmarks[2]
        eye_mid = (left_eye + right_eye) / 2.0
        eye_distance = float(np.linalg.norm(left_eye - right_eye))
        if eye_distance <= 1e-6:
            return 0.0
        return float((nose[0] - eye_mid[0]) / eye_distance)

    def check(self, frame: np.ndarray, face: DetectedFace) -> SpoofResult:
        if cv2 is None:
            return SpoofResult("unknown", 0.0, "opencv_unavailable")

        x1, y1, x2, y2 = face.xyxy_int()
        if x2 <= x1 or y2 <= y1:
            return SpoofResult("unknown", 0.0, "invalid_face_box")

        h, w = frame.shape[:2]
        roi = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        if roi.size == 0:
            return SpoofResult("unknown", 0.0, "empty_face_roi")

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
        gray = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)

        motion = 0.0
        if self._prev_gray is not None:
            motion = float(np.mean(cv2.absdiff(gray, self._prev_gray)))
        self._prev_gray = gray
        self._motion_history.append(motion)

        pose = None
        if face.landmarks is not None:
            landmarks = np.asarray(face.landmarks, dtype=np.float32)
            if landmarks.shape == (5, 2):
                pose = self._pose_proxy(landmarks)
                self._pose_history.append(pose)

        if motion >= self.motion_threshold:
            self._stagnant_frames = 0
            score = motion + (abs(pose) * 10.0 if pose is not None else 0.0)
            return SpoofResult("live", float(score), "motion_detected")

        self._stagnant_frames += 1
        if len(self._motion_history) < self._motion_history.maxlen:
            return SpoofResult("unknown", float(motion), "warming_up")

        pose_range = 0.0
        if len(self._pose_history) >= 2:
            pose_range = float(max(self._pose_history) - min(self._pose_history))
        if pose_range >= self.pose_threshold:
            self._stagnant_frames = 0
            return SpoofResult("live", pose_range, "pose_change_detected")

        score = max(float(np.mean(self._motion_history)), pose_range)
        if self._stagnant_frames >= self.spoof_frames:
            return SpoofResult("spoof", score, "insufficient_motion_or_pose_change")
        return SpoofResult("unknown", score, "insufficient_motion_or_pose_change")

    def reset(self) -> None:
        self._prev_gray = None
        self._motion_history.clear()
        self._pose_history.clear()
        self._stagnant_frames = 0


SpoofDetector = MotionSpoofDetector
