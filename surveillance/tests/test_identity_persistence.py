"""Unit tests for identity persistence across video frames when face is no longer visible."""

import unittest
from surveillance.tracking.association import IdentityManager


class TestIdentityPersistence(unittest.TestCase):

    def test_identity_persists_when_face_is_missing_in_subsequent_frames(self):
        manager = IdentityManager()

        # Frame 1: Face recognized and bound to Track 1
        record = manager.associate_identity(
            track_id=1,
            user_id="202",
            identity="Bob",
            similarity=0.92,
            frame_id=1,
        )
        self.assertTrue(record.is_recognized)
        self.assertEqual(record.user_id, "202")

        # Frames 2 to 20: Track 1 remains active, but person's face turned away (no face detection)
        for frame_idx in range(2, 21):
            manager.update_active_tracks(active_track_ids={1}, frame_id=frame_idx)
            current_record = manager.get_identity(track_id=1)

            # Identity must be preserved cleanly over active track lifetime (Requirement 6)
            self.assertTrue(current_record.is_recognized)
            self.assertEqual(current_record.user_id, "202")
            self.assertEqual(current_record.identity, "Bob")
            self.assertFalse(manager.should_recognize(track_id=1))


if __name__ == "__main__":
    unittest.main()
