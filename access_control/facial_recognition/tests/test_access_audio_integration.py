import datetime as dt
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from access_control.audio_io.cloud_audio_client import CloudAudioClient, CloudChatCredentials
    from access_control.audio_io.config import _cloud_audio_stream_url, _cloud_audio_url
except ImportError:
    from edge.audio_io.cloud_audio_client import CloudAudioClient, CloudChatCredentials
    from edge.audio_io.config import _cloud_audio_stream_url, _cloud_audio_url
from access_control.facial_recognition.src.config import AccessControlConfig
from access_control.facial_recognition.src.pipelines.access_audio import (
    AccessControlAudioCoordinator,
    EdgeAuthToken,
    EdgeAuthTokenClient,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class AccessAudioIntegrationTests(unittest.TestCase):
    def test_audio_cloud_url_defaults_to_edge_sync_cloud_url(self):
        with patch.dict("os.environ", {"EDGE_SYNC_CLOUD_URL": "http://cloud.example:8000"}, clear=True):
            self.assertEqual(_cloud_audio_url(), "http://cloud.example:8000/api/chatbot/chat/audio")
            self.assertEqual(
                _cloud_audio_stream_url(),
                "http://cloud.example:8000/api/chatbot/chat/audio/stream",
            )

    def test_cloud_audio_client_prefers_runtime_credentials(self):
        client = CloudAudioClient(
            credential_provider=lambda: CloudChatCredentials(bearer_token="runtime-token", session_id=12)
        )

        credentials = client._credentials()

        self.assertEqual(credentials.bearer_token, "runtime-token")
        self.assertEqual(credentials.session_id, 12)

    def test_edge_auth_token_client_posts_to_cloud_endpoint(self):
        payload = {
            "access_token": "jwt-value",
            "user_id": 7,
            "email": "user7",
            "roles": ["STUDENT"],
            "session_id": 99,
            "expires_at": "2026-06-24T12:00:00",
        }
        with patch(
            "access_control.facial_recognition.src.pipelines.access_audio.requests.post",
            side_effect=[
                FakeResponse(payload={"challenge_id": "challenge-1"}),
                FakeResponse(payload=payload),
            ],
        ) as post:
            token = EdgeAuthTokenClient(
                "https://cloud.example:8000",
                "entry-gate-01",
                "device-secret-for-tests",
            ).issue_token(7)

        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].args[0], "https://cloud.example:8000/api/edge-auth/challenge")
        self.assertEqual(post.call_args_list[1].args[0], "https://cloud.example:8000/api/edge-auth/token")
        for call in post.call_args_list:
            self.assertIn("X-Device-Signature", call.kwargs["headers"])
            self.assertEqual(call.kwargs["headers"]["Content-Type"], "application/json")
            self.assertIsInstance(call.kwargs["data"], bytes)
        self.assertEqual(token.access_token, "jwt-value")
        self.assertEqual(token.session_id, 99)
        self.assertEqual(token.roles, ("STUDENT",))

    def test_coordinator_finds_local_visitor_and_returns_credentials(self):
        db_path = Path(__file__).with_name("_visitor_test.db")
        db_path.unlink(missing_ok=True)
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                conn.executescript(
                    """
                    CREATE TABLE device_users (user_id INTEGER PRIMARY KEY, is_active INTEGER NOT NULL);
                    CREATE TABLE device_roles (role_id INTEGER PRIMARY KEY, role_name TEXT NOT NULL);
                    CREATE TABLE device_user_roles (user_id INTEGER NOT NULL, role_id INTEGER NOT NULL);
                    INSERT INTO device_users (user_id, is_active) VALUES (5, 1);
                    INSERT INTO device_roles (role_id, role_name) VALUES (2, 'VISITOR');
                    INSERT INTO device_user_roles (user_id, role_id) VALUES (5, 2);
                    """
                )
                conn.commit()
            finally:
                conn.close()

            config = AccessControlConfig(database_path=db_path, allow_insecure_loopback=True)
            coordinator = AccessControlAudioCoordinator(config)

            self.assertEqual(coordinator._find_local_visitor_user_id(), 5)

            token = EdgeAuthToken(
                access_token="visitor-token",
                session_id=3,
                user_id=5,
                roles=("VISITOR",),
                expires_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(minutes=10),
            )
            coordinator._visitor_token = token

            self.assertEqual(
                coordinator.credential_provider(),
                {"bearer_token": "visitor-token", "session_id": 3},
            )
        finally:
            db_path.unlink(missing_ok=True)

    def test_coordinator_throttles_repeated_token_attempts(self):
        coordinator = AccessControlAudioCoordinator(
            AccessControlConfig(audio_token_retry_seconds=30, allow_insecure_loopback=True)
        )

        self.assertTrue(coordinator._should_attempt_authenticated_token(7))
        self.assertFalse(coordinator._should_attempt_authenticated_token(7))


if __name__ == "__main__":
    unittest.main()
