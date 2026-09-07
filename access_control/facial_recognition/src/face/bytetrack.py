"""ByteTrack multi-object tracking implementation for face tracking."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from scipy.optimize import linear_sum_assignment
    HAS_SCIPY = True
except ImportError:  # pragma: no cover
    HAS_SCIPY = False

logger = logging.getLogger(__name__)


class TrackState(Enum):
    New = 0
    Tracked = 1
    Lost = 2
    Removed = 3


class KalmanFilter8D:
    """Simple 8-dimensional linear Kalman Filter for bounding box tracking (x, y, a, h, vx, vy, va, vh)."""

    def __init__(self) -> None:
        ndim, dt = 4, 1.0
        self._motion_mat = np.eye(2 * ndim, dtype=np.float32)
        for i in range(ndim):
            self._motion_mat[i, ndim + i] = dt

        self._update_mat = np.eye(ndim, 2 * ndim, dtype=np.float32)
        self._std_weight_position = 1.0 / 20.0
        self._std_weight_velocity = 1.0 / 160.0

    def initiate(self, measurement: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        mean_pos = measurement
        mean_vel = np.zeros_like(mean_pos)
        mean = np.r_[mean_pos, mean_vel]

        std = [
            2 * self._std_weight_position * measurement[3],
            2 * self._std_weight_position * measurement[3],
            1e-2,
            2 * self._std_weight_position * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            1e-5,
            10 * self._std_weight_velocity * measurement[3],
        ]
        covariance = np.diag(np.square(std))
        return mean, covariance

    def predict(self, mean: np.ndarray, covariance: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        std_pos = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-2,
            self._std_weight_position * mean[3],
        ]
        std_vel = [
            self._std_weight_velocity * mean[3],
            self._std_weight_velocity * mean[3],
            1e-5,
            self._std_weight_velocity * mean[3],
        ]
        motion_cov = np.diag(np.square(np.r_[std_pos, std_vel]))

        mean = np.dot(self._motion_mat, mean)
        covariance = np.linalg.multi_dot((self._motion_mat, covariance, self._motion_mat.T)) + motion_cov
        return mean, covariance

    def update(
        self, mean: np.ndarray, covariance: np.ndarray, measurement: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        std = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-2,
            self._std_weight_position * mean[3],
        ]
        innovation_cov = np.diag(np.square(std))

        projected_mean = np.dot(self._update_mat, mean)
        projected_cov = np.linalg.multi_dot((self._update_mat, covariance, self._update_mat.T)) + innovation_cov

        kalman_gain = np.linalg.multi_dot((covariance, self._update_mat.T, np.linalg.inv(projected_cov)))
        innovation = measurement - projected_mean

        new_mean = mean + np.dot(kalman_gain, innovation)
        new_covariance = covariance - np.linalg.multi_dot((kalman_gain, projected_cov, kalman_gain.T))
        new_covariance = 0.5 * (new_covariance + new_covariance.T)
        return new_mean, new_covariance


class STrack:
    """Individual object track representing a face across video frames."""

    _count = 0

    def __init__(
        self,
        tlwh: np.ndarray,
        score: float,
        landmarks: Optional[np.ndarray] = None,
    ) -> None:
        self._tlwh = np.asarray(tlwh, dtype=np.float32)
        self.score = float(score)
        self.landmarks = None if landmarks is None else np.asarray(landmarks, dtype=np.float32).copy()

        self.kalman_filter: Optional[KalmanFilter8D] = None
        self.mean: Optional[np.ndarray] = None
        self.covariance: Optional[np.ndarray] = None
        self.is_activated = False

        self.track_id = 0
        self.state = TrackState.New
        self.frame_id = 0
        self.start_frame = 0
        self.tracklet_len = 0

    @classmethod
    def reset_id_counter(cls) -> None:
        cls._count = 0

    @classmethod
    def next_id(cls) -> int:
        cls._count += 1
        return cls._count

    def activate(self, kalman_filter: KalmanFilter8D, frame_id: int) -> None:
        self.kalman_filter = kalman_filter
        self.track_id = self.next_id()
        self.mean, self.covariance = self.kalman_filter.initiate(self.tlwh_to_xyah(self._tlwh))

        self.tracklet_len = 0
        self.state = TrackState.Tracked
        self.is_activated = True
        self.frame_id = frame_id
        self.start_frame = frame_id

    def re_activate(self, new_track: STrack, frame_id: int, new_id: bool = False) -> None:
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, self.tlwh_to_xyah(new_track.tlwh)
        )
        self.tracklet_len = 0
        self.state = TrackState.Tracked
        self.is_activated = True
        self.frame_id = frame_id
        if new_id:
            self.track_id = self.next_id()
        self.score = new_track.score
        if new_track.landmarks is not None:
            self.landmarks = new_track.landmarks.copy()

    def update(self, new_track: STrack, frame_id: int) -> None:
        self.frame_id = frame_id
        self.tracklet_len += 1
        self._tlwh = new_track.tlwh.copy()

        if self.kalman_filter is not None and self.mean is not None:
            self.mean, self.covariance = self.kalman_filter.update(
                self.mean, self.covariance, self.tlwh_to_xyah(new_track.tlwh)
            )

        self.state = TrackState.Tracked
        self.is_activated = True
        self.score = new_track.score
        if new_track.landmarks is not None:
            self.landmarks = new_track.landmarks.copy()

    def predict(self) -> None:
        mean_state = self.mean.copy()
        if self.state != TrackState.Tracked:
            mean_state[7] = 0
        if self.kalman_filter is not None and self.mean is not None:
            self.mean, self.covariance = self.kalman_filter.predict(mean_state, self.covariance)

    @property
    def tlwh(self) -> np.ndarray:
        if self.mean is None:
            return self._tlwh.copy()
        ret = self.mean[:4].copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2
        return ret

    @property
    def tlbr(self) -> np.ndarray:
        ret = self.tlwh
        ret[2:] += ret[:2]
        return ret

    @staticmethod
    def tlwh_to_xyah(tlwh: np.ndarray) -> np.ndarray:
        ret = np.asarray(tlwh, dtype=np.float32).copy()
        ret[:2] += ret[2:] / 2
        ret[2] /= ret[3]
        return ret

    @staticmethod
    def tlbr_to_tlwh(tlbr: np.ndarray) -> np.ndarray:
        ret = np.asarray(tlbr, dtype=np.float32).copy()
        ret[2:] -= ret[:2]
        return ret


def iou_distance(atracks: List[STrack], btracks: List[STrack]) -> np.ndarray:
    """Computes 1.0 - IoU distance matrix between two lists of STrack objects."""
    if not atracks or not btracks:
        return np.empty((len(atracks), len(btracks)), dtype=np.float32)

    a_tlbrs = np.ascontiguousarray([track.tlbr for track in atracks], dtype=np.float32)
    b_tlbrs = np.ascontiguousarray([track.tlbr for track in btracks], dtype=np.float32)

    num_a = len(atracks)
    num_b = len(btracks)

    costs = np.ones((num_a, num_b), dtype=np.float32)
    for i in range(num_a):
        ax1, ay1, ax2, ay2 = a_tlbrs[i]
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        for j in range(num_b):
            bx1, by1, bx2, by2 = b_tlbrs[j]
            area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)

            inter_x1 = max(ax1, bx1)
            inter_y1 = max(ay1, by1)
            inter_x2 = min(ax2, bx2)
            inter_y2 = min(ay2, by2)

            inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
            union = area_a + area_b - inter_area
            if union > 0:
                iou = inter_area / union
                costs[i, j] = 1.0 - iou
    return costs


def linear_assignment(
    cost_matrix: np.ndarray, thresh: float
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """Solves linear assignment problem using Hungarian algorithm or greedy fallback."""
    if cost_matrix.size == 0:
        return [], list(range(cost_matrix.shape[0])), list(range(cost_matrix.shape[1]))

    matches, unmatched_a, unmatched_b = [], [], []
    if HAS_SCIPY:
        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        for r, c in zip(row_ind, col_ind):
            if cost_matrix[r, c] <= thresh:
                matches.append((r, c))
            else:
                unmatched_a.append(r)
                unmatched_b.append(c)

        assigned_a = {r for r, _ in matches}
        assigned_b = {c for _, c in matches}
        unmatched_a.extend([r for r in range(cost_matrix.shape[0]) if r not in assigned_a and r not in unmatched_a])
        unmatched_b.extend([c for c in range(cost_matrix.shape[1]) if c not in assigned_b and c not in unmatched_b])
    else:
        # Greedy fallback assignment
        rows, cols = cost_matrix.shape
        cost_list = []
        for r in range(rows):
            for c in range(cols):
                if cost_matrix[r, c] <= thresh:
                    cost_list.append((cost_matrix[r, c], r, c))
        cost_list.sort(key=lambda x: x[0])

        used_rows, used_cols = set(), set()
        for _, r, c in cost_list:
            if r not in used_rows and c not in used_cols:
                matches.append((r, c))
                used_rows.add(r)
                used_cols.add(c)

        unmatched_a = [r for r in range(rows) if r not in used_rows]
        unmatched_b = [c for c in range(cols) if c not in used_cols]

    return matches, unmatched_a, unmatched_b


class ByteTracker:
    """ByteTrack multi-object tracker for preserving face tracks across frames."""

    def __init__(
        self,
        track_high_thresh: float = 0.5,
        track_low_thresh: float = 0.1,
        new_track_thresh: float = 0.6,
        track_buffer: int = 30,
        match_thresh: float = 0.8,
    ) -> None:
        self.track_high_thresh = track_high_thresh
        self.track_low_thresh = track_low_thresh
        self.new_track_thresh = new_track_thresh
        self.buffer_size = track_buffer
        self.max_time_lost = track_buffer
        self.match_thresh = match_thresh

        self.kalman_filter = KalmanFilter8D()
        self.tracked_stracks: List[STrack] = []
        self.lost_stracks: List[STrack] = []
        self.removed_stracks: List[STrack] = []
        self.frame_id = 0

    def reset(self) -> None:
        """Reset all tracking states and counters."""
        self.tracked_stracks.clear()
        self.lost_stracks.clear()
        self.removed_stracks.clear()
        self.frame_id = 0
        STrack.reset_id_counter()

    def update(
        self,
        output_results: List[np.ndarray],
        landmarks_list: Optional[List[Optional[np.ndarray]]] = None,
    ) -> List[STrack]:
        """Update tracks with new frame detection bounding boxes `[x1, y1, x2, y2, score]`."""
        self.frame_id += 1
        activated_stracks: List[STrack] = []
        refind_stracks: List[STrack] = []
        lost_stracks: List[STrack] = []
        removed_stracks: List[STrack] = []

        # Split detections into high confidence and low confidence
        detections_high: List[STrack] = []
        detections_low: List[STrack] = []

        for i, det in enumerate(output_results):
            score = float(det[4])
            tlbr = det[:4]
            tlwh = STrack.tlbr_to_tlwh(tlbr)
            landmarks = landmarks_list[i] if landmarks_list and i < len(landmarks_list) else None
            track = STrack(tlwh, score, landmarks=landmarks)

            if score >= self.track_high_thresh:
                detections_high.append(track)
            elif score >= self.track_low_thresh:
                detections_low.append(track)

        # Separate unconfirmed tracks and confirmed tracks
        unconfirmed: List[STrack] = []
        tracked_stracks: List[STrack] = []
        for track in self.tracked_stracks:
            if not track.is_activated:
                unconfirmed.append(track)
            else:
                tracked_stracks.append(track)

        # Step 1: Predict positions for existing active & lost tracks
        strack_pool = self.joint_stracks(tracked_stracks, self.lost_stracks)
        for strack in strack_pool:
            strack.predict()

        # Step 2: First association with high score detections
        dists = iou_distance(strack_pool, detections_high)
        matches, u_track, u_detection = linear_assignment(dists, thresh=self.match_thresh)

        for itracked, idet in matches:
            track = strack_pool[itracked]
            det = detections_high[idet]
            if track.state == TrackState.Tracked:
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)

        # Step 3: Second association with low score detections
        r_tracked_stracks = [
            strack_pool[i]
            for i in u_track
            if strack_pool[i].state == TrackState.Tracked
        ]
        dists = iou_distance(r_tracked_stracks, detections_low)
        matches, u_r_track, _ = linear_assignment(dists, thresh=0.5)

        for itracked, idet in matches:
            track = r_tracked_stracks[itracked]
            det = detections_low[idet]
            if track.state == TrackState.Tracked:
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)

        for it in u_r_track:
            track = r_tracked_stracks[it]
            if track.state != TrackState.Lost:
                track.state = TrackState.Lost
                lost_stracks.append(track)

        # Step 4: Deal with unconfirmed tracks
        detections_rem = [detections_high[i] for i in u_detection]
        dists = iou_distance(unconfirmed, detections_rem)
        matches, u_unconfirmed, u_detection_rem = linear_assignment(dists, thresh=0.7)

        for itracked, idet in matches:
            unconfirmed[itracked].update(detections_rem[idet], self.frame_id)
            activated_stracks.append(unconfirmed[itracked])

        for it in u_unconfirmed:
            track = unconfirmed[it]
            track.state = TrackState.Removed
            removed_stracks.append(track)

        # Step 5: Init new tracks
        for inew in u_detection_rem:
            track = detections_rem[inew]
            if track.score >= self.new_track_thresh:
                track.activate(self.kalman_filter, self.frame_id)
                activated_stracks.append(track)

        # Step 6: Update state & prune lost tracks
        for track in self.lost_stracks:
            if self.frame_id - track.frame_id > self.max_time_lost:
                track.state = TrackState.Removed
                removed_stracks.append(track)

        self.tracked_stracks = [t for t in self.tracked_stracks if t.state == TrackState.Tracked]
        self.tracked_stracks = self.joint_stracks(self.tracked_stracks, activated_stracks)
        self.tracked_stracks = self.joint_stracks(self.tracked_stracks, refind_stracks)
        self.lost_stracks = self.sub_stracks(self.lost_stracks, self.tracked_stracks)
        self.lost_stracks.extend(lost_stracks)
        self.lost_stracks = self.sub_stracks(self.lost_stracks, self.removed_stracks)
        self.removed_stracks.extend(removed_stracks)

        output_stracks = [track for track in self.tracked_stracks if track.is_activated]
        return output_stracks

    @staticmethod
    def joint_stracks(tlista: List[STrack], tlistb: List[STrack]) -> List[STrack]:
        exists = {}
        res = []
        for t in tlista:
            exists[t.track_id] = 1
            res.append(t)
        for t in tlistb:
            tid = t.track_id
            if not exists.get(tid, 0):
                exists[tid] = 1
                res.append(t)
        return res

    @staticmethod
    def sub_stracks(tlista: List[STrack], tlistb: List[STrack]) -> List[STrack]:
        stracks = {t.track_id: t for t in tlista}
        for t in tlistb:
            tid = t.track_id
            if tid in stracks:
                del stracks[tid]
        return list(stracks.values())
