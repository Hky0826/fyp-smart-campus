"""Surveillance FastAPI service daemon with headless & camera-QR provisioning."""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .config import SurveillanceConfig, clear_runtime_configuration
from .database import SurveillanceUserRepository
from .sync import SurveillanceSyncEngine, claim_surveillance_device, create_surveillance_app

config = SurveillanceConfig()
repository = SurveillanceUserRepository(config.database_path)

sync_engine = SurveillanceSyncEngine.from_config(config, repository)
app = create_surveillance_app(repository, sync_engine=sync_engine)


class SurveillanceClaimRequest(BaseModel):
    cloud_url: Optional[str] = Field(default=None, max_length=500)
    pairing_code: Optional[str] = Field(default=None, max_length=64)
    qr_payload: Optional[str] = Field(default=None, max_length=2000)


class SurveillanceResetRequest(BaseModel):
    admin_pin: str = ""


@app.get("/")
def root():
    return {
        "service": "Surveillance Service Daemon",
        "models": {
            "person_detector": "YOLOX-M",
            "face_detector": "YuNet",
            "face_embedder": "AuraFace",
            "tracker": "ByteTrack",
        },
        "status": "running",
        "provisioned": bool(sync_engine.device_secret and sync_engine.cloud_url),
        "device_id": sync_engine.device_id,
    }


@app.get("/setup/status")
def setup_status():
    provisioned = bool(sync_engine.device_secret and sync_engine.cloud_url and sync_engine.device_id)
    return {
        "success": True,
        "setup_complete": provisioned,
        "first_time_setup": not provisioned,
        "device_id": sync_engine.device_id,
        "device_name": sync_engine.device_name,
        "cloud_url": sync_engine.cloud_url,
        "registered_templates": repository.count(),
        "ws_connected": bool(getattr(sync_engine, "ws_connected", False)),
    }


@app.post("/setup/claim")
def setup_claim(payload: SurveillanceClaimRequest):
    if sync_engine.device_secret and sync_engine.cloud_url and sync_engine.device_id:
        raise HTTPException(status_code=409, detail="Surveillance device is already provisioned; reset first to re-pair.")
    try:
        result = claim_surveillance_device(
            cloud_url=payload.cloud_url or "",
            pairing_code=payload.pairing_code or "",
            qr_payload=payload.qr_payload or "",
            repository=repository,
            sync_engine=sync_engine,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.post("/setup/reset")
def setup_reset(payload: SurveillanceResetRequest):
    expected_pin = os.getenv("SURVEILLANCE_ADMIN_PIN", "").strip()
    is_prod = os.getenv("APP_ENV", "development").lower() == "production"
    if is_prod and not expected_pin:
        raise HTTPException(status_code=403, detail="SURVEILLANCE_ADMIN_PIN must be configured in production to reset this device")
    if expected_pin and not hmac.compare_digest(payload.admin_pin.strip(), expected_pin):
        raise HTTPException(status_code=403, detail="Invalid administrator PIN")
    sync_engine.stop()
    clear_runtime_configuration()
    sync_engine.cloud_url = ""
    sync_engine.device_id = ""
    sync_engine.device_secret = ""
    return {"success": True, "setup_complete": False, "first_time_setup": True}


@app.get("/setup", response_class=HTMLResponse)
def setup_page():
    """Lightweight headless web UI for pairing ceiling-mounted / screenless surveillance cameras."""
    return HTMLResponse(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Surveillance Camera Setup</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; display: flex; justify-content: center; }
    .card { width: 100%; max-width: 440px; background: #1e293b; border: 1px solid #334155; border-radius: 16px; padding: 24px; }
    h1 { font-size: 20px; margin: 0 0 8px; }
    p { font-size: 13px; color: #94a3b8; margin: 0 0 16px; }
    label { display: block; font-size: 12px; font-weight: 600; color: #cbd5e1; margin: 12px 0 4px; }
    input { width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: #f8fafc; font-family: monospace; }
    button { width: 100%; margin-top: 16px; padding: 12px; border: 0; border-radius: 10px; background: #6366f1; color: #fff; font-weight: 700; cursor: pointer; }
    button.danger { background: #dc2626; }
    .msg { margin-top: 12px; font-size: 13px; }
    .ok { color: #34d399; }
    .err { color: #f87171; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Surveillance Camera Setup</h1>
    <p id="subtitle">Hold the dashboard QR code in front of the camera, or enter the 8-character pairing code below.</p>
    <div id="pair-form">
      <label>Cloud Dashboard URL</label>
      <input id="cloud_url" placeholder="https://your-cloud-dashboard" />
      <label>8-Character Pairing Code</label>
      <input id="pairing_code" placeholder="K9X4-M2P8" />
      <button onclick="claimDevice()">Pair &amp; Verify</button>
    </div>
    <div id="paired-box" style="display:none;">
      <p class="ok" id="paired-info"></p>
      <label>Admin PIN (if configured)</label>
      <input id="admin_pin" type="password" placeholder="Optional PIN" />
      <button class="danger" onclick="resetDevice()">Re-Pair / Reset Device</button>
    </div>
    <div class="msg" id="msg"></div>
  </div>
  <script>
    async function loadStatus() {
      const r = await fetch('/setup/status');
      const d = await r.json();
      if (d.setup_complete) {
        document.getElementById('pair-form').style.display = 'none';
        document.getElementById('paired-box').style.display = 'block';
        document.getElementById('paired-info').textContent = 'Paired as ' + d.device_id + ' (' + d.cloud_url + ') — ' + d.registered_templates + ' cached templates.';
      } else {
        document.getElementById('pair-form').style.display = 'block';
        document.getElementById('paired-box').style.display = 'none';
      }
    }
    async function claimDevice() {
      const msg = document.getElementById('msg');
      msg.className = 'msg';
      msg.textContent = 'Claiming credentials and verifying cloud sync...';
      const r = await fetch('/setup/claim', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          cloud_url: document.getElementById('cloud_url').value,
          pairing_code: document.getElementById('pairing_code').value
        })
      });
      const d = await r.json();
      if (!r.ok) { msg.className = 'msg err'; msg.textContent = d.detail || 'Pairing failed'; return; }
      msg.className = 'msg ok'; msg.textContent = 'Paired and synced as ' + d.device_id;
      loadStatus();
    }
    async function resetDevice() {
      const msg = document.getElementById('msg');
      const r = await fetch('/setup/reset', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ admin_pin: document.getElementById('admin_pin').value })
      });
      const d = await r.json();
      if (!r.ok) { msg.className = 'msg err'; msg.textContent = d.detail || 'Reset failed'; return; }
      msg.className = 'msg ok'; msg.textContent = 'Credentials cleared. Ready to pair.';
      loadStatus();
    }
    loadStatus();
  </script>
</body>
</html>"""
    )
