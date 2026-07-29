import pytest
from fastapi.testclient import TestClient

from access_control.facial_recognition.src.api import main as api_main
from access_control.facial_recognition.src.device_signing import signed_headers, validate_cloud_url
from access_control.facial_recognition.src.sync import SQLiteEdgeDB, create_edge_app
from access_control.facial_recognition.src.config import AccessControlConfig


def test_https_is_default_transport_policy():
    validate_cloud_url("https://cloud.example.test")
    with pytest.raises(ValueError):
        validate_cloud_url("http://192.0.2.10:8000", allow_insecure_loopback=True)
    validate_cloud_url("http://127.0.0.1:8000", allow_insecure_loopback=True)


def test_signed_headers_require_device_secret():
    with pytest.raises(ValueError):
        signed_headers("", "device", "GET", "https://cloud.example.test/api/health")


def test_cloud_to_edge_control_requires_signed_one_time_request(tmp_path):
    class Worker:
        def __init__(self):
            self.calls = 0

        def perform_sync(self):
            self.calls += 1

    secret = "edge-control-secret-which-is-long-enough"
    worker = Worker()
    db = SQLiteEdgeDB(tmp_path / "device.db")
    app = create_edge_app(db, downstream_worker=worker, device_id="edge-1", device_secret=secret)
    client = TestClient(app)

    assert client.post("/api/edge/trigger-sync").status_code == 401

    url = "http://testserver/api/edge/trigger-sync"
    headers = signed_headers(secret, "edge-1", "POST", url)
    response = client.post("/api/edge/trigger-sync", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "triggered"

    replay = client.post("/api/edge/trigger-sync", headers=headers)
    assert replay.status_code == 401


def test_local_kiosk_api_remains_available_when_remote_sync_is_enabled(monkeypatch):
    config = AccessControlConfig(
        remote_api_enabled=True,
        installation_credential="",
        sync_cloud_url="http://127.0.0.1:8000",
        allow_insecure_loopback=True,
    )
    monkeypatch.setattr(api_main, "access_config", lambda: config)

    client = TestClient(api_main.app, client=("127.0.0.1", 50001))
    response = client.get("/sync/status")

    assert response.status_code == 200


def test_remote_api_still_requires_installation_credential_for_non_local_clients(monkeypatch):
    config = AccessControlConfig(
        remote_api_enabled=True,
        installation_credential="",
        sync_cloud_url="http://127.0.0.1:8000",
        allow_insecure_loopback=True,
    )
    monkeypatch.setattr(api_main, "access_config", lambda: config)

    client = TestClient(api_main.app, client=("192.168.1.20", 50001))
    response = client.get("/sync/status")

    assert response.status_code == 401
    assert response.json()["detail"] == "Installation authentication required"
