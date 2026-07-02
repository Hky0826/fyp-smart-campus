"""One-time setup utility for the edge SQLite database."""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from typing import Optional

try:
    from edge.facial_recognition.src.utils.sync_key import generate_sync_key
except ModuleNotFoundError:  # Allows `python edge/facial_recognition/setup_sqlite.py` from repo root.
    from src.utils.sync_key import generate_sync_key


EDGE_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = EDGE_ROOT / "setup_sqlite.sql"
DEFAULT_DB_PATH = EDGE_ROOT / "data" / "device_local.db"
DEFAULT_EMBEDDING_MODEL = "arcface_r50"


def default_database_path() -> Path:
    configured = os.getenv("EDGE_HAILO_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DB_PATH


def table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}


def backfill_missing_sync_keys(cursor: sqlite3.Cursor, table_name: str) -> None:
    columns = table_columns(cursor, table_name)
    if "sync_key" not in columns or "log_id" not in columns:
        return

    rows = cursor.execute(
        f"""
        SELECT log_id
        FROM {table_name}
        WHERE sync_key IS NULL OR sync_key = ''
        """
    ).fetchall()
    for (log_id,) in rows:
        cursor.execute(f"UPDATE {table_name} SET sync_key = ? WHERE log_id = ?", (generate_sync_key(), log_id))


def add_column_if_missing(cursor: sqlite3.Cursor, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in table_columns(cursor, table_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def migrate_legacy_schema(cursor: sqlite3.Cursor) -> None:
    add_column_if_missing(cursor, "device_users", "is_active", "INTEGER DEFAULT 1 NOT NULL")
    add_column_if_missing(cursor, "device_users", "last_synced_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")

    auth_migrations = {
        "sync_key": "TEXT",
        "face_count": "INTEGER DEFAULT 1 NOT NULL",
        "reason": "TEXT",
        "spoofing_checked": "INTEGER DEFAULT 1 NOT NULL",
        "spoofing_passed": "INTEGER",
        "image_path": "TEXT",
        "synced_at": "DATETIME",
    }
    for column_name, definition in auth_migrations.items():
        add_column_if_missing(cursor, "device_auth_logs", column_name, definition)
    backfill_missing_sync_keys(cursor, "device_auth_logs")
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_device_auth_logs_sync_key
        ON device_auth_logs(sync_key)
        WHERE sync_key IS NOT NULL
        """
    )

    surveillance_migrations = {
        "sync_key": "TEXT",
        "matched_template": "TEXT",
        "face_count": "INTEGER DEFAULT 1 NOT NULL",
        "bbox": "TEXT",
        "image_path": "TEXT",
        "sync_status": "INTEGER DEFAULT 0 NOT NULL",
        "synced_at": "DATETIME",
    }
    for column_name, definition in surveillance_migrations.items():
        add_column_if_missing(cursor, "device_surveillance_logs", column_name, definition)
    backfill_missing_sync_keys(cursor, "device_surveillance_logs")
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_device_surveillance_logs_sync_key
        ON device_surveillance_logs(sync_key)
        WHERE sync_key IS NOT NULL
        """
    )

    user_columns = table_columns(cursor, "device_users")
    if "face_vector" in user_columns:
        template_expr = "COALESCE(NULLIF(template_name, ''), 'front')" if "template_name" in user_columns else "'front'"
        synced_expr = "last_synced_at" if "last_synced_at" in user_columns else "CURRENT_TIMESTAMP"
        cursor.execute(
            f"""
            INSERT OR IGNORE INTO device_user_face_embeddings (
                user_id,
                template_name,
                model_name,
                embedding,
                last_synced_at
            )
            SELECT
                user_id,
                {template_expr},
                ?,
                face_vector,
                {synced_expr}
            FROM device_users
            WHERE face_vector IS NOT NULL AND length(face_vector) > 0
            """,
            (DEFAULT_EMBEDDING_MODEL,),
        )


def initialize_sqlite_database(db_path: Optional[str | Path] = None) -> Path:
    resolved_path = Path(db_path).expanduser() if db_path is not None else default_database_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(resolved_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        migrate_legacy_schema(conn.cursor())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return resolved_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up the Edge SQLite database schema")
    parser.add_argument(
        "--database",
        "-d",
        default=None,
        help="SQLite database path. Defaults to EDGE_HAILO_DB_PATH or edge/facial_recognition/data/device_local.db.",
    )
    args = parser.parse_args()

    db_path = initialize_sqlite_database(args.database)
    print(f"Edge SQLite database is ready: {db_path}")


if __name__ == "__main__":
    main()
