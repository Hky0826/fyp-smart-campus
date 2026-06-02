"""SQLite storage manager for embeddings and logs."""

from __future__ import annotations

import sqlite3
from typing import List, Tuple, Optional

import numpy as np


class StorageManager:
    def __init__(self, db_path: str = 'edge_local.db'):
        self.db_path = db_path

    def ensure_schema(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_users (
                user_id INTEGER PRIMARY KEY NOT NULL,
                role_name TEXT NOT NULL,
                face_vector BLOB NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_auth_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES edge_users(user_id),
                auth_status TEXT NOT NULL,
                confidence_score REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                sync_status INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()

    def load_embeddings(self) -> List[Tuple[int, np.ndarray]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id, face_vector FROM edge_users WHERE is_active=1")
        except sqlite3.OperationalError:
            try:
                # Fallback to the legacy schema (active column instead of is_active)
                cur.execute("SELECT user_id, face_vector FROM edge_users WHERE active=1")
            except sqlite3.OperationalError as e:
                print(f"[ERROR] Failed to load embeddings: {e}")
                conn.close()
                return []
        rows = cur.fetchall()
        conn.close()
        out = []
        for user_id, blob in rows:
            if blob is None:
                continue
            vec = np.frombuffer(blob, dtype=np.float32)
            out.append((int(user_id), vec))
        return out

    def log_event(self, user_id: Optional[int], auth_status: str, confidence_score: float) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO edge_auth_logs (user_id, auth_status, confidence_score, sync_status) VALUES (?, ?, ?, 0)",
                (user_id, auth_status, float(confidence_score)),
            )
            conn.commit()
        except sqlite3.OperationalError:
            print('[WARN] edge_auth_logs missing; event:', user_id, auth_status, confidence_score)
        finally:
            conn.close()
