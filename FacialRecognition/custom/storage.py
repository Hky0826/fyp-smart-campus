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
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                face_vector BLOB,
                active INTEGER DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS edge_auth_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                auth_status TEXT,
                confidence_score REAL,
                timestamp TEXT DEFAULT (datetime('now')),
                sync_status INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()

    def load_embeddings(self) -> List[Tuple[int, np.ndarray]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id, face_vector FROM edge_users WHERE active=1")
        except sqlite3.OperationalError:
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
