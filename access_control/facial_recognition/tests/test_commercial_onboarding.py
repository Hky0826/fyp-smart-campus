"""Tests for commercial onboarding (QR/pairing code, clock-skew guard, reset, WebSocket push)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from access_control.facial_recognition.src.api import main as edge_api
from access_control.facial_recognition.src.config import AccessControlConfig
from surveillance import config as surv_config
from surveillance import sync as surv_sync


def _make_qr_frame(text: str) -> np.ndarray:
    encoder = cv2.QRCodeEncoder_create()
    matrix = encoder.encode(text)
    big = cv2.resize(matrix, (240, 240), interpolation=cv2.INTER_NEAREST)
    padded = cv2.copyMakeBorder(big, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR)


def test_parse_qr_pairing_payload_and_clock_skew():
    url, code = edge_api._parse_qr_pairing_payload(
        json.dumps({"cloud_url": "https://cloud.example.com/", "code": "K9X4-M2P8"})
    )
    assert url == "https://cloud.example.com"
    assert code == "K9X4-M2P8"

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    assert edge_api._check_clock_skew(now_iso) < 5.0

    skewed_iso = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)).isoformat()
    assert edge_api._check_clock_skew(skewed_iso) > 500.0


def test_access_control_claim_rejects_excessive_clock_skew(monkeypatch, tmp_path: Path):
    cfg = AccessControlConfig(
        database_path=tmp_path / "device_local.db",
        sync_cloud_url="http://127.0.0.1:8000",
        allow_insecure_loopback=True,
    )
    monkeypatch.setattr(edge_api, "access_config", lambda: cfg)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "device_id": "KIOSK-TEST0001",
        "device_secret": "s" * 48,
        "server_utc_time": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)).isoformat(),
    }
    monkeypatch.setattr(edge_api.requests, "post", lambda *a, **kw: fake_resp)

    with pytest.raises(HTTPException) as exc_info:
        edge_api.claim_setup(
            edge_api.SetupClaimRequest(cloud_url="http://127.0.0.1:8000", pairing_code="K9X4-M2P8")
        )
    assert exc_info.value.status_code == 400
    assert "NTP" in exc_info.value.detail


def test_access_control_reset_clears_marker_and_respects_pin(monkeypatch, tmp_path: Path):
    runtime_cfg = tmp_path / "runtime.env"
    runtime_cfg.write_text("EDGE_SYNC_DEVICE_SECRET=secret\n", encoding="utf-8")

    cfg = AccessControlConfig(
        database_path=tmp_path / "device_local.db",
        sync_device_secret="secret" * 8,
    )
    marker = cfg.setup_marker_path
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("2026-11-25T00:00:00Z", encoding="utf-8")
    monkeypatch.setattr(edge_api, "access_config", lambda: cfg)
    monkeypatch.setattr(edge_api.access_config, "cache_clear", lambda: None, raising=False)
    monkeypatch.setattr(edge_api.runtime_config, "cache_clear", lambda: None, raising=False)
    monkeypatch.setattr(edge_api._chatbot_client, "cache_clear", lambda: None, raising=False)
    monkeypatch.setattr(edge_api, "clear_runtime_configuration", lambda: runtime_cfg.unlink(missing_ok=True))
    monkeypatch.setenv("EDGE_ADMIN_PIN", "2468")

    with pytest.raises(HTTPException) as bad_pin:
        edge_api.reset_setup(edge_api.SetupResetRequest(admin_pin="0000"))
    assert bad_pin.value.status_code == 403
    assert marker.exists()

    res = edge_api.reset_setup(edge_api.SetupResetRequest(admin_pin="2468"))
    assert res["first_time_setup"] is True
    assert not marker.exists()
    assert not runtime_cfg.exists()


def test_surveillance_camera_qr_scan_and_claim(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(surv_config, "RUNTIME_CONFIG_PATH", tmp_path / "surv.env")
    monkeypatch.setattr(surv_config, "SETUP_MARKER_PATH", tmp_path / "surv.provisioned")
    monkeypatch.setattr(surv_sync, "SETUP_MARKER_PATH", tmp_path / "surv.provisioned")

    fake_claim = MagicMock()
    fake_claim.status_code = 200
    fake_claim.json.return_value = {
        "device_id": "EDGE-SURV01",
        "device_name": "Lobby Cam",
        "device_secret": "x" * 48,
        "server_utc_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    monkeypatch.setattr(surv_sync.requests, "post", lambda *a, **kw: fake_claim)

    fake_verify = MagicMock()
    fake_verify.status_code = 200
    monkeypatch.setattr(surv_sync, "_signed_request", lambda **kw: fake_verify)

    qr_text = json.dumps({"cloud_url": "http://127.0.0.1:8000", "code": "ABCD-2345"})
    frame = _make_qr_frame(qr_text)

    fake_repo = MagicMock()
    result = surv_sync.scan_qr_and_claim_frame(frame, fake_repo, sync_engine=None)
    assert result is not None
    assert result["success"] is True
    assert result["device_id"] == "EDGE-SURV01"
    assert (tmp_path / "surv.env").is_file()
    assert (tmp_path / "surv.provisioned").is_file()


def test_surveillance_config_has_no_hardcoded_dev_secret(monkeypatch):
    monkeypatch.delenv("SURVEILLANCE_SYNC_DEVICE_SECRET", raising=False)
    monkeypatch.delenv("SURVEILLANCE_SYNC_DEVICE_ID", raising=False)
    monkeypatch.delenv("SURVEILLANCE_SYNC_CLOUD_URL", raising=False)
    monkeypatch.delenv("EDGE_SYNC_CLOUD_URL", raising=False)

    cfg = surv_config.SurveillanceConfig()
    assert cfg.sync_device_secret == ""
    assert cfg.sync_device_id == ""
    assert cfg.sync_cloud_url == ""


def test_allowed_cloud_hosts_blocks_untrusted_domains(monkeypatch):
    from access_control.facial_recognition.src.device_signing import validate_cloud_url

    monkeypatch.setenv("ALLOWED_CLOUD_HOSTS", "cloud.company.com,*.trusted.internal")
    validate_cloud_url("https://cloud.company.com")
    validate_cloud_url("https://eu1.trusted.internal")

    with pytest.raises(ValueError, match="ALLOWED_CLOUD_HOSTS"):
        validate_cloud_url("https://evil-attacker.com")

    with pytest.raises(ValueError, match="ALLOWED_CLOUD_HOSTS"):
        surv_sync._validate_surveillance_cloud_url("https://evil-attacker.com")


def test_production_reset_requires_configured_admin_pin(monkeypatch, tmp_path: Path):
    cfg = AccessControlConfig(database_path=tmp_path / "device_local.db", sync_device_secret="secret" * 8)
    monkeypatch.setattr(edge_api, "access_config", lambda: cfg)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EDGE_ADMIN_PIN", raising=False)

    with pytest.raises(HTTPException) as exc:
        edge_api.reset_setup(edge_api.SetupResetRequest(admin_pin=""))
    assert exc.value.status_code == 403
    assert "EDGE_ADMIN_PIN" in exc.value.detail


def test_ws_rotate_secret_handler_and_outbox_pruning(tmp_path: Path):
    from access_control.facial_recognition.src.sync import EdgeWebSocketClient, SQLiteEdgeDB

    rotated: list[str] = []
    client = EdgeWebSocketClient(
        cloud_url="https://cloud.example.com",
        device_id="KIOSK-1",
        device_secret="a" * 40,
        on_deactivate=lambda _uid: None,
        on_trigger_sync=lambda: None,
        on_rotate_secret=lambda s: rotated.append(s),
    )
    new_sec = "b" * 48
    client._handle_message(json.dumps({"type": "rotate_secret", "device_secret": new_sec}))
    assert rotated == [new_sec]
    assert client.device_secret == new_sec

    db = SQLiteEdgeDB(tmp_path / "outbox.db")
    for idx in range(10):
        db.log_authentication_event(
            user_id=None,
            auth_status="FAILED",
            confidence_score=0.1,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
    pruned = db.prune_offline_outbox(max_rows=4)
    assert pruned == 6
    assert len(db.get_unsynced_logs()) == 4


def test_remote_access_config_override_and_ws_push(monkeypatch, tmp_path: Path):
    from access_control.facial_recognition.src import config as ac_config
    from access_control.facial_recognition.src.sync import EdgeWebSocketClient

    override_file = tmp_path / "access_config_overrides.json"
    monkeypatch.setattr(ac_config, "ACCESS_CONFIG_OVERRIDES_PATH", override_file)

    reloaded: list[dict] = []
    client = EdgeWebSocketClient(
        cloud_url="https://cloud.example.com",
        device_id="KIOSK-1",
        device_secret="a" * 40,
        on_deactivate=lambda _uid: None,
        on_trigger_sync=lambda: None,
    )
    client._on_config_update = lambda cfg: reloaded.append(cfg)
    client._handle_message(
        json.dumps({
            "type": "config_update",
            "access_config": {
                "recognition_threshold": 0.45,
                "pad_threshold": 0.82,
                "door_unlock_duration_seconds": 7.5,
                "ignored_unknown_key": 123,
            },
        })
    )

    assert len(reloaded) == 1
    assert reloaded[0]["recognition_threshold"] == 0.45
    assert "ignored_unknown_key" not in reloaded[0]
    loaded = ac_config.load_access_config_overrides()
    assert loaded["recognition_threshold"] == 0.45
    assert loaded["pad_threshold"] == 0.82
    assert loaded["door_unlock_duration_seconds"] == 7.5
