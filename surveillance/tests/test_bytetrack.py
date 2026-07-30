"""Unit tests for ByteTrack multi-object tracking."""

import unittest
import numpy as np
from surveillance.tracking.bytetrack import ByteTracker, STrack, TrackState


class TestByteTrack(unittest.TestCase):

    def setUp(self):
        STrack.reset_id_counter()

    def test_strack_activation_and_id_assignment(self):
        tracker = ByteTracker()
        detections = [np.array([100, 100, 200, 300, 0.9], dtype=np.float32)]
        tracks = tracker.update(detections)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].track_id, 1)
        self.assertEqual(tracks[0].state, TrackState.Tracked)

    def test_track_persistence_across_consecutive_frames(self):
        tracker = ByteTracker()
        # Frame 1: Detection at (100, 100, 200, 300)
        tracks_f1 = tracker.update([np.array([100, 100, 200, 300, 0.9], dtype=np.float32)])
        track_id_f1 = tracks_f1[0].track_id

        # Frame 2: Person moved slightly to (105, 102, 205, 302)
        tracks_f2 = tracker.update([np.array([105, 102, 205, 302, 0.88], dtype=np.float32)])

        self.assertEqual(len(tracks_f2), 1)
        self.assertEqual(tracks_f2[0].track_id, track_id_f1)

    def test_multiple_tracks_assignment(self):
        tracker = ByteTracker()
        dets = [
            np.array([50, 50, 100, 150, 0.9], dtype=np.float32),
            np.array([300, 300, 400, 500, 0.85], dtype=np.float32),
        ]
        tracks = tracker.update(dets)

        self.assertEqual(len(tracks), 2)
        track_ids = {t.track_id for t in tracks}
        self.assertEqual(track_ids, {1, 2})


if __name__ == "__main__":
    unittest.main()
