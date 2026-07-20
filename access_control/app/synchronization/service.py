"""Non-blocking cloud synchronization preserving offline chronological replay."""
from __future__ import annotations

import base64
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncConfig:
    cloud_url: str
    device_id: str
    device_name: str
    local_ip: str = "127.0.0.1"
    local_port: int = 8001
    downstream_interval: float = 30
    upstream_interval: float = 60
    heartbeat_interval: float = 30
    retry_max: float = 300


class BackgroundDatabaseSyncService:
    def __init__(self, repository, config, http=None):
        self.repository = repository
        self.config = config
        self.http = http or requests.Session()
        self._stop = threading.Event()
        self._threads = []
        self._online = False
        self._last_error = None

    def status(self):
        return "online" if self._online else "offline"

    @property
    def last_error(self):
        return self._last_error

    def start(self):
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._downstream_loop, name="access-sync-downstream", daemon=True),
            threading.Thread(target=self._upstream_loop, name="access-sync-upstream", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3)
        self._threads = []

    def _downstream_loop(self):
        self.perform_startup_cleanup()
        delay = self.config.downstream_interval
        while not self._stop.is_set():
            ok = self.perform_downstream_sync()
            delay = self.config.downstream_interval if ok else min(max(delay * 2, 1), self.config.retry_max)
            self._stop.wait(delay)

    def _upstream_loop(self):
        delay = 0
        while not self._stop.wait(delay):
            online = self.send_heartbeat()
            if online:
                self.replay_pending_authentication_logs()
                self.replay_pending_surveillance_logs()
            delay = self.config.upstream_interval if online else min(max(delay * 2, 1), self.config.retry_max)

    def perform_startup_cleanup(self):
        try:
            response = self.http.get(
                f"{self.config.cloud_url.rstrip('/')}/api/sync/downstream/user-ids",
                timeout=10.0,
            )
            if response.status_code != 200:
                return False
            cloud = {int(item) for item in response.json()}
            local = self.repository.get_local_user_ids()
            self.repository.delete_users_locally([item for item in local if item not in cloud])
            return True
        except Exception as exc:
            self._record_failure(exc)
            return False

    def perform_downstream_sync(self):
        try:
            params = {"module": "access_control"}
            last = self.repository.get_last_sync_timestamp()
            if last:
                params["last_synced_at"] = last
            response = self.http.get(
                f"{self.config.cloud_url.rstrip('/')}/api/sync/downstream/delta",
                params=params,
                timeout=10.0,
            )
            if response.status_code != 200:
                raise RuntimeError(f"downstream HTTP {response.status_code}")
            data = response.json()
            self.repository.save_roles_delta(data.get("roles", []))
            self.repository.save_users_delta(data.get("users", []))
            self.repository.save_user_roles_delta(data.get("user_roles", data.get("device_user_roles", [])))
            self.repository.save_rbac_delta(data.get("node_rbac", []))
            self.repository.delete_users_locally(data.get("deleted_user_ids", []))
            if data.get("timestamp"):
                self.repository.update_last_sync_timestamp(data["timestamp"])
            self._online = True
            self._last_error = None
            return True
        except Exception as exc:
            self._record_failure(exc)
            return False

    def send_heartbeat(self):
        payload = {
            "device_id": self.config.device_id,
            "device_name": self.config.device_name,
            "ip_address": f"{self.config.local_ip}:{self.config.local_port}",
        }
        try:
            response = self.http.post(
                f"{self.config.cloud_url.rstrip('/')}/api/sync/upstream/heartbeat",
                json=payload,
                timeout=5.0,
            )
            self._online = response.status_code == 200
            if not self._online:
                self._last_error = f"heartbeat HTTP {response.status_code}"
            return self._online
        except Exception as exc:
            self._record_failure(exc)
            return False

    def replay_pending_authentication_logs(self):
        pending = self.repository.get_unsynced_logs()
        if not pending:
            return True
        payload = []
        for log in pending:
            item = {
                key: log.get(key)
                for key in (
                    "sync_key", "user_id", "auth_status", "confidence_score", "face_count",
                    "reason", "spoofing_checked", "spoofing_passed", "timestamp", "image_path",
                )
            }
            item["device_id"] = self.config.device_id
            payload.append(item)
        return self._push_logs(
            "/api/sync/upstream/logs",
            pending,
            payload,
            self.repository.mark_logs_as_synced,
            15.0,
        )

    def replay_pending_surveillance_logs(self):
        pending = self.repository.get_unsynced_surveillance_logs()
        if not pending:
            return True
        payload = []
        for log in pending:
            image_b64, image_filename = self._read_image_payload(log.get("image_path"))
            item = {
                key: log.get(key)
                for key in (
                    "sync_key", "user_id", "recognition_status", "confidence_score",
                    "matched_template", "face_count", "bbox", "timestamp", "image_path",
                )
            }
            item.update(
                device_id=self.config.device_id,
                image_b64=image_b64,
                image_filename=image_filename,
            )
            payload.append(item)
        return self._push_logs(
            "/api/sync/upstream/surveillance-logs",
            pending,
            payload,
            self.repository.mark_surveillance_logs_as_synced,
            30.0,
        )

    def _push_logs(self, endpoint, pending, payload, mark_synced, timeout):
        try:
            response = self.http.post(
                f"{self.config.cloud_url.rstrip('/')}{endpoint}",
                json={"logs": payload},
                timeout=timeout,
            )
            if response.status_code != 200:
                raise RuntimeError(f"upstream HTTP {response.status_code}")
            indices = response.json().get("successful_indices", [])
            mark_synced([pending[index]["log_id"] for index in indices if 0 <= index < len(pending)])
            self._online = True
            self._last_error = None
            return True
        except Exception as exc:
            self._record_failure(exc)
            return False

    @staticmethod
    def _read_image_payload(image_path):
        if not image_path:
            return None, None
        path = Path(image_path).expanduser()
        if not path.is_file():
            return None, path.name
        try:
            return base64.b64encode(path.read_bytes()).decode("ascii"), path.name
        except OSError:
            return None, path.name

    def trigger_immediate_sync(self):
        return self.perform_downstream_sync()

    def deactivate_user(self, user_id):
        return self.repository.deactivate_user_instantly(user_id)

    def _record_failure(self, exc):
        self._online = False
        self._last_error = str(exc)
        logger.warning("database sync failure: %s", exc)