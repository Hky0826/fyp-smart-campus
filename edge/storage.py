# edge/storage.py
"""SQLite storage manager for embeddings and logs, modified to use sync schemas."""

from __future__ import annotations

import sqlite3
from typing import List, Tuple, Optional
import numpy as np

class StorageManager:
    def __init__(self, db_path: str = 'device_local.db'):
        self.db_path = db_path

    def ensure_schema(self) -> None:
        """
        Creates SQLite tables according to sync specifications if not already present.
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS device_users (
                user_id INTEGER PRIMARY KEY NOT NULL,
                face_vector BLOB NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS device_auth_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES device_users(user_id) ON DELETE SET NULL,
                auth_status TEXT NOT NULL,
                confidence_score REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sync_status INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()

    def load_embeddings(self) -> List[Tuple[int, np.ndarray, int]]:
        """
        Loads user face vectors from the unified device_users table.
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id, face_vector, is_active FROM device_users")
            rows = cur.fetchall()
        except sqlite3.OperationalError as e:
            print(f"[ERROR] Failed to load embeddings: {e}")
            conn.close()
            return []
        
        conn.close()
        out = []
        for user_id, blob, is_active in rows:
            if blob is None or len(blob) == 0:
                continue
            # Reconstruct numpy vector array from SQLite binary BLOB
            vec = np.frombuffer(blob, dtype=np.float32)
            out.append((int(user_id), vec, int(is_active)))
        return out

    def log_event(self, user_id: Optional[int], auth_status: str, confidence_score: float) -> None:
        """
        Logs authentication event locally to device_auth_logs with sync_status = 0 (Pending sync).
        """
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            # Enforce foreign key constraints inside this connection
            cur.execute("PRAGMA foreign_keys = ON;")
            cur.execute(
                "INSERT INTO device_auth_logs (user_id, auth_status, confidence_score, sync_status) VALUES (?, ?, ?, 0)",
                (user_id, auth_status, float(confidence_score)),
            )
            conn.commit()
        except sqlite3.OperationalError as e:
            print('[WARN] device_auth_logs error; event:', user_id, auth_status, confidence_score, e)
        except sqlite3.IntegrityError as e:
            # Foreign key violation (e.g. user_id not in device_users cache)
            # Log as offline failed event without referencing invalid user_id
            try:
                cur.execute(
                    "INSERT INTO device_auth_logs (user_id, auth_status, confidence_score, sync_status) VALUES (NULL, ?, ?, 0)",
                    (auth_status, float(confidence_score)),
                )
                conn.commit()
                print(f"[INFO] Buffered invalid FK user {user_id} event under NULL user reference.")
            except Exception as ex:
                print('[ERROR] Hard write error on SQLite constraint recovery:', ex)
        finally:
            conn.close()
