"""Unit tests for track loss, track expiration, and cleanup of identity records."""

import unittest
from surveillance.tracking.association import IdentityManager


class TestTrackExpiration(unittest.TestCase):

    def test_identity_cleanup_upon_track_expiration(self):
        manager = IdentityManager()

        # Bind identity to Track 1 and Track 2
        manager.associate_identity(track_id=1, user_id="101", identity="Alice", similarity=0.85)
        manager.associate_identity(track_id=2, user_id="102", identity="Bob", similarity=0.90)

        self.assertTrue(manager.get_identity(1).is_recognized)
        self.assertTrue(manager.get_identity(2).is_recognized)

        # Track 2 leaves the scene / expires in ByteTrack -> active_track_ids now only contains {1}
        manager.update_active_tracks(active_track_ids={1}, frame_id=50)

        # Track 1 identity remains active
        self.assertTrue(manager.get_identity(1).is_recognized)

        # Track 2 identity binding must be cleaned up / reset (Requirement 7)
        expired_record = manager.get_identity(2)
        self.assertFalse(expired_record.is_recognized)
        self.assertEqual(expired_record.identity, "unknown")
        self.assertIsNone(expired_record.user_id)


if __name__ == "__main__":
    unittest.main()
