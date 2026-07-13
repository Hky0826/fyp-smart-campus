"""SQLite loader for already-enrolled device user embeddings."""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from .matching import FaceTemplate, count_templates_by_user
from ..utils.sync_key import generate_sync_key


logger = logging.getLogger(__name__)


class DeviceUserDatabaseError(RuntimeError):
    pass


class DeviceUserRepository:
    """Reads registered user embeddings from the local SQLite edge database.

    The updated schema stores one or more embeddings per user in
    `device_user_face_embeddings`. Legacy `device_users.face_vector` layouts are
    still read so existing persisted edge databases can be migrated safely.
    """

    EMBEDDING_COLUMNS = (
        "face_vector",
        "face_vectors",
        "embedding",
        "embeddings",
        "face_embedding",
        "embedding_blob",
        "templates_json",
    )
    TEMPLATE_COLUMNS = ("template_name", "template", "pose", "pose_name", "view", "image_name")
    IDENTITY_COLUMNS = ("identity", "person_id", "username", "name", "display_name")

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {self.db_path}")
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_status(self) -> Dict[str, object]:
        conn = self._connect()
        try:
            self._require_device_users(conn)
            templates = self.load_templates()
            counts = count_templates_by_user(templates)
            return {
                "ok": True,
                "path": str(self.db_path),
                "registered_users": len(counts),
                "templates": len(templates),
                "templates_per_user": counts,
            }
        finally:
            conn.close()

    def load_templates(self) -> List[FaceTemplate]:
        conn = self._connect()
        try:
            columns = self._require_device_users(conn)
            tables = self._table_names(conn)
            if "device_user_face_embeddings" in tables:
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
                    ORDER BY u.user_id, e.template_name, e.model_name
                    """
                ).fetchall()
                templates = self._templates_from_embedding_rows(rows)
                if templates or "face_vector" not in columns:
                    return self._log_templates(templates)

            rows = conn.execute("SELECT * FROM device_users").fetchall()
        finally:
            conn.close()

        templates: List[FaceTemplate] = []
        embedding_columns = [c for c in self.EMBEDDING_COLUMNS if c in columns]
        if not embedding_columns:
            raise DeviceUserDatabaseError("device_users has no supported embedding column")

        for row in rows:
            row_templates = self._templates_from_row(row, columns, embedding_columns)
            templates.extend(row_templates)

        return self._log_templates(templates)

    def _log_templates(self, templates: List[FaceTemplate]) -> List[FaceTemplate]:
        counts = count_templates_by_user(templates)
        logger.info("Loaded %s registered users and %s face templates", len(counts), len(templates))
        for user_id, count in counts.items():
            logger.info("Loaded %s templates for user %s", count, user_id)
        return templates

    def log_auth_event(self, user_id: Optional[str], auth_status: str, confidence_score: Optional[float], image_path: Optional[str] = None) -> None:
        try:
            conn = self._connect()
        except FileNotFoundError:
            logger.warning("Cannot log auth event because database is missing: %s", self.db_path)
            return

        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "device_auth_logs" not in tables:
                logger.warning("Cannot log auth event because device_auth_logs table is missing")
                return
            columns = self._table_columns(conn, "device_auth_logs")
            normalized_user_id: Optional[int]
            try:
                normalized_user_id = None if user_id is None else int(user_id)
            except (TypeError, ValueError):
                normalized_user_id = None
            fields = ["user_id", "auth_status", "confidence_score", "image_path", "sync_status"]
            values: List[Any] = [normalized_user_id, auth_status.upper(), confidence_score, image_path, 0]
            if "sync_key" in columns:
                fields.insert(0, "sync_key")
                values.insert(0, generate_sync_key())
            conn.execute(
                f"INSERT INTO device_auth_logs ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                values,
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Failed to log auth event: %s", exc)
        finally:
            conn.close()

    def log_surveillance_event(
        self,
        user_id: Optional[str],
        recognition_status: str,
        confidence_score: Optional[float],
        matched_template: Optional[str] = None,
        face_count: int = 1,
        bbox: Optional[List[int]] = None,
        image_path: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        try:
            conn = self._connect()
        except FileNotFoundError:
            logger.warning("Cannot log surveillance event because database is missing: %s", self.db_path)
            return

        try:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "device_surveillance_logs" not in tables:
                logger.warning("Cannot log surveillance event because device_surveillance_logs table is missing")
                return

            columns = self._table_columns(conn, "device_surveillance_logs")
            try:
                normalized_user_id = None if user_id is None else int(user_id)
            except (TypeError, ValueError):
                normalized_user_id = None

            fields = [
                "user_id",
                "recognition_status",
                "confidence_score",
                "matched_template",
                "face_count",
                "bbox",
                "image_path",
                "sync_status",
            ]
            values: List[Any] = [
                normalized_user_id,
                recognition_status.upper(),
                confidence_score,
                matched_template,
                int(face_count),
                json.dumps(bbox) if bbox is not None else None,
                image_path,
                0,
            ]
            if "sync_key" in columns:
                fields.insert(0, "sync_key")
                values.insert(0, generate_sync_key())
            if timestamp is not None and "timestamp" in columns:
                fields.insert(-1, "timestamp")
                values.insert(-1, timestamp)

            conn.execute(
                f"INSERT INTO device_surveillance_logs ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                values,
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Failed to log surveillance event: %s", exc)
        finally:
            conn.close()

    @staticmethod
    def _table_names(conn: sqlite3.Connection) -> set[str]:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}

    @staticmethod
    def _require_device_users(conn: sqlite3.Connection) -> set[str]:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='device_users'"
        ).fetchone()
        if table is None:
            raise DeviceUserDatabaseError("SQLite database is missing required table: device_users")
        columns = DeviceUserRepository._table_columns(conn, "device_users")
        if "user_id" not in columns:
            raise DeviceUserDatabaseError("device_users is missing required column: user_id")
        return columns

    def _templates_from_embedding_rows(self, rows: Iterable[sqlite3.Row]) -> List[FaceTemplate]:
        templates: List[FaceTemplate] = []
        for row in rows:
            embedding = self._vector_from_blob(row["embedding"])
            if embedding.size == 0:
                logger.warning("Skipping empty embedding for user %s", row["user_id"])
                continue
            user_id = str(row["user_id"])
            is_active = bool(int(row["is_active"])) if row["is_active"] is not None else True
            templates.append(
                FaceTemplate(
                    user_id=user_id,
                    identity=user_id,
                    template_name=str(row["template_name"]),
                    embedding=embedding,
                    is_active=is_active,
                )
            )
        return templates

    def _templates_from_row(
        self,
        row: sqlite3.Row,
        columns: set[str],
        embedding_columns: Iterable[str],
    ) -> List[FaceTemplate]:
        user_id = str(row["user_id"])
        identity = self._row_identity(row, columns, user_id)
        is_active = bool(int(row["is_active"])) if "is_active" in columns and row["is_active"] is not None else True
        default_template = self._row_template_name(row, columns)
        out: List[FaceTemplate] = []

        for column in embedding_columns:
            value = row[column]
            if value is None:
                continue
            parsed = self._parse_embedding_value(value, default_template)
            for template_name, embedding in parsed:
                if embedding.size == 0:
                    logger.warning("Skipping empty embedding for user %s", user_id)
                    continue
                out.append(
                    FaceTemplate(
                        user_id=user_id,
                        identity=identity,
                        template_name=template_name,
                        embedding=embedding,
                        is_active=is_active,
                    )
                )

        if not out:
            logger.warning("User %s has no readable embeddings", user_id)
        return out

    def _row_identity(self, row: sqlite3.Row, columns: set[str], fallback: str) -> str:
        for column in self.IDENTITY_COLUMNS:
            if column in columns and row[column] not in (None, ""):
                return str(row[column])
        return fallback

    def _row_template_name(self, row: sqlite3.Row, columns: set[str]) -> str:
        for column in self.TEMPLATE_COLUMNS:
            if column in columns and row[column] not in (None, ""):
                name = str(row[column])
                return Path(name).stem if "." in name else name
        return "front"

    def _parse_embedding_value(self, value: Any, default_template: str) -> List[Tuple[str, np.ndarray]]:
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, bytes):
            return [(default_template, self._vector_from_blob(value))]
        if isinstance(value, (list, tuple)):
            return self._vectors_from_json(value, default_template)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            try:
                decoded = json.loads(stripped)
                return self._vectors_from_json(decoded, default_template)
            except json.JSONDecodeError:
                pass
            try:
                raw = base64.b64decode(stripped, validate=True)
                return [(default_template, self._vector_from_blob(raw))]
            except Exception:
                pass
            try:
                vec = np.fromstring(stripped, sep=",", dtype=np.float32)
                return [(default_template, self._normalize(vec))]
            except Exception:
                logger.warning("Skipping corrupted embedding text")
                return []
        logger.warning("Skipping unsupported embedding value type: %s", type(value).__name__)
        return []

    def _vectors_from_json(self, value: Any, default_template: str) -> List[Tuple[str, np.ndarray]]:
        if isinstance(value, dict):
            if "embedding" in value:
                name = str(value.get("template_name") or value.get("template") or default_template)
                parsed = self._safe_json_vector(name, value["embedding"])
                return [] if parsed is None else [parsed]

            out: List[Tuple[str, np.ndarray]] = []
            for template_name, vector in value.items():
                if isinstance(vector, dict) and "embedding" in vector:
                    vector = vector["embedding"]
                parsed = self._safe_json_vector(str(template_name), vector)
                if parsed is not None:
                    out.append(parsed)
            return out

        if isinstance(value, list):
            if not value:
                return []
            if all(isinstance(item, (int, float)) for item in value):
                parsed = self._safe_json_vector(default_template, value)
                return [] if parsed is None else [parsed]

            out = []
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    name = str(item.get("template_name") or item.get("template") or item.get("pose") or f"template_{index}")
                    vector = item.get("embedding") or item.get("vector") or item.get("face_vector")
                    if vector is None:
                        continue
                    parsed = self._safe_json_vector(name, vector)
                else:
                    parsed = self._safe_json_vector(f"template_{index}", item)
                if parsed is not None:
                    out.append(parsed)
            return out

        return []

    def _safe_json_vector(self, template_name: str, value: Any) -> Optional[Tuple[str, np.ndarray]]:
        try:
            vector = self._normalize(np.asarray(value, dtype=np.float32))
        except Exception as exc:
            logger.warning("Skipping corrupted embedding for template %s: %s", template_name, exc)
            return None
        if vector.size == 0:
            logger.warning("Skipping empty embedding for template %s", template_name)
            return None
        return template_name, vector

    def _vector_from_blob(self, blob: bytes) -> np.ndarray:
        if len(blob) == 0 or len(blob) % 4 != 0:
            logger.warning("Skipping corrupted embedding BLOB of %s bytes", len(blob))
            return np.empty((0,), dtype=np.float32)
        return self._normalize(np.frombuffer(blob, dtype=np.float32).copy())

    @staticmethod
    def _normalize(vector: np.ndarray) -> np.ndarray:
        vec = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if norm <= 1e-12:
            return vec
        return vec / norm
