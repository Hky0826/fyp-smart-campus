"""Configurable quality gate run only on detector-confirmed faces."""
from dataclasses import dataclass
from math import atan2, degrees

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class FaceQualityConfig:
    min_confidence: float = .7
    min_width: int = 48
    min_height: int = 48
    min_area_ratio: float = .015
    min_sharpness: float = 35.0
    min_brightness: float = 45.0
    max_brightness: float = 215.0
    center_tolerance: float = .4
    boundary_margin: int = 2
    max_eye_tilt_degrees: float = 18.0
    max_nose_offset_ratio: float = .65


@dataclass(frozen=True, slots=True)
class QualityResult:
    passed: bool
    status: str
    reasons: tuple[str, ...]
    sharpness: float = 0
    brightness: float = 0


class FaceQualityEvaluator:
    def __init__(self, config=FaceQualityConfig()):
        self.config = config

    def evaluate(self, frame, detection):
        config = self.config
        box = detection.box
        height, width = frame.image.shape[:2]
        reasons = []
        if detection.confidence < config.min_confidence:
            reasons.append('low_detector_confidence')
        if box.width < config.min_width or box.height < config.min_height:
            reasons.append('move_closer')
        if box.area / max(float(width * height), 1) < config.min_area_ratio:
            reasons.append('move_closer')
        center_x, center_y = box.center
        if abs(center_x - width / 2) > width * config.center_tolerance or abs(center_y - height / 2) > height * config.center_tolerance:
            reasons.append('move_to_center')
        margin = config.boundary_margin
        if box.x <= margin or box.y <= margin or box.x2 >= width - margin or box.y2 >= height - margin:
            reasons.append('face_partially_clipped')
        landmarks = np.asarray(detection.landmarks, np.float32)
        if landmarks.shape != (5, 2) or not np.all(np.isfinite(landmarks)):
            reasons.append('invalid_landmarks')
        else:
            right_eye, left_eye, nose = landmarks[:3]
            eye_vector = left_eye - right_eye
            eye_distance = float(np.linalg.norm(eye_vector))
            eye_tilt = abs(degrees(atan2(float(eye_vector[1]), float(eye_vector[0]))))
            if eye_tilt > config.max_eye_tilt_degrees:
                reasons.append('excessive_pose')
            eye_midpoint = (left_eye + right_eye) / 2
            if eye_distance <= 1 or abs(float(nose[0] - eye_midpoint[0])) / eye_distance > config.max_nose_offset_ratio:
                reasons.append('excessive_pose')
        x1, y1, x2, y2 = box.clipped(width, height).as_xyxy()
        crop = frame.image[y1:y2, x1:x2]
        if crop.size == 0:
            return QualityResult(False, 'No face detected', ('empty_crop',))
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        brightness = float(np.mean(gray))
        if sharpness < config.min_sharpness:
            reasons.append('hold_still')
        if brightness < config.min_brightness:
            reasons.append('lighting_too_dark')
        if brightness > config.max_brightness:
            reasons.append('lighting_too_bright')
        labels = {
            'move_closer': 'Move closer',
            'move_to_center': 'Move to the center',
            'hold_still': 'Face image too blurry',
            'lighting_too_dark': 'Lighting too dark',
            'lighting_too_bright': 'Lighting too bright',
            'face_partially_clipped': 'Keep your full face in view',
            'excessive_pose': 'Look straight at the camera',
        }
        unique = tuple(dict.fromkeys(reasons))
        return QualityResult(not unique, labels.get(unique[0], 'Face quality insufficient') if unique else 'Verifying identity', unique, sharpness, brightness)
