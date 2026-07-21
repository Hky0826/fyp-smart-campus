"""Cloud synchronization engine for the access-control edge pipelines."""

from __future__ import annotations

import base64
import datetime
import json
import logging
import sqlite3
import threading
from array import array
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..setup_sqlite import backfill_missing_sync_keys, initialize_sqlite_database, table_columns
from .utils.sync_key import generate_sync_key


logger = logging.getLogger(__name__)
DEFAULT_EMBEDDING_MODEL = "openvc_sface"


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
            try:
                initialize_sqlite_database(self.db_path)
                logger.info("SQLite sync schema initialized at %s", self.db_path)
            except Exception:
                logger.exception("Error initializing SQLite sync schema")
                raise

    @staticmethod
    def _table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
        return table_columns(cursor, table_name)

    def save_users_delta(self, users: List[Dict[str, Any]]) -> None:
        if not users:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                user_columns = self._table_columns(cursor, "device_users")
                for user in users:
                    user_id = user["user_id"]
                    is_active = int(user.get("is_active", 1))
                    embeddings_present = self._has_embedding_payload(user)
                    embedding_records = self._embedding_records_from_user(user)

                    if "face_vector" in user_columns:
                        legacy_face_vector = embedding_records[0]["embedding"] if embedding_records else b""
                        cursor.execute(
                            """
                            INSERT INTO device_users (user_id, face_vector, is_active, last_synced_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_id) DO UPDATE SET
                                face_vector=excluded.face_vector,
                                is_active=excluded.is_active,
                                last_synced_at=CURRENT_TIMESTAMP
                            """,
                            (user_id, legacy_face_vector, is_active),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO device_users (user_id, is_active, last_synced_at)
                            VALUES (?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_id) DO UPDATE SET
                                is_active=excluded.is_active,
                                last_synced_at=CURRENT_TIMESTAMP
                            """,
                            (user_id, is_active),
                        )
                    if embeddings_present:
                        cursor.execute("DELETE FROM device_user_face_embeddings WHERE user_id = ?", (user_id,))
                        for record in embedding_records:
                            cursor.execute(
                                """
                                INSERT INTO device_user_face_embeddings (
                                    user_id,
                                    template_name,
                                    model_name,
                                    embedding,
                                    last_synced_at
                                )
                                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                                ON CONFLICT(user_id, template_name, model_name) DO UPDATE SET
                                    embedding=excluded.embedding,
                                    last_synced_at=CURRENT_TIMESTAMP
                                """,
                                (
                                    user_id,
                                    record["template_name"],
                                    record["model_name"],
                                    record["embedding"],
                                ),
                            )
                conn.commit()
                logger.info("Processed delta update for %s users", len(users))
            except Exception:
                conn.rollback()
                logger.exception("Failed to commit users delta")
                raise
            finally:
                conn.close()

    @staticmethod
    def _has_embedding_payload(user: Dict[str, Any]) -> bool:
        return any(
            key in user
            for key in (
                "face_vector_b64",
                "embedding_b64",
                "face_vector",
                "embedding",
                "embedding_blob",
                "embeddings",
                "face_embeddings",
                "user_face_embeddings",
                "templates",
            )
        )

    @classmethod
    def _embedding_records_from_user(cls, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        records = []
        for payload in cls._iter_embedding_payloads(user):
            record = cls._embedding_record_from_payload(payload)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _iter_embedding_payloads(user: Dict[str, Any]) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []
        direct_keys = {"face_vector_b64", "embedding_b64", "face_vector", "embedding", "embedding_blob"}
        if direct_keys.intersection(user):
            payloads.append(user)

        for key in ("embeddings", "face_embeddings", "user_face_embeddings", "templates"):
            value = user.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        payloads.append(item)
                    else:
                        payloads.append({"embedding": item})
            elif isinstance(value, dict):
                if direct_keys.intersection(value):
                    payloads.append(value)
                else:
                    for template_name, embedding in value.items():
                        if isinstance(embedding, dict):
                            item = dict(embedding)
                            item.setdefault("template_name", template_name)
                            payloads.append(item)
                        else:
                            payloads.append({"template_name": template_name, "embedding": embedding})
        return payloads

    @classmethod
    def _embedding_record_from_payload(cls, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        value = None
        for key in ("embedding_b64", "face_vector_b64", "embedding_blob", "embedding", "face_vector"):
            if key in payload:
                value = payload[key]
                break
        embedding = cls._decode_embedding(value)
        if not embedding:
            return None
        return {
            "template_name": str(payload.get("template_name") or payload.get("template") or payload.get("pose") or "front"),
            "model_name": str(payload.get("model_name") or DEFAULT_EMBEDDING_MODEL),
            "embedding": embedding,
        }

    @staticmethod
    def _decode_embedding(value: Any) -> Optional[bytes]:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            return base64.b64decode(stripped, validate=True)
        if isinstance(value, list):
            return array("f", (float(item) for item in value)).tobytes()
        return None

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

    def save_user_roles_delta(self, user_roles: List[Dict[str, Any]]) -> None:
        if not user_roles:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # Clear existing roles for updated users to avoid accumulation
                user_ids_to_clear = {ur["user_id"] for ur in user_roles}
                for uid in user_ids_to_clear:
                    cursor.execute("DELETE FROM device_user_roles WHERE user_id = ?", (uid,))

                saved_count = 0
                for user_role in user_roles:
                    user_id = user_role["user_id"]
                    role_id = user_role["role_id"]
                    cursor.execute("SELECT 1 FROM device_users WHERE user_id = ?", (user_id,))
                    if cursor.fetchone() is None:
                        continue
                    cursor.execute("SELECT 1 FROM device_roles WHERE role_id = ?", (role_id,))
                    if cursor.fetchone() is None:
                        continue
                    cursor.execute(
                        """
                        INSERT INTO device_user_roles (user_id, role_id, last_synced_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(user_id, role_id) DO UPDATE SET
                            last_synced_at=CURRENT_TIMESTAMP
                        """,
                        (user_id, role_id),
                    )
                    saved_count += 1
                conn.commit()
                logger.info("Processed delta update for %s user-role assignments", saved_count)
            except Exception:
                conn.rollback()
                logger.exception("Failed to commit user-role assignments delta")
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
                    INSERT INTO device_auth_logs (sync_key, user_id, auth_status, confidence_score, timestamp, sync_status)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (generate_sync_key(), user_id, auth_status.upper(), confidence_score, ts),
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
                backfill_missing_sync_keys(cursor, "device_auth_logs")
                conn.commit()
                cursor.execute(
                    """
                    SELECT
                        log_id,
                        sync_key,
                        user_id,
                        auth_status,
                        confidence_score,
                        face_count,
                        reason,
                        spoofing_checked,
                        spoofing_passed,
                        timestamp,
                        image_path
                    FROM device_auth_logs
                    WHERE sync_status = 0
                    ORDER BY timestamp ASC
                    """
                )
                return [
                    {
                        "log_id": row[0],
                        "sync_key": row[1],
                        "user_id": row[2],
                        "auth_status": row[3],
                        "confidence_score": row[4],
                        "face_count": row[5],
                        "reason": row[6],
                        "spoofing_checked": row[7],
                        "spoofing_passed": row[8],
                        "timestamp": row[9],
                        "image_path": row[10],
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
                    SET sync_status = 1, synced_at = CURRENT_TIMESTAMP
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

    def log_surveillance_event(
        self,
        user_id: Optional[int],
        recognition_status: str,
        confidence_score: Optional[float],
        matched_template: Optional[str] = None,
        face_count: int = 1,
        bbox: Optional[Any] = None,
        image_path: Optional[str] = None,
        timestamp: Any = None,
    ) -> int:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp or datetime.datetime.utcnow().isoformat())
                bbox_value = bbox if isinstance(bbox, str) or bbox is None else json.dumps(bbox)
                cursor.execute(
                    """
                    INSERT INTO device_surveillance_logs (
                        sync_key,
                        user_id,
                        recognition_status,
                        confidence_score,
                        matched_template,
                        face_count,
                        bbox,
                        timestamp,
                        image_path,
                        sync_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        generate_sync_key(),
                        user_id,
                        recognition_status.upper(),
                        confidence_score,
                        matched_template,
                        int(face_count),
                        bbox_value,
                        ts,
                        image_path,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            except Exception:
                conn.rollback()
                logger.exception("Failed to buffer surveillance log locally")
                raise
            finally:
                conn.close()

    def get_unsynced_surveillance_logs(self) -> List[Dict[str, Any]]:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                backfill_missing_sync_keys(cursor, "device_surveillance_logs")
                conn.commit()
                cursor.execute(
                    """
                    SELECT
                        log_id,
                        sync_key,
                        user_id,
                        recognition_status,
                        confidence_score,
                        matched_template,
                        face_count,
                        bbox,
                        timestamp,
                        image_path
                    FROM device_surveillance_logs
                    WHERE sync_status = 0
                    ORDER BY timestamp ASC
                    """
                )
                return [
                    {
                        "log_id": row[0],
                        "sync_key": row[1],
                        "user_id": row[2],
                        "recognition_status": row[3],
                        "confidence_score": row[4],
                        "matched_template": row[5],
                        "face_count": row[6],
                        "bbox": self._decode_json_field(row[7]),
                        "timestamp": row[8],
                        "image_path": row[9],
                    }
                    for row in cursor.fetchall()
                ]
            except Exception:
                logger.exception("Error fetching unsynced surveillance logs")
                return []
            finally:
                conn.close()

    @staticmethod
    def _decode_json_field(value: Any) -> Any:
        if not isinstance(value, str) or not value.strip():
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def mark_surveillance_logs_as_synced(self, log_ids: List[int]) -> None:
        if not log_ids:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in log_ids)
                cursor.execute(
                    f"""
                    UPDATE device_surveillance_logs
                    SET sync_status = 1, synced_at = CURRENT_TIMESTAMP
                    WHERE log_id IN ({placeholders})
                    """,
                    log_ids,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("Failed to commit local surveillance sync status update")
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
        # Request access_control module templates from cloud (openvc_sface embeddings)
        params = {"module": "access_control"}
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
            self.db.save_user_roles_delta(data.get("user_roles", data.get("device_user_roles", [])))
            self.db.save_rbac_delta(data.get("node_rbac", []))

            deleted_ids = data.get("deleted_user_ids", [])
            if deleted_ids:
                self.db.delete_users_locally(deleted_ids)

            timestamp = data.get("timestamp")
            if timestamp:
                self.db.update_last_sync_timestamp(timestamp)
        except requests.exceptions.RequestException as exc:
            logger.warning("Downstream cloud sync offline (%s: %s). Operating in local offline mode.", url, type(exc).__name__)
        except Exception:
            logger.exception("Downstream sync unexpected error")


class UpstreamSyncClient:
    """Sends device heartbeats and replays unsynced edge logs to the cloud."""

    def __init__(
        self,
        db: SQLiteEdgeDB,
        cloud_url: str,
        device_id: str,
        device_name: str,
        local_ip: str,
        local_port: int = 8000,
        log_push_interval_sec: int = 60,
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
        self.replay_pending_authentication_logs()
        self.replay_pending_surveillance_logs()

    def replay_pending_authentication_logs(self) -> None:
        pending_logs = self.db.get_unsynced_logs()
        if not pending_logs:
            return

        payload_logs = []
        log_id_mapping = {}
        for index, log in enumerate(pending_logs):
            payload_logs.append(
                {
                    "sync_key": log["sync_key"],
                    "user_id": log["user_id"],
                    "device_id": self.device_id,
                    "auth_status": log["auth_status"],
                    "confidence_score": log["confidence_score"],
                    "face_count": log["face_count"],
                    "reason": log["reason"],
                    "spoofing_checked": log["spoofing_checked"],
                    "spoofing_passed": log["spoofing_passed"],
                    "timestamp": log["timestamp"],
                    "image_path": log["image_path"],
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

    def replay_pending_surveillance_logs(self) -> None:
        pending_logs = self.db.get_unsynced_surveillance_logs()
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
            response = requests.post(url, json={"logs": payload_logs}, timeout=30.0)
            if response.status_code != 200:
                logger.error("Cloud returned surveillance upstream sync HTTP %s", response.status_code)
                return

            result = response.json()
            successful_indices = result.get("successful_indices", [])
            synced_ids = [log_id_mapping[index] for index in successful_indices if index in log_id_mapping]
            if synced_ids:
                self.db.mark_surveillance_logs_as_synced(synced_ids)
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
            logger.exception("Failed to read surveillance snapshot %s", path)
            return None, path.name


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
