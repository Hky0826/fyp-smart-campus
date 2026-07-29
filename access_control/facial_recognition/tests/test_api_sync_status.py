import unittest
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from access_control.facial_recognition.src.api import main as api_main
from access_control.facial_recognition.src.config import AccessControlConfig
from access_control.facial_recognition.src import sync as sync_module


class ApiSyncStatusTests(unittest.TestCase):
    def test_sync_status_uses_edge_sync_cloud_url_config(self):
        config = AccessControlConfig(
            sync_enabled=False,
            sync_cloud_url="http://cloud.example:8000",
            sync_device_id="entry-gate-test",
            remote_api_enabled=False,
        )
        with patch.object(api_main, "access_config", return_value=config):
            response = TestClient(api_main.app).get("/sync/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cloud_url"], "http://cloud.example:8000")
        self.assertEqual(payload["device_id"], "entry-gate-test")
        self.assertFalse(payload["enabled"])

    def test_heartbeat_signs_the_exact_body_that_is_sent(self):
        captured = {}

        class Response:
            status_code = 200

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return Response()

        db = sync_module.SQLiteEdgeDB(":memory:")
        client = sync_module.UpstreamSyncClient(
            db,
            cloud_url="http://127.0.0.1:8000",
            device_id="edge-1",
            device_name="Test Edge",
            local_ip="192.168.1.50",
            local_port=8001,
            device_secret="secret",
            allow_insecure_loopback=True,
        )

        with patch.object(sync_module.requests, "post", side_effect=fake_post), patch.object(
            sync_module, "signed_headers", return_value={}
        ):
            client._check_connection_and_heartbeat()

        payload = {
            "device_id": "edge-1",
            "device_name": "Test Edge",
            "ip_address": "192.168.1.50:8001",
        }
        expected_body = json.dumps(payload, separators=(",", ":")).encode()
        self.assertEqual(captured["data"], expected_body)
        self.assertNotIn("json", captured)


if __name__ == "__main__":
    unittest.main()
