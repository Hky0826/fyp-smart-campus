"""Lightweight timestamp-aware face tracking for access control."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .types import DetectedFace


@dataclass(frozen=True)
class FaceTrackerConfig:
    min_stable_frames: int = 5
    min_stable_duration_ms: int = 250
    max_missed_frames: int = 3
    track_timeout_ms: int = 1000
    min_iou_for_match: float = 0.3
    max_landmark_jump_ratio: float = 0.5


@dataclass
class FaceTrack:
    track_id: int
    bbox: np.ndarray
    landmarks: np.ndarray | None
    created_at: float
    last_seen_at: float
    matched_frames: int = 1
    missed_frames: int = 0
    stable: bool = False
    visible: bool = True

    def as_detection(self, confidence: float = 1.0) -> DetectedFace:
        return DetectedFace(self.bbox.copy(), confidence, self.landmarks, self.track_id)


def bbox_iou(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return 0.0 if union <= 0 else float(intersection / union)


class FaceTracker:
    def __init__(self, config: FaceTrackerConfig | None = None) -> None:
        self.config = config or FaceTrackerConfig()
        self._tracks: dict[int, FaceTrack] = {}
        self._next_track_id = 1

    def update(self, detections: list[DetectedFace], timestamp: float) -> list[FaceTrack]:
        now = float(timestamp)
        self._expire(now)
        for track in self._tracks.values():
            track.visible = False

        candidates: list[tuple[float, int, int]] = []
        for track_id, track in self._tracks.items():
            for detection_index, detection in enumerate(detections):
                score = self._match_score(track, detection)
                if score is not None:
                    candidates.append((score, track_id, detection_index))
        assigned_tracks: set[int] = set()
        assigned_detections: set[int] = set()
        for _, track_id, detection_index in sorted(candidates, reverse=True):
            if track_id in assigned_tracks or detection_index in assigned_detections:
                continue
            self._apply_match(self._tracks[track_id], detections[detection_index], now)
            assigned_tracks.add(track_id)
            assigned_detections.add(detection_index)

        for track_id, track in list(self._tracks.items()):
            if track_id not in assigned_tracks:
                track.missed_frames += 1
        for index, detection in enumerate(detections):
            if index not in assigned_detections:
                self._create_track(detection, now)
        self._expire(now)
        return sorted(self._tracks.values(), key=lambda item: item.track_id)

    def reset(self) -> None:
        self._tracks.clear()

    def _match_score(self, track: FaceTrack, detection: DetectedFace) -> float | None:
        iou = bbox_iou(track.bbox, np.asarray(detection.bbox, dtype=np.float32))
        if iou < self.config.min_iou_for_match:
            return None
        landmark_score = 0.0
        if track.landmarks is not None and detection.landmarks is not None:
            current = np.asarray(detection.landmarks, dtype=np.float32)
            if current.shape != (5, 2) or not np.all(np.isfinite(current)):
                return None
            diagonal = max(float(np.linalg.norm(track.bbox[2:] - track.bbox[:2])), 1.0)
            jump_ratio = float(np.mean(np.linalg.norm(current - track.landmarks, axis=1))) / diagonal
            if jump_ratio > self.config.max_landmark_jump_ratio:
                return None
            landmark_score = 1.0 - jump_ratio
        return iou + 0.25 * landmark_score

    def _apply_match(self, track: FaceTrack, detection: DetectedFace, now: float) -> None:
        track.bbox = np.asarray(detection.bbox, dtype=np.float32).copy()
        track.landmarks = None if detection.landmarks is None else np.asarray(detection.landmarks, dtype=np.float32).copy()
        track.last_seen_at = now
        track.matched_frames += 1
        track.missed_frames = 0
        track.visible = True
        duration_ms = (now - track.created_at) * 1000.0
        track.stable = (
            track.matched_frames >= self.config.min_stable_frames
            and duration_ms >= self.config.min_stable_duration_ms
        )

    def _create_track(self, detection: DetectedFace, now: float) -> None:
        track = FaceTrack(
            track_id=self._next_track_id,
            bbox=np.asarray(detection.bbox, dtype=np.float32).copy(),
            landmarks=None if detection.landmarks is None else np.asarray(detection.landmarks, dtype=np.float32).copy(),
            created_at=now,
            last_seen_at=now,
        )
        track.stable = self.config.min_stable_frames <= 1 and self.config.min_stable_duration_ms <= 0
        self._tracks[track.track_id] = track
        self._next_track_id += 1

    def _expire(self, now: float) -> None:
        timeout = self.config.track_timeout_ms / 1000.0
        self._tracks = {
            track_id: track
            for track_id, track in self._tracks.items()
            if track.missed_frames <= self.config.max_missed_frames and now - track.last_seen_at <= timeout
        }
