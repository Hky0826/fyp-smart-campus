"""Structured face-quality assessment for biometric decisions."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .types import DetectedFace

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def _clamp(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


@dataclass(frozen=True)
class FaceQualityConfig:
    min_face_size: int = 48
    min_inter_eye_distance: float = 18.0
    min_face_occupancy: float = 0.015
    max_face_occupancy: float = 0.65
    min_sharpness: float = 0.05
    min_brightness: float = 45.0
    max_brightness: float = 215.0
    min_contrast: float = 25.0
    max_yaw_degrees: float = 30.0
    max_pitch_degrees: float = 25.0
    max_roll_degrees: float = 25.0
    boundary_margin_ratio: float = 0.02
    min_overall_score: float = 0.45
    weights: tuple[float, ...] = (0.14, 0.18, 0.14, 0.10, 0.18, 0.16, 0.10)


@dataclass(frozen=True)
class FaceQualityResult:
    usable: bool
    overall_score: float = 0.0
    size_score: float = 0.0
    sharpness_score: float = 0.0
    exposure_score: float = 0.0
    contrast_score: float = 0.0
    pose_score: float = 0.0
    landmark_score: float = 0.0
    truncation_score: float = 0.0
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.usable

    @property
    def reason(self) -> str:
        return "ok" if not self.failure_reasons else self.failure_reasons[0]

    @property
    def score(self) -> float:
        return self.overall_score


QualityResult = FaceQualityResult


class FaceQualityChecker:
    def __init__(
        self,
        min_face_size: int = 48,
        blur_threshold: float | None = None,
        config: FaceQualityConfig | None = None,
    ) -> None:
        del blur_threshold  # retained for source compatibility; normalized sharpness is used.
        self.config = config or FaceQualityConfig(min_face_size=int(min_face_size))

    def check(self, frame: np.ndarray, face: DetectedFace) -> FaceQualityResult:
        cfg = self.config
        reasons: list[str] = []
        frame_h, frame_w = frame.shape[:2]
        width, height = face.width(), face.height()
        size_score = _clamp(min(width, height) / max(float(cfg.min_face_size), 1.0))
        if width < cfg.min_face_size or height < cfg.min_face_size:
            reasons.append("face_too_small")

        occupancy = (width * height) / max(float(frame_w * frame_h), 1.0)
        occupancy_score = _clamp(occupancy / max(cfg.min_face_occupancy, 1e-6))
        if occupancy < cfg.min_face_occupancy:
            reasons.append("face_occupancy_too_low")
        if occupancy > cfg.max_face_occupancy:
            reasons.append("face_occupancy_too_high")

        x1, y1, x2, y2 = [float(v) for v in face.bbox]
        margin_x = cfg.boundary_margin_ratio * frame_w
        margin_y = cfg.boundary_margin_ratio * frame_h
        boundary_distances = (x1, y1, frame_w - x2, frame_h - y2)
        truncation_score = _clamp(min(boundary_distances) / max(margin_x, margin_y, 1.0))
        if x1 <= 0 or y1 <= 0 or x2 >= frame_w - 1 or y2 >= frame_h - 1:
            reasons.append("face_boundary_truncated")

        landmarks = None if face.landmarks is None else np.asarray(face.landmarks, dtype=np.float32)
        landmark_score, pose_score = self._landmark_and_pose_scores(landmarks, face, reasons)

        ix1, iy1 = max(0, int(np.floor(x1))), max(0, int(np.floor(y1)))
        ix2, iy2 = min(frame_w, int(np.ceil(x2))), min(frame_h, int(np.ceil(y2)))
        crop = frame[iy1:iy2, ix1:ix2]
        if crop.size == 0:
            reasons.append("empty_face_crop")
            return FaceQualityResult(False, failure_reasons=reasons)
        gray = self._gray(crop)

        brightness = float(np.mean(gray))
        if brightness < cfg.min_brightness:
            reasons.append("face_too_dark")
        elif brightness > cfg.max_brightness:
            reasons.append("face_overexposed")
        target = (cfg.min_brightness + cfg.max_brightness) / 2.0
        half_range = max((cfg.max_brightness - cfg.min_brightness) / 2.0, 1.0)
        clipped_ratio = float(np.mean((gray <= 5) | (gray >= 250)))
        exposure_score = _clamp(1.0 - abs(brightness - target) / half_range) * _clamp(1.0 - clipped_ratio * 2.0)

        contrast = float(np.std(gray))
        contrast_score = _clamp(contrast / max(cfg.min_contrast, 1e-6))
        if contrast < cfg.min_contrast:
            reasons.append("face_low_contrast")

        sharpness_score = self._sharpness_score(gray)
        if sharpness_score < cfg.min_sharpness:
            reasons.append("face_too_blurry")

        scores = np.array(
            [min(size_score, occupancy_score), sharpness_score, exposure_score, contrast_score,
             pose_score, landmark_score, truncation_score],
            dtype=np.float32,
        )
        weights = np.asarray(cfg.weights, dtype=np.float32)
        overall = float(np.dot(scores, weights) / max(float(np.sum(weights)), 1e-6))
        if overall < cfg.min_overall_score:
            reasons.append("overall_quality_too_low")
        return FaceQualityResult(
            usable=not reasons,
            overall_score=overall,
            size_score=float(scores[0]),
            sharpness_score=sharpness_score,
            exposure_score=exposure_score,
            contrast_score=contrast_score,
            pose_score=pose_score,
            landmark_score=landmark_score,
            truncation_score=truncation_score,
            failure_reasons=list(dict.fromkeys(reasons)),
        )

    @staticmethod
    def _gray(crop: np.ndarray) -> np.ndarray:
        if crop.ndim == 2:
            return crop.astype(np.uint8, copy=False)
        if cv2 is not None:
            return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return np.mean(crop, axis=2).astype(np.uint8)

    @staticmethod
    def _sharpness_score(gray: np.ndarray) -> float:
        data = gray.astype(np.float32) / 255.0
        gx = np.diff(data, axis=1)
        gy = np.diff(data, axis=0)
        gradient_energy = float(np.sqrt(np.mean(gx * gx) + np.mean(gy * gy)))
        laplacian_score = 0.0
        if cv2 is not None:
            laplacian_score = _clamp(float(cv2.Laplacian(data, cv2.CV_32F).var()) / 0.02)
        return _clamp(0.65 * (gradient_energy / 0.12) + 0.35 * laplacian_score)

    def _landmark_and_pose_scores(
        self, landmarks: np.ndarray | None, face: DetectedFace, reasons: list[str]
    ) -> tuple[float, float]:
        cfg = self.config
        if landmarks is None or landmarks.shape != (5, 2) or not np.all(np.isfinite(landmarks)):
            reasons.append("invalid_landmarks")
            return 0.0, 0.0
        left_eye, right_eye, nose, left_mouth, right_mouth = landmarks
        eye_distance = float(np.linalg.norm(right_eye - left_eye))
        if left_eye[0] >= right_eye[0] or eye_distance < cfg.min_inter_eye_distance:
            reasons.append("invalid_inter_eye_distance")
        landmark_score = _clamp(eye_distance / max(cfg.min_inter_eye_distance, 1e-6))

        eye_mid = (left_eye + right_eye) * 0.5
        mouth_mid = (left_mouth + right_mouth) * 0.5
        yaw = abs(float(nose[0] - eye_mid[0])) / max(eye_distance, 1e-6) * 90.0
        roll = abs(float(np.degrees(np.arctan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]))))
        vertical = float(mouth_mid[1] - eye_mid[1])
        expected_vertical = max(eye_distance * 1.15, 1e-6)
        pitch = abs(vertical / expected_vertical - 1.0) * 45.0
        if yaw > cfg.max_yaw_degrees:
            reasons.append("face_yaw_too_large")
        if pitch > cfg.max_pitch_degrees:
            reasons.append("face_pitch_too_large")
        if roll > cfg.max_roll_degrees:
            reasons.append("face_roll_too_large")
        pose_score = min(
            _clamp(1.0 - yaw / max(cfg.max_yaw_degrees, 1e-6)),
            _clamp(1.0 - pitch / max(cfg.max_pitch_degrees, 1e-6)),
            _clamp(1.0 - roll / max(cfg.max_roll_degrees, 1e-6)),
        )
        x1, y1, x2, y2 = [float(v) for v in face.bbox]
        tolerance = 0.1 * max(face.width(), face.height())
        if np.any(landmarks[:, 0] < x1 - tolerance) or np.any(landmarks[:, 0] > x2 + tolerance) \
                or np.any(landmarks[:, 1] < y1 - tolerance) or np.any(landmarks[:, 1] > y2 + tolerance):
            reasons.append("landmarks_outside_face")
            landmark_score *= 0.25
        return landmark_score, pose_score
