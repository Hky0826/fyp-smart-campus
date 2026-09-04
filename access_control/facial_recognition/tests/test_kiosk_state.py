import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from access_control.facial_recognition.src.api.kiosk import (
    KioskStateStore,
    KioskTimingConfig,
    _try_issue_registered_token,
)
from access_control.facial_recognition.src.config import RuntimeConfig
from access_control.facial_recognition.src.face.matching import FaceTemplate, TemplateMatcher
from access_control.facial_recognition.src.face.types import AuthenticationResult
from access_control.facial_recognition.src.pipelines.access_audio import EdgeAuthToken


class KioskStateTests(unittest.TestCase):
    def test_chatbot_owner_matching_uses_pose_specific_templates(self):
        token = EdgeAuthToken(
            access_token="jwt",
            session_id=7,
            user_id=42,
            roles=("STUDENT",),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        )
        template = FaceTemplate(
            user_id="42",
            identity="42",
            template_name="left_30",
            embedding=np.array([1.0, 0.0], dtype=np.float32),
        )
        pipeline = SimpleNamespace(
            repository=SimpleNamespace(load_templates=lambda: [template]),
            matcher=TemplateMatcher(0.8),
            config=SimpleNamespace(recognition_threshold=0.8),
        )
        config = RuntimeConfig(
            sync_cloud_url="https://cloud.example",
            sync_device_id="entry-gate-01",
            sync_device_secret="device-secret",
        )

        with patch(
            "access_control.facial_recognition.src.api.kiosk.EdgeAuthTokenClient"
        ) as token_client_type:
            token_client_type.return_value.issue_token.return_value = token
            result = _try_issue_registered_token(
                pipeline,
                np.array([1.0, 0.0], dtype=np.float32),
                config,
            )

        self.assertIs(result, token)
        token_client_type.assert_called_once_with(
            "https://cloud.example",
            "entry-gate-01",
            "device-secret",
            allow_insecure_loopback=True,
        )
        token_client_type.return_value.issue_token.assert_called_once_with("42")

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
            email="owner",
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
        self.assertEqual(state.active_chat_session.email, "owner")
        self.assertEqual(state.active_chat_session.full_name, "Original Owner")
        self.assertEqual(state.active_chat_session.roles, ["STAFF"])
        self.assertEqual(len(state.active_chat_session.conversation_history), 3)
        self.assertIsNone(state.active_chat_session.owner_absent_since)

    def test_owner_presence_expires_session_after_absence_timeout(self):
        store = KioskStateStore(
            RuntimeConfig(sync_device_id="door-1", sync_device_name="Door 1"),
            timings=KioskTimingConfig(
                owner_missing_grace_seconds=1,
                owner_absent_lock_seconds=1,
                owner_absent_terminate_seconds=1,
            ),
        )
        token = EdgeAuthToken(
            access_token="secret",
            session_id=123,
            user_id=10,
            email="owner",
            roles=("STAFF",),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        )
        store.start_chat_session(token, full_name="Original Owner")

        first_missing = store.update_owner_presence(False)
        self.assertFalse(first_missing.ended)
        self.assertIsNotNone(first_missing.session)
        self.assertFalse(first_missing.session.locked)

        store._chat_session.owner_absent_since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=4)
        expired = store.update_owner_presence(False)

        self.assertTrue(expired.ended)
        self.assertIsNone(store.state("ok").active_chat_session)
        self.assertFalse(store.state("ok").chat_recoverable)

    def test_chat_live_config_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from access_control.facial_recognition.src.api.kiosk import create_kiosk_router

        config = RuntimeConfig(
            sync_cloud_url="http://127.0.0.1:8000",
            sync_device_id="ENTRY-A8F3D155",
            sync_device_secret="secret",
        )
        app = FastAPI()
        app.include_router(
            create_kiosk_router(
                runtime_config=lambda: config,
                access_pipeline=lambda: None,
                chatbot_client=lambda: None,
                sync_status=lambda: "ok",
            )
        )
        client = TestClient(app)

        # Visitor / no active session
        resp = client.get("/kiosk/chat/live-config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("ws://127.0.0.1:8000/api/chatbot/live/ws", data["ws_url"])
        self.assertEqual(data["roles"], ["VISITOR"])
        self.assertEqual(data["device_id"], "ENTRY-A8F3D155")


if __name__ == "__main__":
    unittest.main()
