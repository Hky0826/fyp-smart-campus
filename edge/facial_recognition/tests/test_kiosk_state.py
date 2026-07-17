import datetime as dt
import unittest

from edge.facial_recognition.src.api.kiosk import KioskStateStore, KioskTimingConfig
from edge.facial_recognition.src.config import RuntimeConfig
from edge.facial_recognition.src.face.types import AuthenticationResult
from edge.facial_recognition.src.pipelines.access_audio import EdgeAuthToken


class KioskStateTests(unittest.TestCase):
    def test_retry_access_result_keeps_attempt_verifying(self):
        store = KioskStateStore(RuntimeConfig(sync_device_id="door-1", sync_device_name="Door 1"))

        store.start_access_attempt()
        attempt = store.complete_access_attempt(
            {
                "access_granted": False,
                "authentication_result": AuthenticationResult.RETRY_INSUFFICIENT_SAMPLES.value,
                "reason": "Candidate identity is not consistent across frames",
                "face_count": 1,
                "sample_count": 4,
            }
        )

        self.assertEqual(attempt.access_decision, "VERIFYING")
        self.assertIsNone(attempt.completed_at)
        self.assertEqual(attempt.reason, "Candidate identity is not consistent across frames")

    def test_different_access_user_does_not_lock_chat_session_before_absence_timeout(self):
        store = KioskStateStore(RuntimeConfig(sync_device_id="door-1", sync_device_name="Door 1"))
        token = EdgeAuthToken(
            access_token="secret",
            session_id=123,
            user_id=10,
            username="owner",
            roles=("STAFF",),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        )
        store.start_chat_session(token, full_name="Original Owner")
        store.append_chat_exchange("Where is the lab?", "Second floor.", [])

        store.start_access_attempt()
        store.complete_access_attempt(
            {
                "access_granted": True,
                "user_id": 20,
                "similarity": 0.91,
                "face_count": 1,
            }
        )

        state = store.state("ok")

        self.assertIsNotNone(state.active_chat_session)
        self.assertFalse(state.active_chat_session.locked)
        self.assertEqual(state.active_chat_session.presence_state, "OWNER_PRESENT")
        self.assertEqual(state.active_chat_session.username, "owner")
        self.assertEqual(state.active_chat_session.full_name, "Original Owner")
        self.assertEqual(state.active_chat_session.roles, ["STAFF"])
        self.assertEqual(len(state.active_chat_session.conversation_history), 3)
        self.assertIsNone(state.active_chat_session.owner_absent_since)

    def test_owner_presence_expires_session_after_absence_timeout(self):
        store = KioskStateStore(
            RuntimeConfig(sync_device_id="door-1", sync_device_name="Door 1"),
            timings=KioskTimingConfig(owner_absent_terminate_seconds=1),
        )
        token = EdgeAuthToken(
            access_token="secret",
            session_id=123,
            user_id=10,
            username="owner",
            roles=("STAFF",),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        )
        store.start_chat_session(token, full_name="Original Owner")

        first_missing = store.update_owner_presence(False)
        self.assertFalse(first_missing.ended)
        self.assertIsNotNone(first_missing.session)
        self.assertFalse(first_missing.session.locked)

        store._chat_session.owner_absent_since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=2)
        expired = store.update_owner_presence(False)

        self.assertTrue(expired.ended)
        self.assertIsNone(store.state("ok").active_chat_session)
        self.assertFalse(store.state("ok").chat_recoverable)


if __name__ == "__main__":
    unittest.main()
