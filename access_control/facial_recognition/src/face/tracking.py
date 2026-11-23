"""ByteTrack-powered face tracking for access control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from .bytetrack import ByteTracker, STrack
from .types import DetectedFace


@dataclass(frozen=True)
class FaceTrackerConfig:
    min_stable_frames: int = 2
    min_stable_duration_ms: int = 100
    max_missed_frames: int = 3
    track_timeout_ms: int = 1000
    min_iou_for_match: float = 0.3
    max_landmark_jump_ratio: float = 0.5
    track_high_thresh: float = 0.5
    track_low_thresh: float = 0.1
    new_track_thresh: float = 0.5
    track_buffer: int = 30
    match_thresh: float = 0.7


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
    """Multi-object face tracker backed by ByteTrack and 8D Kalman filtering."""

    def __init__(self, config: FaceTrackerConfig | None = None) -> None:
        self.config = config or FaceTrackerConfig()
        self._byte_tracker = ByteTracker(
            track_high_thresh=self.config.track_high_thresh,
            track_low_thresh=self.config.track_low_thresh,
            new_track_thresh=self.config.new_track_thresh,
            track_buffer=self.config.track_buffer,
            match_thresh=self.config.match_thresh,
        )
        self._tracks: dict[int, FaceTrack] = {}

    @property
    def byte_tracker(self) -> ByteTracker:
        return self._byte_tracker

    def reset(self) -> None:
        self._tracks.clear()
        self._byte_tracker.reset()

    def update(self, detections: list[DetectedFace], timestamp: float) -> list[FaceTrack]:
        now = float(timestamp)
        if not detections:
            self._byte_tracker.update([])
            for track in self._tracks.values():
                track.visible = False
                track.missed_frames += 1
            self._expire(now)
            return sorted(self._tracks.values(), key=lambda t: t.track_id)

        dets_array: list[np.ndarray] = []
        landmarks_list: list[np.ndarray | None] = []
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            score = float(det.confidence)
            dets_array.append(np.array([x1, y1, x2, y2, score], dtype=np.float32))
            landmarks_list.append(det.landmarks)

        active_stracks = self._byte_tracker.update(dets_array, landmarks_list)
        active_ids = {s.track_id for s in active_stracks}

        # Update tracks not matched in this frame
        for track_id, track in list(self._tracks.items()):
            if track_id not in active_ids:
                track.visible = False
                track.missed_frames += 1

        for strack in active_stracks:
            track_id = strack.track_id
            tlbr = np.asarray(strack.tlbr, dtype=np.float32)
            landmarks = strack.landmarks

            if track_id in self._tracks:
                track = self._tracks[track_id]
                track.bbox = tlbr
                if landmarks is not None:
                    track.landmarks = landmarks
                track.last_seen_at = now
                track.matched_frames += 1
                track.missed_frames = 0
                track.visible = True
            else:
                track = FaceTrack(
                    track_id=track_id,
                    bbox=tlbr,
                    landmarks=landmarks,
                    created_at=now,
                    last_seen_at=now,
                    matched_frames=1,
                    missed_frames=0,
                    visible=True,
                )
                self._tracks[track_id] = track

            duration_ms = (now - track.created_at) * 1000.0
            track.stable = (
                track.matched_frames >= self.config.min_stable_frames
                and duration_ms >= self.config.min_stable_duration_ms
            )

        self._expire(now)
        return sorted(self._tracks.values(), key=lambda t: t.track_id)

    def _expire(self, now: float) -> None:
        timeout = self.config.track_timeout_ms / 1000.0
        removed_ids = {s.track_id for s in self._byte_tracker.removed_stracks}
        self._tracks = {
            tid: tr
            for tid, tr in self._tracks.items()
            if tid not in removed_ids and (now - tr.last_seen_at <= timeout)
        }
