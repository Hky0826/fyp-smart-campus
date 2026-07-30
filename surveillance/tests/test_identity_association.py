"""Unit tests for track-to-identity association."""

import unittest
from surveillance.tracking.association import IdentityManager, TrackIdentity


class TestIdentityAssociation(unittest.TestCase):

    def setUp(self):
        self.manager = IdentityManager()

    def test_initial_track_identity_is_unknown(self):
        record = self.manager.get_identity(track_id=1)
        self.assertEqual(record.track_id, 1)
        self.assertFalse(record.is_recognized)
        self.assertEqual(record.identity, "unknown")
        self.assertIsNone(record.user_id)

    def test_associate_recognized_identity(self):
        record = self.manager.associate_identity(
            track_id=1,
            user_id="101",
            identity="Alice",
            similarity=0.88,
            matched_template="front",
            frame_id=5,
        )

        self.assertTrue(record.is_recognized)
        self.assertEqual(record.user_id, "101")
        self.assertEqual(record.identity, "Alice")
        self.assertAlmostEqual(record.similarity, 0.88)
        self.assertEqual(record.first_recognized_frame, 5)

    def test_should_recognize_flag(self):
        # Track 1 has not been recognized yet -> should run recognition
        self.assertTrue(self.manager.should_recognize(track_id=1))

        # Perform association
        self.manager.associate_identity(track_id=1, user_id="101", identity="Alice", similarity=0.85)

        # Track 1 is now recognized -> should NOT run recognition again (Requirement 8)
        self.assertFalse(self.manager.should_recognize(track_id=1))


if __name__ == "__main__":
    unittest.main()
