"""Prepare the local cloud database without destroying existing data.

This is intentionally separate from ``app.db_init``.  That legacy initializer
drops tables and is suitable only for a disposable development database.  The
startup launcher uses this script so it can be run repeatedly on a laptop or
deployment without resetting users, devices, logs, or documents.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import mysql.connector
from sqlalchemy import inspect, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.core.database import Base, engine  # noqa: E402
from app.models import models as _models  # noqa: F401,E402


MIGRATION_TABLE = "smart_campus_schema_migrations"
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_$]+$")


def _identifier(value: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise RuntimeError(f"Unsafe MySQL identifier in configuration: {value!r}")
    return f"`{value}`"


def create_database() -> None:
    """Create the configured database if necessary, without changing data."""

    connection = mysql.connector.connect(
        host=settings.DB_HOST,
        port=int(settings.DB_PORT),
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
    )
    try:
        cursor = connection.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS {_identifier(settings.DB_NAME)} "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        connection.commit()
        cursor.close()
    finally:
        connection.close()


def table_exists(connection, table: str) -> bool:
    return inspect(connection).has_table(table)


def column_exists(connection, table: str, column: str) -> bool:
    if not table_exists(connection, table):
        return False
    return any(item["name"] == column for item in inspect(connection).get_columns(table))


def index_exists(connection, table: str, index_name: str) -> bool:
    if not table_exists(connection, table):
        return False
    inspector = inspect(connection)
    return any(item.get("name") == index_name for item in inspector.get_indexes(table))


def add_column_if_missing(connection, table: str, column: str, definition: str) -> None:
    if table_exists(connection, table) and not column_exists(connection, table, column):
        connection.execute(text(f"ALTER TABLE {_identifier(table)} ADD COLUMN {_identifier(column)} {definition}"))


def create_security_tables(connection) -> None:
    if table_exists(connection, "devices") and not table_exists(connection, "device_request_nonces"):
        connection.execute(
            text(
                """CREATE TABLE device_request_nonces (
                    device_id VARCHAR(100) NOT NULL,
                    nonce VARCHAR(128) NOT NULL,
                    expires_at DATETIME NOT NULL,
                    PRIMARY KEY (device_id, nonce),
                    CONSTRAINT fk_device_nonce_device
                        FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
                ) ENGINE=InnoDB"""
            )
        )

    if table_exists(connection, "devices") and table_exists(connection, "users") and not table_exists(connection, "face_auth_challenges"):
        connection.execute(
            text(
                """CREATE TABLE face_auth_challenges (
                    challenge_id VARCHAR(64) PRIMARY KEY,
                    device_id VARCHAR(100) NOT NULL,
                    user_id INT NOT NULL,
                    expires_at DATETIME NOT NULL,
                    used_at DATETIME NULL,
                    match_passed BOOLEAN NOT NULL DEFAULT FALSE,
                    liveness_passed BOOLEAN NOT NULL DEFAULT FALSE,
                    pad_model_version VARCHAR(100) NULL,
                    pad_score FLOAT NULL,
                    CONSTRAINT fk_face_challenge_device
                        FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE,
                    CONSTRAINT fk_face_challenge_user
                        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                ) ENGINE=InnoDB"""
            )
        )


def run_one_migration(connection, migration_name: str) -> None:
    """Apply the checked-in migrations using idempotent schema checks."""

    if migration_name == "20260719_multi_model_embeddings.sql":
        if table_exists(connection, "user_face_embeddings") and column_exists(connection, "user_face_embeddings", "model_name"):
            connection.execute(
                text(
                    "ALTER TABLE user_face_embeddings MODIFY COLUMN model_name "
                    "ENUM('arcface_mobilefacenet', 'arcface_r50', 'openvc_sface', 'auraface') NOT NULL"
                )
            )
        if column_exists(connection, "users", "username"):
            connection.execute(text("ALTER TABLE users DROP COLUMN username"))

    elif migration_name == "20260720_widen_log_sync_keys.sql":
        for table in ("authentication_logs", "surveillance_logs"):
            if table_exists(connection, table) and column_exists(connection, table, "sync_key"):
                connection.execute(text(f"ALTER TABLE {_identifier(table)} MODIFY COLUMN sync_key VARCHAR(64) NOT NULL"))

    elif migration_name == "20260728_security_hardening.sql":
        add_column_if_missing(connection, "devices", "device_secret_ciphertext", "TEXT NULL")
        add_column_if_missing(connection, "devices", "credential_rotated_at", "DATETIME NULL")
        add_column_if_missing(connection, "jwt_sessions", "session_uuid", "VARCHAR(64) NULL")
        add_column_if_missing(connection, "jwt_sessions", "jti", "VARCHAR(64) NULL")
        add_column_if_missing(connection, "jwt_sessions", "principal_type", "VARCHAR(32) NOT NULL DEFAULT 'ADMIN'")
        if table_exists(connection, "jwt_sessions"):
            connection.execute(text("UPDATE jwt_sessions SET is_revoked = 1"))
            if not index_exists(connection, "jwt_sessions", "uq_jwt_sessions_session_uuid"):
                connection.execute(text("CREATE UNIQUE INDEX uq_jwt_sessions_session_uuid ON jwt_sessions(session_uuid)"))
            if not index_exists(connection, "jwt_sessions", "uq_jwt_sessions_jti"):
                connection.execute(text("CREATE UNIQUE INDEX uq_jwt_sessions_jti ON jwt_sessions(jti)"))
        create_security_tables(connection)
        add_column_if_missing(connection, "chatbot_queries", "query_hash", "VARCHAR(64) NULL")
        add_column_if_missing(connection, "chatbot_queries", "query_length", "INT NULL")
        add_column_if_missing(connection, "chatbot_queries", "query_category", "VARCHAR(32) NULL")

    elif migration_name == "20260728_face_auth_challenges.sql":
        create_security_tables(connection)

    elif migration_name == "20260728_private_data.sql":
        # This migration currently contains the same chatbot metadata changes
        # as the security migration.  Keep it tracked for existing deployments.
        add_column_if_missing(connection, "chatbot_queries", "query_hash", "VARCHAR(64) NULL")
        add_column_if_missing(connection, "chatbot_queries", "query_length", "INT NULL")
        add_column_if_missing(connection, "chatbot_queries", "query_category", "VARCHAR(32) NULL")

    else:
        raise RuntimeError(f"No safe handler exists for migration {migration_name}")


def run_migrations() -> None:
    migrations = [
        "20260719_multi_model_embeddings.sql",
        "20260720_widen_log_sync_keys.sql",
        "20260728_security_hardening.sql",
        "20260728_face_auth_challenges.sql",
        "20260728_private_data.sql",
    ]

    with engine.begin() as connection:
        connection.execute(
            text(
                f"""CREATE TABLE IF NOT EXISTS {_identifier(MIGRATION_TABLE)} (
                    migration_name VARCHAR(255) PRIMARY KEY,
                    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB"""
            )
        )
        applied = {
            row[0]
            for row in connection.execute(text(f"SELECT migration_name FROM {_identifier(MIGRATION_TABLE)}"))
        }
        for migration_name in migrations:
            if migration_name in applied:
                continue
            run_one_migration(connection, migration_name)
            connection.execute(
                text(
                    f"INSERT INTO {_identifier(MIGRATION_TABLE)} (migration_name) VALUES (:migration_name)"
                ),
                {"migration_name": migration_name},
            )
            print(f"Applied cloud migration: {migration_name}")


def main() -> int:
    settings.validate_security()
    create_database()
    Base.metadata.create_all(bind=engine)
    run_migrations()
    print(f"Cloud database ready: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Cloud preparation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
