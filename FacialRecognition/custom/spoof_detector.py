"""Lightweight anti-spoofing heuristics for the edge kiosk.

This detector is intentionally simple: it looks for small but real face motion
and landmark changes over a short window. It is a prototype gate, not a trained
liveness model.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


@dataclass
class SpoofResult:
    state: str
    score: float
    reason: str


class SpoofDetector:
    def __init__(
        self,
        history_size: int = 6,
        motion_threshold: float = 3.0,
        pose_threshold: float = 0.025,
        spoof_frames: int = 10,
    ):
        self.motion_threshold = float(motion_threshold)
        self.pose_threshold = float(pose_threshold)
        self.spoof_frames = int(spoof_frames)
        self._prev_gray: Optional[np.ndarray] = None
        self._motion_history: deque[float] = deque(maxlen=history_size)
        self._pose_history: deque[float] = deque(maxlen=history_size)
        self._stagnant_frames = 0

    @staticmethod
    def _extract_landmarks(face_row: np.ndarray) -> Optional[np.ndarray]:
        if face_row is None or face_row.shape[0] < 15:
            return None
        try:
            landmarks = np.asarray(face_row[5:15], dtype=np.float32).reshape(5, 2)
            return landmarks
        except Exception:
            return None

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

    def update(self, frame: np.ndarray, face_row: np.ndarray, box: Tuple[int, int, int, int]) -> SpoofResult:
        x, y, w, h = box
        if w <= 0 or h <= 0:
            return SpoofResult("unknown", 0.0, "invalid_face_box")

        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(frame.shape[1], x + w)
        y2 = min(frame.shape[0], y + h)
        if x2 <= x1 or y2 <= y1:
            return SpoofResult("unknown", 0.0, "empty_face_roi")

        roi = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)

        motion = 0.0
        if self._prev_gray is not None:
            motion = float(np.mean(cv2.absdiff(gray, self._prev_gray)))
        self._prev_gray = gray

        landmarks = self._extract_landmarks(face_row)
        pose = None
        if landmarks is not None:
            pose = self._pose_proxy(landmarks)
            self._pose_history.append(pose)

        self._motion_history.append(motion)

        if motion >= self.motion_threshold:
            self._stagnant_frames = 0
            score = motion
            if pose is not None:
                score += abs(pose) * 10.0
            return SpoofResult("live", float(score), "motion_detected")

        self._stagnant_frames += 1

        if len(self._motion_history) < self._motion_history.maxlen:
            return SpoofResult("unknown", float(motion), "warming_up")

        pose_range = 0.0
        if len(self._pose_history) >= 2:
            pose_range = float(max(self._pose_history) - min(self._pose_history))

        if pose_range >= self.pose_threshold:
            self._stagnant_frames = 0
            return SpoofResult("live", float(pose_range), "pose_change_detected")

        if self._stagnant_frames >= self.spoof_frames:
            score = max(float(np.mean(self._motion_history)), pose_range)
            return SpoofResult("spoof", score, "insufficient_motion_or_pose_change")

        score = max(float(np.mean(self._motion_history)), pose_range)
        return SpoofResult("unknown", score, "insufficient_motion_or_pose_change")

    def reset(self) -> None:
        self._prev_gray = None
        self._motion_history.clear()
        self._pose_history.clear()
        self._stagnant_frames = 0