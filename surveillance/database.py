"""SQLite database repository for surveillance user embeddings and event logging."""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
import threading
from array import array
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from .utils.matching import FaceTemplate, count_templates_by_user

logger = logging.getLogger(__name__)


def generate_sync_key() -> str:
    """Generate a unique sync key for database records."""
    import uuid
    return str(uuid.uuid4())


class SurveillanceDatabaseError(RuntimeError):
    pass


class SurveillanceUserRepository:
    """Local SQLite repository for registered AuraFace embeddings and surveillance event logs."""

    def __init__(self, db_path: str | Path = "surveillance.db") -> None:
        self.db_path = Path(db_path)
        self.lock = threading.Lock()
        self.initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def initialize_schema(self) -> None:
        """Create necessary database tables for surveillance."""
        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_users (
                        user_id INTEGER PRIMARY KEY,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        last_synced_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_user_face_embeddings (
                        user_id INTEGER NOT NULL,
                        template_name TEXT NOT NULL DEFAULT 'front',
                        model_name TEXT NOT NULL DEFAULT 'arcface_r50',
                        embedding BLOB NOT NULL,
                        last_synced_at TEXT,
                        PRIMARY KEY(user_id, template_name, model_name),
                        FOREIGN KEY(user_id) REFERENCES device_users(user_id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_surveillance_logs (
                        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sync_key TEXT UNIQUE NOT NULL,
                        user_id INTEGER,
                        recognition_status TEXT NOT NULL,
                        confidence_score REAL,
                        matched_template TEXT,
                        face_count INTEGER DEFAULT 1,
                        bbox TEXT,
                        timestamp TEXT NOT NULL,
                        image_path TEXT,
                        sync_status INTEGER DEFAULT 0,
                        synced_at TEXT,
                        FOREIGN KEY(user_id) REFERENCES device_users(user_id) ON DELETE SET NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sync_metadata (
                        key TEXT PRIMARY KEY,
                        val TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_roles (
                        role_id INTEGER PRIMARY KEY,
                        role_name TEXT NOT NULL,
                        last_synced_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_user_roles (
                        user_id INTEGER NOT NULL,
                        role_id INTEGER NOT NULL,
                        last_synced_at TEXT,
                        PRIMARY KEY (user_id, role_id),
                        FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE CASCADE,
                        FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_node_rbac (
                        node_id TEXT NOT NULL,
                        role_id INTEGER NOT NULL,
                        last_synced_at TEXT,
                        PRIMARY KEY (node_id, role_id),
                        FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_rbac (
                        device_id TEXT NOT NULL,
                        role_id INTEGER NOT NULL,
                        last_synced_at TEXT,
                        PRIMARY KEY (device_id, role_id),
                        FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE
                    )
                    """
                )
                conn.commit()
                logger.info("Initialized surveillance database schema at %s", self.db_path)
            except Exception:
                conn.rollback()
                logger.exception("Failed to initialize surveillance database schema")
                raise
            finally:
                conn.close()

    def load_templates(self) -> List[FaceTemplate]:
        """Loads AuraFace templates for active users."""
        with self.lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT
                        u.user_id,
                        u.is_active,
                        e.template_name,
                        e.embedding
                    FROM device_user_face_embeddings e
                    INNER JOIN device_users u ON u.user_id = e.user_id
                    WHERE e.embedding IS NOT NULL AND length(e.embedding) > 0
                      AND u.is_active = 1
                    ORDER BY u.user_id, e.template_name
                    """
                ).fetchall()
                templates: List[FaceTemplate] = []
                for row in rows:
                    vec = self._vector_from_blob(row["embedding"])
                    if vec.size == 0:
                        continue
                    templates.append(
                        FaceTemplate(
                            user_id=str(row["user_id"]),
                            identity=str(row["user_id"]),
                            template_name=str(row["template_name"]),
                            embedding=vec,
                            is_active=bool(int(row["is_active"])),
                        )
                    )
                return self._log_templates(templates)
            finally:
                conn.close()

    def count(self) -> int:
        """Counts total active AuraFace embeddings."""
        with self.lock:
            conn = self._connect()
            try:
                res = conn.execute("SELECT COUNT(*) FROM device_user_face_embeddings").fetchone()
                return res[0] if res else 0
            finally:
                conn.close()

    def log_surveillance_event(
        self,
        user_id: Optional[str | int],
        recognition_status: str,
        confidence_score: Optional[float],
        matched_template: Optional[str] = None,
        face_count: int = 1,
        bbox: Optional[Any] = None,
        image_path: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """Buffers a surveillance recognition event into SQLite device_surveillance_logs."""
        import datetime
        with self.lock:
            conn = self._connect()
            try:
                normalized_user_id: Optional[int]
                try:
                    normalized_user_id = int(user_id) if user_id is not None else None
                except (TypeError, ValueError):
                    normalized_user_id = None

                ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
                bbox_json = bbox if isinstance(bbox, str) or bbox is None else json.dumps(bbox)

                # Verify normalized_user_id exists in device_users to satisfy FK constraint if present
                if normalized_user_id is not None:
                    check = conn.execute("SELECT 1 FROM device_users WHERE user_id = ?", (normalized_user_id,)).fetchone()
                    if check is None:
                        # Auto-create user entry or fallback to None to prevent FK constraint failure
                        try:
                            conn.execute("INSERT INTO device_users (user_id, is_active) VALUES (?, 1)", (normalized_user_id,))
                        except sqlite3.Error:
                            normalized_user_id = None

                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO device_surveillance_logs (
                        sync_key, user_id, recognition_status, confidence_score,
                        matched_template, face_count, bbox, timestamp, image_path, sync_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        generate_sync_key(),
                        normalized_user_id,
                        recognition_status.upper(),
                        confidence_score,
                        matched_template,
                        int(face_count),
                        bbox_json,
                        ts,
                        image_path,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            except Exception:
                conn.rollback()
                logger.exception("Failed to log surveillance event")
                raise
            finally:
                conn.close()

    def get_unsynced_surveillance_logs(self) -> List[Dict[str, Any]]:
        """Fetch pending surveillance logs that have not been synced to cloud."""
        with self.lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT log_id, sync_key, user_id, recognition_status, confidence_score,
                           matched_template, face_count, bbox, timestamp, image_path
                    FROM device_surveillance_logs
                    WHERE sync_status = 0
                    ORDER BY timestamp ASC
                    """
                ).fetchall()
                logs = []
                for row in rows:
                    bbox_val = row["bbox"]
                    try:
                        if isinstance(bbox_val, str) and bbox_val.strip():
                            bbox_val = json.loads(bbox_val)
                    except Exception:
                        pass

                    logs.append(
                        {
                            "log_id": row["log_id"],
                            "sync_key": row["sync_key"],
                            "user_id": row["user_id"],
                            "recognition_status": row["recognition_status"],
                            "confidence_score": row["confidence_score"],
                            "matched_template": row["matched_template"],
                            "face_count": row["face_count"],
                            "bbox": bbox_val,
                            "timestamp": row["timestamp"],
                            "image_path": row["image_path"],
                        }
                    )
                return logs
            finally:
                conn.close()

    def mark_surveillance_logs_as_synced(self, log_ids: List[int]) -> None:
        """Mark log IDs as synced to cloud."""
        if not log_ids:
            return
        with self.lock:
            conn = self._connect()
            try:
                placeholders = ",".join("?" for _ in log_ids)
                conn.execute(
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
                logger.exception("Failed to mark surveillance logs as synced")
                raise
            finally:
                conn.close()

    def apply_delta(self, users: List[Dict[str, Any]]) -> None:
        """Apply users delta update from cloud sync."""
        if not users:
            return
        with self.lock:
            conn = self._connect()
            cursor = conn.cursor()
            try:
                for user in users:
                    user_id = int(user["user_id"])
                    is_active = int(user.get("is_active", 1))

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

                    # Update face embeddings if provided
                    embeddings = user.get("embeddings") or user.get("face_embeddings") or []
                    if embeddings:
                        cursor.execute("DELETE FROM device_user_face_embeddings WHERE user_id = ?", (user_id,))
                        for item in embeddings:
                            model_name = str(item.get("model_name") or "arcface_r50")
                            if model_name not in {"arcface_r50", "auraface"}:
                                continue
                            template_name = str(item.get("template_name") or item.get("template") or "front")
                            val = item.get("embedding") or item.get("embedding_b64") or item.get("face_vector_b64")
                            blob = self._decode_embedding(val)
                            if blob:
                                cursor.execute(
                                    """
                                    INSERT INTO device_user_face_embeddings (
                                        user_id, template_name, model_name, embedding, last_synced_at
                                    ) VALUES (?, ?, 'arcface_r50', ?, CURRENT_TIMESTAMP)
                                    """,
                                    (user_id, template_name, blob),
                                )
                conn.commit()
                logger.info("Applied users delta update for %s users", len(users))
            except Exception:
                conn.rollback()
                logger.exception("Failed to apply users delta")
                raise
            finally:
                conn.close()

    def delete_users_locally(self, user_ids: List[int]) -> None:
        """Delete user accounts locally."""
        if not user_ids:
            return
        with self.lock:
            conn = self._connect()
            try:
                placeholders = ",".join("?" for _ in user_ids)
                conn.execute(f"DELETE FROM device_user_roles WHERE user_id IN ({placeholders})", user_ids)
                conn.execute(f"DELETE FROM device_users WHERE user_id IN ({placeholders})", user_ids)
                conn.commit()
                logger.info("Deleted %s local users", len(user_ids))
            except Exception:
                conn.rollback()
                logger.exception("Failed to delete local users")
                raise
            finally:
                conn.close()

    def get_local_user_ids(self) -> List[int]:
        with self.lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT user_id FROM device_users").fetchall()
                return [int(row[0]) for row in rows]
            finally:
                conn.close()

    def get_last_sync_timestamp(self) -> Optional[str]:
        with self.lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT val FROM sync_metadata WHERE key = 'last_synced_at'").fetchone()
                return row[0] if row else None
            finally:
                conn.close()

    def update_last_sync_timestamp(self, timestamp: str) -> None:
        with self.lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO sync_metadata (key, val) VALUES ('last_synced_at', ?)
                    ON CONFLICT(key) DO UPDATE SET val = excluded.val
                    """,
                    (timestamp,),
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _log_templates(templates: List[FaceTemplate]) -> List[FaceTemplate]:
        counts = count_templates_by_user(templates)
        logger.info("Loaded %s registered users and %s AuraFace templates", len(counts), len(templates))
        return templates

    @staticmethod
    def _vector_from_blob(blob: bytes) -> np.ndarray:
        if len(blob) == 0 or len(blob) % 4 != 0:
            return np.empty((0,), dtype=np.float32)
        vec = np.frombuffer(blob, dtype=np.float32).copy()
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 1e-12 else vec

    @staticmethod
    def _decode_embedding(val: Any) -> Optional[bytes]:
        if val is None:
            return None
        if isinstance(val, bytes):
            return val
        if isinstance(val, str):
            stripped = val.strip()
            if not stripped:
                return None
            try:
                return base64.b64decode(stripped, validate=True)
            except Exception:
                pass
        if isinstance(val, (list, tuple)):
            return array("f", (float(item) for item in val)).tobytes()
        return None
