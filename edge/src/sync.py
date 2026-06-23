"""Cloud synchronization engine for the Hailo edge pipelines."""

from __future__ import annotations

import base64
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


logger = logging.getLogger(__name__)


class SQLiteEdgeDB:
    """SQLite storage used by downstream and upstream synchronization."""

    def __init__(self, db_path: str | Path = "device_local.db") -> None:
        self.db_path = Path(db_path)
        self.lock = threading.Lock()
        self.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def initialize_schema(self) -> None:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_users (
                        user_id INTEGER PRIMARY KEY NOT NULL,
                        face_vector BLOB NOT NULL,
                        is_active INTEGER DEFAULT 1 NOT NULL,
                        last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_roles (
                        role_id INTEGER PRIMARY KEY NOT NULL,
                        role_name TEXT NOT NULL,
                        last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_user_roles (
                        user_id INTEGER NOT NULL,
                        role_id INTEGER NOT NULL,
                        last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (user_id, role_id),
                        FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_auth_logs (
                        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        auth_status TEXT NOT NULL,
                        confidence_score REAL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        sync_status INTEGER DEFAULT 0 NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE SET NULL
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_info (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL,
                        device_name TEXT NOT NULL,
                        node_id INTEGER NOT NULL,
                        location_name TEXT NOT NULL,
                        last_cloud_sync DATETIME
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_node_rbac (
                        node_id INTEGER NOT NULL,
                        role_id INTEGER NOT NULL,
                        last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (node_id, role_id)
                    );
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sync_metadata (
                        key TEXT PRIMARY KEY,
                        val TEXT
                    );
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_logs_sync ON device_auth_logs(sync_status);")
                conn.commit()
                logger.info("SQLite sync schema initialized at %s", self.db_path)
            except Exception:
                conn.rollback()
                logger.exception("Error initializing SQLite sync schema")
                raise
            finally:
                conn.close()

    def save_users_delta(self, users: List[Dict[str, Any]]) -> None:
        if not users:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                for user in users:
                    user_id = user["user_id"]
                    is_active = int(user.get("is_active", 1))
                    face_vector_b64 = user.get("face_vector_b64")

                    if face_vector_b64:
                        face_bytes = base64.b64decode(face_vector_b64)
                        cursor.execute(
                            """
                            INSERT INTO device_users (user_id, face_vector, is_active, last_synced_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_id) DO UPDATE SET
                                face_vector=excluded.face_vector,
                                is_active=excluded.is_active,
                                last_synced_at=CURRENT_TIMESTAMP
                            """,
                            (user_id, face_bytes, is_active),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO device_users (user_id, face_vector, is_active, last_synced_at)
                            VALUES (?, x'', ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_id) DO UPDATE SET
                                is_active=excluded.is_active,
                                last_synced_at=CURRENT_TIMESTAMP
                            """,
                            (user_id, is_active),
                        )
                conn.commit()
                logger.info("Processed delta update for %s users", len(users))
            except Exception:
                conn.rollback()
                logger.exception("Failed to commit users delta")
                raise
            finally:
                conn.close()

    def save_roles_delta(self, roles: List[Dict[str, Any]]) -> None:
        if not roles:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                for role in roles:
                    cursor.execute(
                        """
                        INSERT INTO device_roles (role_id, role_name, last_synced_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(role_id) DO UPDATE SET
                            role_name=excluded.role_name,
                            last_synced_at=CURRENT_TIMESTAMP
                        """,
                        (role["role_id"], role["role_name"]),
                    )
                conn.commit()
                logger.info("Processed delta update for %s roles", len(roles))
            except Exception:
                conn.rollback()
                logger.exception("Failed to commit roles delta")
                raise
            finally:
                conn.close()

    def save_rbac_delta(self, rbac: List[Dict[str, Any]]) -> None:
        if not rbac:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM device_node_rbac")
                for entry in rbac:
                    cursor.execute(
                        """
                        INSERT INTO device_node_rbac (node_id, role_id, last_synced_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        """,
                        (entry["node_id"], entry["role_id"]),
                    )
                conn.commit()
                logger.info("Processed delta update for %s RBAC entries", len(rbac))
            except Exception:
                conn.rollback()
                logger.exception("Failed to commit RBAC delta")
                raise
            finally:
                conn.close()

    def deactivate_user_instantly(self, user_id: int) -> bool:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE device_users
                    SET is_active = 0, last_synced_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
                success = cursor.rowcount > 0
                conn.commit()
                return success
            except Exception:
                conn.rollback()
                logger.exception("Database error during instant deactivation")
                return False
            finally:
                conn.close()

    def delete_users_locally(self, user_ids: List[int]) -> None:
        if not user_ids:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in user_ids)
                cursor.execute(f"DELETE FROM device_user_roles WHERE user_id IN ({placeholders})", user_ids)
                cursor.execute(f"DELETE FROM device_users WHERE user_id IN ({placeholders})", user_ids)
                conn.commit()
                logger.info("Deleted %s users from local database", len(user_ids))
            except Exception:
                conn.rollback()
                logger.exception("Failed to delete local users")
                raise
            finally:
                conn.close()

    def get_local_user_ids(self) -> List[int]:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT user_id FROM device_users")
                return [int(row[0]) for row in cursor.fetchall()]
            finally:
                conn.close()

    def get_last_sync_timestamp(self) -> Optional[str]:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT val FROM sync_metadata WHERE key = 'last_synced_at'")
                row = cursor.fetchone()
                return row[0] if row else None
            finally:
                conn.close()

    def update_last_sync_timestamp(self, timestamp: str) -> None:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO sync_metadata (key, val) VALUES ('last_synced_at', ?)
                    ON CONFLICT(key) DO UPDATE SET val = excluded.val
                    """,
                    (timestamp,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("Failed to save sync timestamp")
            finally:
                conn.close()

    def log_authentication_event(
        self,
        user_id: Optional[int],
        auth_status: str,
        confidence_score: Optional[float],
        timestamp: Any,
    ) -> int:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
                cursor.execute(
                    """
                    INSERT INTO device_auth_logs (user_id, auth_status, confidence_score, timestamp, sync_status)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (user_id, auth_status.upper(), confidence_score, ts),
                )
                conn.commit()
                return int(cursor.lastrowid)
            except Exception:
                conn.rollback()
                logger.exception("Failed to buffer authentication log locally")
                raise
            finally:
                conn.close()

    def get_unsynced_logs(self) -> List[Dict[str, Any]]:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT log_id, user_id, auth_status, confidence_score, timestamp
                    FROM device_auth_logs
                    WHERE sync_status = 0
                    ORDER BY timestamp ASC
                    """
                )
                return [
                    {
                        "log_id": row[0],
                        "user_id": row[1],
                        "auth_status": row[2],
                        "confidence_score": row[3],
                        "timestamp": row[4],
                    }
                    for row in cursor.fetchall()
                ]
            except Exception:
                logger.exception("Error fetching unsynced logs")
                return []
            finally:
                conn.close()

    def mark_logs_as_synced(self, log_ids: List[int]) -> None:
        if not log_ids:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in log_ids)
                cursor.execute(
                    f"""
                    UPDATE device_auth_logs
                    SET sync_status = 1
                    WHERE log_id IN ({placeholders})
                    """,
                    log_ids,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("Failed to commit local sync status update")
                raise
            finally:
                conn.close()


class DeactivatePayload(BaseModel):
    user_id: int
    is_active: int


def create_edge_app(db: SQLiteEdgeDB, downstream_worker: Optional["DownstreamSyncWorker"] = None) -> FastAPI:
    app = FastAPI(title="Edge Device Receiver Daemon")

    @app.post("/api/edge/deactivate")
    def handle_deactivation(payload: DeactivatePayload) -> Dict[str, str]:
        if payload.is_active != 0:
            raise HTTPException(status_code=400, detail="Invalid sync command payload")

        success = db.deactivate_user_instantly(payload.user_id)
        if success:
            return {"status": "success", "message": f"User {payload.user_id} deactivated locally"}
        return {"status": "not_found", "message": f"User {payload.user_id} not cached locally"}

    @app.post("/api/edge/trigger-sync")
    def handle_trigger_sync() -> Dict[str, str]:
        if downstream_worker is None:
            logger.warning("Trigger-sync received but no downstream worker is wired")
            return {"status": "skipped", "message": "No downstream worker available"}

        thread = threading.Thread(target=downstream_worker.perform_sync, daemon=True)
        thread.start()
        return {"status": "triggered", "message": "Immediate delta sync initiated"}

    return app


class DownstreamSyncWorker:
    """Polls cloud database deltas into the local SQLite cache."""

    def __init__(self, db: SQLiteEdgeDB, cloud_url: str, poll_interval_sec: int = 60) -> None:
        self.db = db
        self.cloud_url = cloud_url.rstrip("/")
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
            logger.exception("Error performing startup cleanup")

        while not self._stop_event.is_set():
            try:
                self.perform_sync()
            except Exception:
                logger.exception("Sync error in background downstream loop")
            self._stop_event.wait(self.poll_interval)

    def perform_startup_cleanup(self) -> None:
        url = f"{self.cloud_url}/api/sync/downstream/user-ids"
        try:
            logger.info("Syncing cloud database baseline for deleted users at startup")
            response = requests.get(url, timeout=10.0)
            if response.status_code != 200:
                logger.warning("Startup cleanup skipped, cloud returned HTTP %s", response.status_code)
                return

            cloud_user_ids = {int(user_id) for user_id in response.json()}
            local_user_ids = self.db.get_local_user_ids()
            orphaned_ids = [user_id for user_id in local_user_ids if user_id not in cloud_user_ids]
            if orphaned_ids:
                self.db.delete_users_locally(orphaned_ids)
                logger.info("Startup cleanup deleted %s orphaned users", len(orphaned_ids))
            else:
                logger.info("Startup cleanup found no orphaned local users")
        except Exception:
            logger.exception("Network error during startup user validation")

    def perform_sync(self) -> None:
        params = {}
        last_sync = self.db.get_last_sync_timestamp()
        if last_sync:
            params["last_synced_at"] = last_sync

        url = f"{self.cloud_url}/api/sync/downstream/delta"
        try:
            response = requests.get(url, params=params, timeout=10.0)
            if response.status_code != 200:
                logger.error("Cloud returned downstream sync HTTP %s", response.status_code)
                return

            data = response.json()
            self.db.save_roles_delta(data.get("roles", []))
            self.db.save_users_delta(data.get("users", []))
            self.db.save_rbac_delta(data.get("node_rbac", []))

            deleted_ids = data.get("deleted_user_ids", [])
            if deleted_ids:
                self.db.delete_users_locally(deleted_ids)

            timestamp = data.get("timestamp")
            if timestamp:
                self.db.update_last_sync_timestamp(timestamp)
        except Exception:
            logger.exception("Downstream sync network failure")


class UpstreamSyncClient:
    """Sends device heartbeats and replays unsynced auth logs to the cloud."""

    def __init__(
        self,
        db: SQLiteEdgeDB,
        cloud_url: str,
        device_id: str,
        device_name: str,
        local_ip: str,
        local_port: int = 8000,
        log_push_interval_sec: int = 600,
    ) -> None:
        self.db = db
        self.cloud_url = cloud_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.local_ip = local_ip
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
        payload = {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "ip_address": f"{self.local_ip}:{self.local_port}",
        }
        try:
            response = requests.post(url, json=payload, timeout=5.0)
            online = response.status_code == 200
            if online and not self.is_online:
                logger.info("Cloud link restored; sync status ONLINE")
            if not online and self.is_online:
                logger.warning("Cloud heartbeat failed; sync status OFFLINE")
            self.is_online = online
        except Exception:
            if self.is_online:
                logger.warning("Cloud connection dropped; sync status OFFLINE")
            self.is_online = False

    def _run_replay_loop(self) -> None:
        while not self._stop_event.is_set():
            if self.is_online:
                try:
                    self.replay_pending_logs()
                except Exception:
                    logger.exception("Error in chronological log replay queue")
            self._stop_event.wait(self.log_push_interval)

    def replay_pending_logs(self) -> None:
        pending_logs = self.db.get_unsynced_logs()
        if not pending_logs:
            return

        payload_logs = []
        log_id_mapping = {}
        for index, log in enumerate(pending_logs):
            payload_logs.append(
                {
                    "user_id": log["user_id"],
                    "device_id": self.device_id,
                    "auth_status": log["auth_status"],
                    "confidence_score": log["confidence_score"],
                    "timestamp": log["timestamp"],
                }
            )
            log_id_mapping[index] = log["log_id"]

        url = f"{self.cloud_url}/api/sync/upstream/logs"
        try:
            response = requests.post(url, json={"logs": payload_logs}, timeout=15.0)
            if response.status_code != 200:
                logger.error("Cloud returned upstream sync HTTP %s", response.status_code)
                return

            result = response.json()
            successful_indices = result.get("successful_indices", [])
            synced_ids = [log_id_mapping[index] for index in successful_indices if index in log_id_mapping]
            if synced_ids:
                self.db.mark_logs_as_synced(synced_ids)
                logger.info("Replay sync completed for %s auth logs", len(synced_ids))
        except Exception:
            logger.exception("Upstream transmission timeout during log replay")


class SyncEngine:
    """Owns all background sync components for a pipeline process."""

    def __init__(
        self,
        db_path: str | Path,
        cloud_url: str,
        device_id: str,
        device_name: str,
        local_ip: str,
        local_port: int,
        downstream_poll_interval_sec: int,
        log_push_interval_sec: int,
        enabled: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.cloud_url = cloud_url
        self.device_id = device_id
        self.device_name = device_name
        self.local_ip = local_ip
        self.local_port = local_port
        self.downstream_poll_interval_sec = downstream_poll_interval_sec
        self.log_push_interval_sec = log_push_interval_sec
        self.enabled = enabled
        self.db: Optional[SQLiteEdgeDB] = None
        self.downstream: Optional[DownstreamSyncWorker] = None
        self.upstream: Optional[UpstreamSyncClient] = None
        self._server: Optional[uvicorn.Server] = None
        self._server_thread: Optional[threading.Thread] = None
        self._running = False

    @classmethod
    def from_config(cls, config: Any) -> "SyncEngine":
        return cls(
            db_path=config.database_path,
            cloud_url=config.sync_cloud_url,
            device_id=config.sync_device_id,
            device_name=config.sync_device_name,
            local_ip=config.sync_local_ip,
            local_port=config.sync_local_port,
            downstream_poll_interval_sec=config.sync_downstream_poll_seconds,
            log_push_interval_sec=config.sync_log_push_interval_seconds,
            enabled=config.sync_enabled,
        )

    def start(self) -> None:
        if not self.enabled:
            logger.info("Sync engine disabled by configuration")
            return
        if self._running:
            return

        self.db = SQLiteEdgeDB(self.db_path)
        self.downstream = DownstreamSyncWorker(
            self.db,
            cloud_url=self.cloud_url,
            poll_interval_sec=self.downstream_poll_interval_sec,
        )
        self.upstream = UpstreamSyncClient(
            self.db,
            cloud_url=self.cloud_url,
            device_id=self.device_id,
            device_name=self.device_name,
            local_ip=self.local_ip,
            local_port=self.local_port,
            log_push_interval_sec=self.log_push_interval_sec,
        )

        app = create_edge_app(self.db, downstream_worker=self.downstream)
        uvicorn_config = uvicorn.Config(app, host="0.0.0.0", port=self.local_port, log_level="warning")
        self._server = uvicorn.Server(uvicorn_config)

        self.upstream.start()
        self.downstream.start()
        self._server_thread = threading.Thread(target=self._server.run, daemon=True)
        self._server_thread.start()
        self._running = True
        logger.info("Sync engine started for %s using %s", self.device_id, self.db_path)

    def stop(self) -> None:
        if not self._running:
            return
        if self.upstream:
            self.upstream.stop()
        if self.downstream:
            self.downstream.stop()
        if self._server:
            self._server.should_exit = True
        if self._server_thread:
            self._server_thread.join(timeout=3)
        self._running = False
        logger.info("Sync engine stopped")
