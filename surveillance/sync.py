"""Cloud synchronization engine for the surveillance module."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import SETUP_MARKER_PATH, persist_runtime_configuration
from .database import SurveillanceUserRepository, generate_sync_key

logger = logging.getLogger(__name__)


def _validate_surveillance_cloud_url(url: str) -> None:
    import fnmatch
    import os

    parsed = urlsplit(url)
    host = (parsed.hostname or "").strip().lower()
    raw_allow = os.getenv("ALLOWED_CLOUD_HOSTS", "").strip()
    if raw_allow:
        patterns = [p.strip().lower() for p in raw_allow.split(",") if p.strip()]
        if not host or not any(fnmatch.fnmatch(host, pat) for pat in patterns):
            raise ValueError(f"Cloud host '{host or 'unknown'}' is not in ALLOWED_CLOUD_HOSTS")
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and os.getenv("APP_ENV", "development").lower() != "production":
        return
    raise ValueError("Cloud URL must use HTTPS in production")


def _parse_qr_pairing_payload(raw_text: str) -> tuple[str, str]:
    data = json.loads((raw_text or "").strip())
    if not isinstance(data, dict):
        raise ValueError("QR payload must be a JSON object")
    cloud_url = str(data.get("cloud_url") or "").strip().rstrip("/")
    code = str(data.get("code") or data.get("pairing_code") or "").strip()
    if not cloud_url or not code:
        raise ValueError("QR payload is missing cloud_url or pairing code")
    return cloud_url, code


def claim_surveillance_device(
    *,
    cloud_url: str = "",
    pairing_code: str = "",
    qr_payload: str = "",
    repository: SurveillanceUserRepository,
    sync_engine: Optional["SurveillanceSyncEngine"] = None,
) -> Dict[str, Any]:
    """Claim a one-time cloud pairing code for a headless/camera-only surveillance node."""
    if qr_payload:
        resolved_url, resolved_code = _parse_qr_pairing_payload(qr_payload)
    else:
        resolved_url = (cloud_url or "").strip().rstrip("/")
        resolved_code = (pairing_code or "").strip()

    if not resolved_url or not resolved_code:
        raise ValueError("Cloud URL and pairing code are required")
    _validate_surveillance_cloud_url(resolved_url)

    claim_url = f"{resolved_url}/api/infra/devices/claim"
    try:
        resp = requests.post(
            claim_url,
            json={
                "pairing_code": resolved_code,
                "device_name": sync_engine.device_name if sync_engine else "Surveillance Camera",
                "embedding_model": "arcface_r50",
                "app_version": "surveillance-1.0",
            },
            timeout=10.0,
        )
    except requests.exceptions.RequestException as exc:
        raise ValueError(f"Could not reach cloud server at {resolved_url}: {type(exc).__name__}") from exc

    if resp.status_code != 200:
        detail = ""
        try:
            detail = str(resp.json().get("detail") or "")
        except Exception:
            detail = resp.text[:200]
        raise ValueError(detail or f"Pairing failed (HTTP {resp.status_code})")

    claimed = resp.json()
    server_utc = claimed.get("server_utc_time")
    if server_utc:
        try:
            parsed = datetime.datetime.fromisoformat(str(server_utc).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            skew = abs((datetime.datetime.now(datetime.timezone.utc) - parsed).total_seconds())
            if skew > 120:
                raise ValueError(
                    f"Device clock is off by {int(skew)}s compared to cloud. Enable NTP before pairing."
                )
        except ValueError:
            raise
        except Exception:
            pass

    device_id = str(claimed["device_id"])
    device_secret = str(claimed["device_secret"])
    device_name = str(claimed.get("device_name") or (sync_engine.device_name if sync_engine else "Surveillance Camera"))

    # Verify HMAC credentials against cloud before persisting & marking complete
    verify_url = f"{resolved_url}/api/sync/downstream/user-ids"
    verify_resp = _signed_request(
        method="GET",
        url=verify_url,
        device_id=device_id,
        device_secret=device_secret,
        timeout=8.0,
    )
    if verify_resp.status_code != 200:
        raise ValueError(f"Cloud handshake verification failed (HTTP {verify_resp.status_code})")

    persist_runtime_configuration(
        cloud_url=resolved_url,
        device_id=device_id,
        device_secret=device_secret,
        device_name=device_name,
    )

    if sync_engine is not None:
        sync_engine.stop()
        sync_engine.cloud_url = resolved_url
        sync_engine.device_id = device_id
        sync_engine.device_name = device_name
        sync_engine.device_secret = device_secret
        sync_engine.start(start_server=False)
        if sync_engine.downstream is not None:
            sync_engine.downstream.perform_sync()

    marker = SETUP_MARKER_PATH.expanduser()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat(), encoding="utf-8")

    return {
        "success": True,
        "setup_complete": True,
        "device_id": device_id,
        "device_name": device_name,
        "cloud_url": resolved_url,
    }


def scan_qr_and_claim_frame(
    frame: Any,
    repository: SurveillanceUserRepository,
    sync_engine: Optional["SurveillanceSyncEngine"] = None,
) -> Optional[Dict[str, Any]]:
    """Decode a dashboard QR code from a live surveillance camera frame and claim credentials."""
    if frame is None:
        return None
    try:
        import cv2
        detector = cv2.QRCodeDetector()
        decoded, _, _ = detector.detectAndDecode(frame)
    except Exception:
        return None
    if not decoded:
        return None
    try:
        return claim_surveillance_device(
            qr_payload=decoded,
            repository=repository,
            sync_engine=sync_engine,
        )
    except ValueError as exc:
        logger.warning("QR code seen by surveillance camera could not be claimed: %s", exc)
        return None


def _sign_request(
    secret: str,
    method: str,
    path: str,
    query: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    """Create the HMAC signature expected by the cloud device-auth middleware."""
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join((method.upper(), path, query, timestamp, nonce, body_hash)).encode()
    digest = hmac.new(secret.encode(), canonical, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _signed_request(
    *,
    method: str,
    url: str,
    device_id: str,
    device_secret: str,
    params: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float,
):
    """Send one request using the same canonical bytes the cloud verifies."""
    if not device_secret:
        raise RuntimeError(
            "SURVEILLANCE_SYNC_DEVICE_SECRET is not configured; "
            "copy the one-time cloud provisioned secret into the device secret store"
        )

    body = b""
    headers: Dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"

    prepared = requests.Request(method=method, url=url, params=params, data=body, headers=headers).prepare()
    parsed = urlsplit(prepared.url)
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    headers.update(
        {
            "X-Device-ID": device_id,
            "X-Device-Timestamp": timestamp,
            "X-Device-Nonce": nonce,
            "X-Device-Signature": _sign_request(
                device_secret,
                method,
                parsed.path or "/",
                parsed.query,
                timestamp,
                nonce,
                body,
            ),
        }
    )
    return requests.request(method, prepared.url, headers=headers, data=body, timeout=timeout)


class DownstreamSyncWorker:
    """Polls cloud database for user deltas (module=surveillance) into local SQLite repository."""

    def __init__(
        self,
        repository: SurveillanceUserRepository,
        cloud_url: str,
        poll_interval_sec: int = 30,
        device_id: str = "",
        device_secret: str = "",
    ) -> None:
        self.repository = repository
        self.cloud_url = cloud_url.rstrip("/")
        self.device_id = device_id
        self.device_secret = device_secret.strip()
        self.poll_interval = poll_interval_sec
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run_loop(self) -> None:
        try:
            self.perform_startup_cleanup()
        except Exception:
            logger.exception("Error during startup cleanup in downstream worker")

        while not self._stop_event.is_set():
            try:
                self.perform_sync()
            except Exception:
                logger.exception("Sync error in background downstream loop")
            self._stop_event.wait(self.poll_interval)

    def perform_startup_cleanup(self) -> None:
        url = f"{self.cloud_url}/api/sync/downstream/user-ids"
        try:
            logger.info("Checking cloud database baseline for deleted users at startup")
            response = _signed_request(
                method="GET",
                url=url,
                device_id=self.device_id,
                device_secret=self.device_secret,
                timeout=10.0,
            )
            if response.status_code != 200:
                logger.warning("Startup cleanup skipped, cloud HTTP %s", response.status_code)
                return

            cloud_user_ids = {int(uid) for uid in response.json()}
            local_user_ids = self.repository.get_local_user_ids()
            orphaned_ids = [uid for uid in local_user_ids if uid not in cloud_user_ids]
            if orphaned_ids:
                self.repository.delete_users_locally(orphaned_ids)
                logger.info("Startup cleanup deleted %s orphaned local users", len(orphaned_ids))
        except Exception:
            logger.exception("Network failure during startup user validation")

    def perform_sync(self) -> None:
        params = {"module": "surveillance"}
        last_sync = self.repository.get_last_sync_timestamp()
        if last_sync:
            params["last_synced_at"] = last_sync

        url = f"{self.cloud_url}/api/sync/downstream/delta"
        try:
            response = _signed_request(
                method="GET",
                url=url,
                device_id=self.device_id,
                device_secret=self.device_secret,
                params=params,
                timeout=10.0,
            )
            if response.status_code != 200:
                logger.error("Cloud returned downstream sync HTTP %s", response.status_code)
                return

            data = response.json()
            self.repository.apply_delta(data.get("users", []))

            deleted_ids = data.get("deleted_user_ids", [])
            if deleted_ids:
                self.repository.delete_users_locally(deleted_ids)

            timestamp = data.get("timestamp")
            if timestamp:
                self.repository.update_last_sync_timestamp(timestamp)
        except Exception:
            logger.exception("Downstream sync network failure")


class UpstreamSyncClient:
    """Sends device heartbeats and replays unsynced surveillance logs to cloud."""

    def __init__(
        self,
        repository: SurveillanceUserRepository,
        cloud_url: str,
        device_id: str,
        device_name: str,
        local_ip: str,
        local_port: int = 8002,
        log_push_interval_sec: int = 60,
        device_secret: str = "",
    ) -> None:
        self.repository = repository
        self.cloud_url = cloud_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.local_ip = local_ip
        self.device_secret = device_secret.strip()
        self.local_port = local_port
        self.log_push_interval = log_push_interval_sec
        self.is_online = False
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._replay_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(target=self._run_heartbeat_loop, daemon=True)
        self._replay_thread = threading.Thread(target=self._run_replay_loop, daemon=True)
        self._heartbeat_thread.start()
        self._replay_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=3)
        if self._replay_thread:
            self._replay_thread.join(timeout=3)

    def _run_heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            self._check_connection_and_heartbeat()
            self._stop_event.wait(30)

    def _check_connection_and_heartbeat(self) -> None:
        url = f"{self.cloud_url}/api/sync/upstream/heartbeat"
        cached_users = None
        pending_logs = None
        last_sync_at = None
        try:
            cached_users = self.repository.count()
            pending_logs = len(self.repository.get_unsynced_surveillance_logs())
            last_sync_at = self.repository.get_last_sync_timestamp()
        except Exception:
            pass
        payload = {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "ip_address": f"{self.local_ip}:{self.local_port}",
            "app_version": "surveillance-1.0",
            "embedding_model": "arcface_r50",
            "cached_users": cached_users,
            "pending_logs": pending_logs,
            "last_sync_at": last_sync_at,
            "ws_connected": bool(getattr(self, "ws_status_fn", lambda: False)()),
            "device_utc_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        try:
            response = _signed_request(
                method="POST",
                url=url,
                device_id=self.device_id,
                device_secret=self.device_secret,
                payload=payload,
                timeout=5.0,
            )
            online = response.status_code == 200
            if online:
                try:
                    srv_time = response.json().get("server_utc_time")
                    if srv_time:
                        parsed = datetime.datetime.fromisoformat(str(srv_time).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                        skew = abs((datetime.datetime.now(datetime.timezone.utc) - parsed).total_seconds())
                        if skew > 60:
                            logger.warning("Surveillance clock skew detected (%.1fs vs cloud); check NTP", skew)
                except Exception:
                    pass
            if online and not self.is_online:
                logger.info("Cloud link restored; surveillance sync status ONLINE")
            if not online and self.is_online:
                logger.warning("Cloud heartbeat failed; surveillance sync status OFFLINE")
            self.is_online = online
        except Exception:
            if self.is_online:
                logger.warning("Cloud connection dropped; surveillance sync status OFFLINE")
            self.is_online = False

    def _run_replay_loop(self) -> None:
        while not self._stop_event.is_set():
            if self.is_online:
                try:
                    self.replay_pending_surveillance_logs()
                except Exception:
                    logger.exception("Error in surveillance log replay queue")
            self._stop_event.wait(self.log_push_interval)

    def replay_pending_surveillance_logs(self) -> None:
        pending_logs = self.repository.get_unsynced_surveillance_logs()
        if not pending_logs:
            return

        payload_logs = []
        log_id_mapping = {}
        for index, log in enumerate(pending_logs):
            image_b64, image_filename = self._read_image_payload(log.get("image_path"))
            payload_logs.append(
                {
                    "sync_key": log["sync_key"],
                    "user_id": log["user_id"],
                    "device_id": self.device_id,
                    "recognition_status": log["recognition_status"],
                    "confidence_score": log["confidence_score"],
                    "matched_template": log["matched_template"],
                    "face_count": log["face_count"],
                    "bbox": log["bbox"],
                    "timestamp": log["timestamp"],
                    "image_path": log["image_path"],
                    "image_b64": image_b64,
                    "image_filename": image_filename,
                }
            )
            log_id_mapping[index] = log["log_id"]

        url = f"{self.cloud_url}/api/sync/upstream/surveillance-logs"
        try:
            response = _signed_request(
                method="POST",
                url=url,
                device_id=self.device_id,
                device_secret=self.device_secret,
                payload={"logs": payload_logs},
                timeout=30.0,
            )
            if response.status_code != 200:
                logger.error("Cloud returned surveillance upstream sync HTTP %s", response.status_code)
                return

            result = response.json()
            successful_indices = result.get("successful_indices", [])
            synced_ids = [log_id_mapping[index] for index in successful_indices if index in log_id_mapping]
            if synced_ids:
                self.repository.mark_surveillance_logs_as_synced(synced_ids)
                logger.info("Replay sync completed for %s surveillance logs", len(synced_ids))
        except Exception:
            logger.exception("Upstream transmission timeout during surveillance log replay")

    @staticmethod
    def _read_image_payload(image_path: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if not image_path:
            return None, None
        path = Path(image_path).expanduser()
        if not path.exists() or not path.is_file():
            return None, path.name
        try:
            return base64.b64encode(path.read_bytes()).decode("ascii"), path.name
        except OSError:
            logger.exception("Failed to read snapshot %s", path)
            return None, path.name


def create_surveillance_app(
    repository: SurveillanceUserRepository,
    downstream_worker: Optional[DownstreamSyncWorker] = None,
    sync_engine: Optional["SurveillanceSyncEngine"] = None,
) -> FastAPI:
    """Create FastAPI application for surveillance daemon."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if sync_engine is not None:
            sync_engine.start(start_server=False)
        try:
            yield
        finally:
            if sync_engine is not None:
                sync_engine.stop()

    app = FastAPI(title="Surveillance Device Daemon", lifespan=lifespan if sync_engine else None)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "module": "surveillance",
            "models": ["yolox-m", "yunet", "arcface_r50"],
            "registered_templates": repository.count(),
        }

    @app.post("/api/edge/trigger-sync")
    def trigger_sync():
        worker = downstream_worker or (sync_engine.downstream if sync_engine is not None else None)
        if worker is None:
            return {"status": "skipped", "message": "No downstream worker available"}

        thread = threading.Thread(target=worker.perform_sync, daemon=True)
        thread.start()
        return {"status": "triggered", "message": "Immediate surveillance delta sync initiated"}

    return app


class SurveillanceWebSocketClient:
    """Outbound WebSocket control channel for NAT-friendly push to headless surveillance cameras."""

    def __init__(self, *, cloud_url: str, device_id: str, device_secret: str, on_trigger_sync, on_rotate_secret=None) -> None:
        self.cloud_url = cloud_url.rstrip("/")
        self.device_id = device_id
        self.device_secret = device_secret
        self._on_trigger_sync = on_trigger_sync
        self._on_rotate_secret = on_rotate_secret
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.connected = False

    def start(self) -> None:
        if not self.device_secret or not self.cloud_url or not self.device_id:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="surveillance-ws-client")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.connected = False
        if self._thread:
            self._thread.join(timeout=3)

    def _run_loop(self) -> None:
        try:
            from websockets.sync.client import connect as ws_connect
        except Exception:
            return
        backoff = 1.0
        while not self._stop_event.is_set():
            http_url = f"{self.cloud_url}/api/sync/downstream/ws"
            ws_url = ("wss://" + http_url[8:]) if http_url.startswith("https://") else ("ws://" + http_url[7:] if http_url.startswith("http://") else http_url)
            try:
                parsed = urlsplit(http_url)
                ts = str(int(time.time()))
                nonce = secrets.token_urlsafe(24)
                headers = {
                    "X-Device-ID": self.device_id,
                    "X-Device-Timestamp": ts,
                    "X-Device-Nonce": nonce,
                    "X-Device-Signature": _sign_request(self.device_secret, "GET", parsed.path or "/", parsed.query, ts, nonce, b""),
                }
                with ws_connect(ws_url, additional_headers=headers, open_timeout=8, ping_interval=20, ping_timeout=10) as ws:
                    self.connected = True
                    backoff = 1.0
                    logger.info("Surveillance WebSocket control channel connected to %s", ws_url)
                    while not self._stop_event.is_set():
                        try:
                            raw = ws.recv(timeout=25)
                        except TimeoutError:
                            ws.send(json.dumps({"type": "ping"}))
                            continue
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="ignore")
                        if not raw:
                            continue
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        if msg.get("type") in {"trigger_sync", "deactivate"}:
                            threading.Thread(target=self._on_trigger_sync, daemon=True).start()
                        elif msg.get("type") == "rotate_secret" and msg.get("device_secret") and callable(self._on_rotate_secret):
                            new_secret = str(msg["device_secret"]).strip()
                            if len(new_secret) >= 32:
                                self._on_rotate_secret(new_secret)
                                self.device_secret = new_secret
            except Exception:
                pass
            finally:
                self.connected = False
            self._stop_event.wait(backoff)
            backoff = min(backoff * 2.0, 30.0)


class SurveillanceSyncEngine:
    """Manages background sync workers and daemon API for the surveillance module."""

    def __init__(
        self,
        repository: SurveillanceUserRepository,
        cloud_url: str,
        device_id: str,
        device_name: str,
        local_ip: str,
        local_port: int = 8002,
        downstream_poll_interval_sec: int = 30,
        log_push_interval_sec: int = 60,
        enabled: bool = True,
        device_secret: str = "",
    ) -> None:
        self.repository = repository
        self.cloud_url = cloud_url
        self.device_id = device_id
        self.device_name = device_name
        self.local_ip = local_ip
        self.device_secret = device_secret
        self.local_port = local_port
        self.downstream_poll_interval_sec = downstream_poll_interval_sec
        self.log_push_interval_sec = log_push_interval_sec
        self.enabled = enabled

        self.downstream: Optional[DownstreamSyncWorker] = None
        self.upstream: Optional[UpstreamSyncClient] = None
        self.ws_client: Optional[SurveillanceWebSocketClient] = None
        self._server: Optional[uvicorn.Server] = None
        self._server_thread: Optional[threading.Thread] = None
        self._running = False

    @classmethod
    def from_config(cls, config: Any, repository: SurveillanceUserRepository) -> SurveillanceSyncEngine:
        return cls(
            repository=repository,
            cloud_url=config.sync_cloud_url,
            device_id=config.sync_device_id,
            device_name=config.sync_device_name,
            local_ip=config.sync_local_ip,
            device_secret=config.sync_device_secret,
            local_port=config.sync_local_port,
            downstream_poll_interval_sec=config.sync_downstream_poll_seconds,
            log_push_interval_sec=config.sync_log_push_interval_seconds,
            enabled=config.sync_enabled,
        )

    def start(self, start_server: bool = True) -> None:
        if not self.enabled or self._running:
            return
        if not self.device_secret or not self.cloud_url or not self.device_id:
            logger.info(
                "Surveillance device is unprovisioned; hold a dashboard QR code in front of the camera or open /setup."
            )
            return

        self.downstream = DownstreamSyncWorker(
            self.repository,
            cloud_url=self.cloud_url,
            device_id=self.device_id,
            device_secret=self.device_secret,
            poll_interval_sec=self.downstream_poll_interval_sec,
        )
        self.upstream = UpstreamSyncClient(
            self.repository,
            cloud_url=self.cloud_url,
            device_id=self.device_id,
            device_name=self.device_name,
            local_ip=self.local_ip,
            device_secret=self.device_secret,
            local_port=self.local_port,
            log_push_interval_sec=self.log_push_interval_sec,
        )

        def _apply_rotated_secret(new_secret: str) -> None:
            persist_runtime_configuration(
                cloud_url=self.cloud_url,
                device_id=self.device_id,
                device_secret=new_secret,
                device_name=self.device_name,
                local_ip=self.local_ip,
            )
            self.device_secret = new_secret
            if self.downstream:
                self.downstream.device_secret = new_secret
            if self.upstream:
                self.upstream.device_secret = new_secret
            logger.info("Applied remotely rotated surveillance secret over WebSocket for %s", self.device_id)

        self.ws_client = SurveillanceWebSocketClient(
            cloud_url=self.cloud_url,
            device_id=self.device_id,
            device_secret=self.device_secret,
            on_trigger_sync=self.downstream.perform_sync,
            on_rotate_secret=_apply_rotated_secret,
        )
        self.upstream.ws_status_fn = lambda: bool(self.ws_client and self.ws_client.connected)

        self.upstream.start()
        self.downstream.start()
        self.ws_client.start()
        if start_server:
            app = create_surveillance_app(self.repository, downstream_worker=self.downstream)
            uvicorn_config = uvicorn.Config(app, host="0.0.0.0", port=self.local_port, log_level="warning")
            self._server = uvicorn.Server(uvicorn_config)
            self._server_thread = threading.Thread(target=self._server.run, daemon=True)
            self._server_thread.start()
        self._running = True
        logger.info("Surveillance sync engine started for device %s", self.device_id)

    @property
    def ws_connected(self) -> bool:
        return bool(self.ws_client and self.ws_client.connected)

    def stop(self) -> None:
        if not self._running:
            return
        if self.ws_client:
            self.ws_client.stop()
        if self.upstream:
            self.upstream.stop()
        if self.downstream:
            self.downstream.stop()
        if self._server:
            self._server.should_exit = True
        if self._server_thread:
            self._server_thread.join(timeout=3)
        self._running = False
        logger.info("Surveillance sync engine stopped")
