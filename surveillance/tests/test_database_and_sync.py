"""Unit tests for SurveillanceUserRepository and cloud sync engine components."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
import numpy as np

from surveillance.database import SurveillanceUserRepository
from surveillance.sync import _sign_request, _signed_request


class TestDatabaseAndSync(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_db.db"
        self.repo = SurveillanceUserRepository(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_apply_users_delta_and_load_templates(self):
        vec = np.ones((512,), dtype=np.float32)
        vec /= np.linalg.norm(vec)

        users_payload = [
            {
                "user_id": 42,
                "is_active": 1,
                "embeddings": [
                    {
                        "model_name": "auraface",
                        "template_name": "front",
                        "embedding": vec.tobytes(),
                    }
                ],
            }
        ]

        self.repo.apply_delta(users_payload)
        self.assertEqual(self.repo.count(), 1)

        templates = self.repo.load_templates()
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0].user_id, "42")
        self.assertEqual(templates[0].template_name, "front")

    def test_log_surveillance_event_and_sync_replay(self):
        log_id = self.repo.log_surveillance_event(
            user_id="42",
            recognition_status="RECOGNIZED",
            confidence_score=0.91,
            matched_template="front",
            face_count=1,
            bbox=[100, 100, 200, 300],
        )

        self.assertGreater(log_id, 0)
        unsynced = self.repo.get_unsynced_surveillance_logs()
        self.assertEqual(len(unsynced), 1)
        self.assertEqual(unsynced[0]["log_id"], log_id)

        self.repo.mark_surveillance_logs_as_synced([log_id])
        self.assertEqual(len(self.repo.get_unsynced_surveillance_logs()), 0)

    @patch("surveillance.sync.requests.request")
    def test_cloud_request_uses_signed_prepared_query_and_body(self, request):
        request.return_value = Mock(status_code=200)
        secret = "test-device-secret"
        payload = {"device_id": "surveillance-cam-01"}

        _signed_request(
            method="POST",
            url="https://cloud.example.test/api/sync/upstream/heartbeat",
            device_id="surveillance-cam-01",
            device_secret=secret,
            params={"module": "surveillance"},
            payload=payload,
            timeout=5.0,
        )

        _, kwargs = request.call_args
        headers = kwargs["headers"]
        body = kwargs["data"]
        parsed = urlsplit(request.call_args.args[1])
        expected = _sign_request(
            secret,
            "POST",
            parsed.path,
            parsed.query,
            headers["X-Device-Timestamp"],
            headers["X-Device-Nonce"],
            body,
        )
        self.assertEqual(headers["X-Device-ID"], "surveillance-cam-01")
        self.assertEqual(headers["X-Device-Signature"], expected)
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_cloud_request_requires_device_secret(self):
        with self.assertRaisesRegex(RuntimeError, "SURVEILLANCE_SYNC_DEVICE_SECRET"):
            _signed_request(
                method="GET",
                url="https://cloud.example.test/api/sync/downstream/delta",
                device_id="surveillance-cam-01",
                device_secret="",
                timeout=5.0,
            )


if __name__ == "__main__":
    unittest.main()
