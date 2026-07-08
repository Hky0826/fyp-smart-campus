import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from edge.facial_recognition.src.api import main as api_main
from edge.facial_recognition.src.config import AccessControlConfig


class ApiSyncStatusTests(unittest.TestCase):
    def test_sync_status_uses_edge_sync_cloud_url_config(self):
        config = AccessControlConfig(
            sync_enabled=False,
            sync_cloud_url="http://cloud.example:8000",
            sync_device_id="entry-gate-test",
        )
        with patch.object(api_main, "access_config", return_value=config):
            response = TestClient(api_main.app).get("/sync/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cloud_url"], "http://cloud.example:8000")
        self.assertEqual(payload["device_id"], "entry-gate-test")
        self.assertFalse(payload["enabled"])


if __name__ == "__main__":
    unittest.main()
