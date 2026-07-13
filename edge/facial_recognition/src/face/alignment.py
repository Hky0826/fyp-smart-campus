"""Strict five-landmark ArcFace alignment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

from .types import DetectedFace

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


ARCFACE_TEMPLATE = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32,
)


@dataclass(frozen=True)
class AlignmentConfig:
    min_inter_eye_distance: float = 18.0
    landmark_box_tolerance_ratio: float = 0.15
    max_rotation_degrees: float = 35.0
    min_scale: float = 0.4
    max_scale: float = 6.0
    max_translation_ratio: float = 2.0


@dataclass(frozen=True)
class AlignmentResult:
    success: bool
    aligned_face: np.ndarray | None = None
    transform_matrix: np.ndarray | None = None
    failure_reason: str | None = None


class FaceAligner:
    def __init__(
        self, output_size: Tuple[int, int] = (112, 112), config: AlignmentConfig | None = None
    ) -> None:
        self.output_size = output_size
        self.config = config or AlignmentConfig()

    def align(self, frame: np.ndarray, face: DetectedFace) -> AlignmentResult:
        if cv2 is None:
            return AlignmentResult(False, failure_reason="opencv_unavailable")
        landmarks = None if face.landmarks is None else np.asarray(face.landmarks, dtype=np.float32)
        failure = self._validate_landmarks(landmarks, face)
        if failure:
            return AlignmentResult(False, failure_reason=failure)
        assert landmarks is not None
        dst = ARCFACE_TEMPLATE.copy()
        dst[:, 0] *= self.output_size[0] / 112.0
        dst[:, 1] *= self.output_size[1] / 112.0
        transform, _ = cv2.estimateAffinePartial2D(landmarks, dst, method=cv2.LMEDS)
        if transform is None or transform.shape != (2, 3) or not np.all(np.isfinite(transform)):
            return AlignmentResult(False, failure_reason="invalid_affine_transform")
        linear = transform[:, :2]
        determinant = float(np.linalg.det(linear))
        scale = float(np.sqrt(abs(determinant)))
        rotation = abs(float(np.degrees(np.arctan2(linear[1, 0], linear[0, 0]))))
        translation = float(np.linalg.norm(transform[:, 2]))
        if determinant <= 1e-8 or not self.config.min_scale <= scale <= self.config.max_scale:
            return AlignmentResult(False, failure_reason="invalid_alignment_scale")
        if rotation > self.config.max_rotation_degrees:
            return AlignmentResult(False, failure_reason="invalid_alignment_rotation")
        if translation > self.config.max_translation_ratio * max(frame.shape[:2]):
            return AlignmentResult(False, failure_reason="invalid_alignment_translation")
        aligned = cv2.warpAffine(frame, transform, self.output_size, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        if aligned.size == 0 or not np.all(np.isfinite(aligned)):
            return AlignmentResult(False, failure_reason="invalid_aligned_face")
        return AlignmentResult(True, aligned, transform, None)

    def extract(self, frame: np.ndarray, face: DetectedFace) -> np.ndarray:
        """Compatibility API for non-authorization callers; never falls back to a box crop."""
        result = self.align(frame, face)
        if not result.success or result.aligned_face is None:
            raise ValueError(result.failure_reason or "face_alignment_failed")
        return result.aligned_face

    def _validate_landmarks(self, landmarks: np.ndarray | None, face: DetectedFace) -> str | None:
        if landmarks is None or landmarks.shape != (5, 2):
            return "missing_or_invalid_landmarks"
        if not np.all(np.isfinite(landmarks)):
            return "non_finite_landmarks"
        left_eye, right_eye, nose, left_mouth, right_mouth = landmarks
        eye_distance = float(np.linalg.norm(right_eye - left_eye))
        if left_eye[0] >= right_eye[0]:
            return "eyes_not_ordered"
        if eye_distance < self.config.min_inter_eye_distance:
            return "inter_eye_distance_too_small"
        tolerance = self.config.landmark_box_tolerance_ratio * max(face.width(), face.height())
        x1, y1, x2, y2 = [float(v) for v in face.bbox]
        outside = (
            np.any(landmarks[:, 0] < x1 - tolerance)
            or np.any(landmarks[:, 0] > x2 + tolerance)
            or np.any(landmarks[:, 1] < y1 - tolerance)
            or np.any(landmarks[:, 1] > y2 + tolerance)
        )
        if outside:
            return "landmarks_outside_face"
        eye_y = float((left_eye[1] + right_eye[1]) * 0.5)
        mouth_y = float((left_mouth[1] + right_mouth[1]) * 0.5)
        if not eye_y < nose[1] < mouth_y or left_mouth[0] >= right_mouth[0]:
            return "implausible_landmark_geometry"
        if abs(float(nose[0] - (left_eye[0] + right_eye[0]) * 0.5)) > eye_distance * 0.8:
            return "implausible_nose_position"
        return None
