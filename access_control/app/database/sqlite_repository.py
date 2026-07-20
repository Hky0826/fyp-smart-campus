"""Cloud-synchronized identity and event storage using the shared edge schema."""
from __future__ import annotations

import base64
import json
import secrets
import sqlite3
import threading
import time
from array import array
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..domain import Embedding, IdentityMatch
from ..recognition.sface import SFaceRecognizer


def _sync_key():
    return f"{int(time.time() * 1000):x}-{secrets.token_hex(8)}"


def _utc(value=None):
    value = value or datetime.now(timezone.utc)
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _decode(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, list):
        return array("f", (float(item) for item in value)).tobytes()
    if isinstance(value, str):
        try:
            return base64.b64decode(value.strip(), validate=True)
        except Exception:
            return None
    return None


class SQLiteIdentityRepository:
    """Access-control repository backed by the same tables used by edge devices."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
                conn.commit()
            finally:
                conn.close()

    def compatible_embeddings(self, probe):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT u.user_id, e.model_name, e.embedding
                FROM device_user_face_embeddings e
                JOIN device_users u ON u.user_id = e.user_id
                WHERE u.is_active = 1 AND e.model_name = ?
                """,
                (probe.model_name,),
            ).fetchall()
            compatible = []
            for row in rows:
                vector = np.frombuffer(row["embedding"], np.float32).copy()
                if vector.size != probe.dimension:
                    continue
                reference = Embedding(
                    vector,
                    row["model_name"],
                    probe.model_version,
                    int(vector.size),
                    -1,
                    0.0,
                )
                identity = str(row["user_id"])
                compatible.append((identity, identity, reference))
            return compatible
        finally:
            conn.close()

    def find_match(self, embedding, threshold=0.363):
        best = None
        for identity_id, name, reference in self.compatible_embeddings(embedding):
            score = SFaceRecognizer.similarity(embedding, reference)
            if score >= threshold and (best is None or score > best.similarity):
                best = IdentityMatch(identity_id, name, score, reference)
        return best

    def status(self):
        conn = self._connect()
        try:
            users = conn.execute("SELECT count(*) FROM device_users WHERE is_active = 1").fetchone()[0]
            templates = conn.execute("SELECT count(*) FROM device_user_face_embeddings").fetchone()[0]
            pending_surveillance = conn.execute(
                "SELECT count(*) FROM device_surveillance_logs WHERE sync_status = 0"
            ).fetchone()[0]
            return {
                "ok": True,
                "path": str(self.db_path),
                "active_users": users,
                "sface_templates": templates,
                "pending_surveillance_logs": pending_surveillance,
            }
        finally:
            conn.close()

    def log_authentication_event(
        self,
        user_id,
        auth_status,
        confidence_score,
        face_count=1,
        reason=None,
        timestamp=None,
        image_path=None,
        spoofing_checked=False,
        spoofing_passed=None,
    ):
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO device_auth_logs(
                        sync_key, user_id, auth_status, confidence_score, face_count,
                        reason, spoofing_checked, spoofing_passed, timestamp, image_path, sync_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        _sync_key(),
                        None if user_id is None else int(user_id),
                        auth_status.upper(),
                        confidence_score,
                        int(face_count),
                        reason,
                        int(spoofing_checked),
                        None if spoofing_passed is None else int(spoofing_passed),
                        _utc(timestamp),
                        image_path,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                conn.close()

    def get_unsynced_logs(self):
        conn = self._connect()
        try:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM device_auth_logs WHERE sync_status = 0 ORDER BY timestamp, log_id"
                ).fetchall()
            ]
        finally:
            conn.close()

    def mark_logs_as_synced(self, ids):
        self._mark_logs_as_synced("device_auth_logs", ids)

    def log_surveillance_event(
        self,
        user_id,
        recognition_status,
        confidence_score,
        matched_template=None,
        face_count=1,
        bbox=None,
        image_path=None,
        timestamp=None,
    ):
        bbox_value = bbox if isinstance(bbox, str) or bbox is None else json.dumps(bbox)
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO device_surveillance_logs(
                        sync_key, user_id, recognition_status, confidence_score,
                        matched_template, face_count, bbox, timestamp, image_path, sync_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        _sync_key(),
                        None if user_id is None else int(user_id),
                        recognition_status.upper(),
                        confidence_score,
                        matched_template,
                        int(face_count),
                        bbox_value,
                        _utc(timestamp),
                        image_path,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                conn.close()

    def get_unsynced_surveillance_logs(self):
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT log_id, sync_key, user_id, recognition_status, confidence_score,
                       matched_template, face_count, bbox, timestamp, image_path
                FROM device_surveillance_logs
                WHERE sync_status = 0
                ORDER BY timestamp, log_id
                """
            ).fetchall()
            logs = []
            for row in rows:
                item = dict(row)
                if isinstance(item["bbox"], str) and item["bbox"].strip():
                    try:
                        item["bbox"] = json.loads(item["bbox"])
                    except json.JSONDecodeError:
                        pass
                logs.append(item)
            return logs
        finally:
            conn.close()

    def mark_surveillance_logs_as_synced(self, ids):
        self._mark_logs_as_synced("device_surveillance_logs", ids)

    def _mark_logs_as_synced(self, table, ids):
        ids = list(ids)
        if not ids:
            return
        if table not in {"device_auth_logs", "device_surveillance_logs"}:
            raise ValueError("unsupported log table")
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE {table} SET sync_status = 1, synced_at = CURRENT_TIMESTAMP "
                f"WHERE log_id IN ({placeholders})",
                ids,
            )
            conn.commit()
        finally:
            conn.close()

    def get_local_user_ids(self):
        conn = self._connect()
        try:
            return [row[0] for row in conn.execute("SELECT user_id FROM device_users").fetchall()]
        finally:
            conn.close()

    def delete_users_locally(self, ids):
        ids = list(map(int, ids))
        if not ids:
            return
        conn = self._connect()
        try:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM device_users WHERE user_id IN ({placeholders})", ids)
            conn.commit()
        finally:
            conn.close()

    def deactivate_user_instantly(self, user_id):
        conn = self._connect()
        try:
            cursor = conn.execute(
                "UPDATE device_users SET is_active = 0, last_synced_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (int(user_id),),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_last_sync_timestamp(self):
        conn = self._connect()
        try:
            row = conn.execute("SELECT val FROM sync_metadata WHERE key = 'last_sync_timestamp'").fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def update_last_sync_timestamp(self, value):
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO sync_metadata(key, val) VALUES ('last_sync_timestamp', ?)
                ON CONFLICT(key) DO UPDATE SET val = excluded.val
                """,
                (str(value),),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _iter_embedding_payloads(user):
        payloads = []
        direct_keys = {"face_vector_b64", "embedding_b64", "face_vector", "embedding", "embedding_blob"}
        if direct_keys.intersection(user):
            payloads.append(user)
        for key in ("embeddings", "face_embeddings", "user_face_embeddings", "templates"):
            value = user.get(key)
            if isinstance(value, list):
                payloads.extend(item if isinstance(item, dict) else {"embedding": item} for item in value)
            elif isinstance(value, dict):
                if direct_keys.intersection(value):
                    payloads.append(value)
                else:
                    for template_name, embedding in value.items():
                        item = dict(embedding) if isinstance(embedding, dict) else {"embedding": embedding}
                        item.setdefault("template_name", template_name)
                        payloads.append(item)
        return payloads

    def save_users_delta(self, users):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for user in users:
                user_id = int(user["user_id"])
                conn.execute(
                    """
                    INSERT INTO device_users(user_id, is_active, last_synced_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET
                        is_active = excluded.is_active,
                        last_synced_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, int(user.get("is_active", 1))),
                )
                template_keys = (
                    "face_vector_b64", "embedding_b64", "face_vector", "embedding", "embedding_blob",
                    "embeddings", "face_embeddings", "user_face_embeddings", "templates",
                )
                if any(key in user for key in template_keys):
                    conn.execute("DELETE FROM device_user_face_embeddings WHERE user_id = ?", (user_id,))
                    for index, payload in enumerate(self._iter_embedding_payloads(user)):
                        blob = _decode(
                            payload.get(
                                "embedding_b64",
                                payload.get("face_vector_b64", payload.get("embedding", payload.get("face_vector", payload.get("embedding_blob")))),
                            )
                        )
                        if not blob:
                            continue
                        conn.execute(
                            """
                            INSERT INTO device_user_face_embeddings(
                                user_id, template_name, model_name, embedding, last_synced_at
                            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_id, template_name, model_name) DO UPDATE SET
                                embedding = excluded.embedding,
                                last_synced_at = CURRENT_TIMESTAMP
                            """,
                            (
                                user_id,
                                payload.get("template_name", f"template-{index + 1}"),
                                payload.get("model_name", "openvc_sface"),
                                blob,
                            ),
                        )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_roles_delta(self, roles):
        conn = self._connect()
        try:
            for role in roles:
                conn.execute(
                    """
                    INSERT INTO device_roles(role_id, role_name) VALUES (?, ?)
                    ON CONFLICT(role_id) DO UPDATE SET
                        role_name = excluded.role_name,
                        last_synced_at = CURRENT_TIMESTAMP
                    """,
                    (int(role["role_id"]), role["role_name"]),
                )
            conn.commit()
        finally:
            conn.close()

    def save_user_roles_delta(self, items):
        conn = self._connect()
        try:
            users = {int(item["user_id"]) for item in items}
            for user_id in users:
                conn.execute("DELETE FROM device_user_roles WHERE user_id = ?", (user_id,))
            for item in items:
                conn.execute(
                    "INSERT OR IGNORE INTO device_user_roles(user_id, role_id) VALUES (?, ?)",
                    (int(item["user_id"]), int(item["role_id"])),
                )
            conn.commit()
        finally:
            conn.close()

    def save_rbac_delta(self, items):
        conn = self._connect()
        try:
            for item in items:
                conn.execute(
                    """
                    INSERT INTO device_node_rbac(node_id, role_id) VALUES (?, ?)
                    ON CONFLICT(node_id, role_id) DO UPDATE SET last_synced_at = CURRENT_TIMESTAMP
                    """,
                    (int(item["node_id"]), int(item["role_id"])),
                )
            conn.commit()
        finally:
            conn.close()