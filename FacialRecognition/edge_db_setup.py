# edge_db_setup.py  — run once on the edge device
import sqlite3

def initialize_edge_db():
    # Connects to or creates the local SQLite file
    conn = sqlite3.connect("edge_local.db") 
    cur = conn.cursor()

    # Execute the updated schema based on Section 7 of the proposal
    cur.executescript("""
        PRAGMA journal_mode = WAL;    -- Optimizes concurrent reads/writes
        PRAGMA foreign_keys = ON;     -- Enforces relational constraints

        -- Table E.1: edge_users 
        -- Stores flattened user profile and biometric vector for offline matching
        CREATE TABLE IF NOT EXISTS edge_users (
            user_id         INTEGER PRIMARY KEY NOT NULL,
            role_name       TEXT NOT NULL,
            face_vector     BLOB NOT NULL,
            is_active       INTEGER NOT NULL DEFAULT 1,
            last_synced_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- Table E.2: edge_auth_logs
        -- Buffers local authentication events until pushed to the cloud
        CREATE TABLE IF NOT EXISTS edge_auth_logs (
            log_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER REFERENCES edge_users(user_id),
            auth_status      TEXT NOT NULL,    -- 'SUCCESS', 'FAILED', or 'SPOOFING'
            confidence_score REAL,
            timestamp        DATETIME DEFAULT CURRENT_TIMESTAMP,
            sync_status      INTEGER NOT NULL DEFAULT 0  -- 0 = pending, 1 = pushed
        );

        -- Table E.3: edge_device_info
        -- Caches device context for JWT generation and spatial routing
        CREATE TABLE IF NOT EXISTS edge_device_info (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id          TEXT NOT NULL,
            device_name        TEXT NOT NULL,
            location_id        INTEGER NOT NULL,
            location_name      TEXT NOT NULL,
            navigation_node_id TEXT,
            last_cloud_sync    DATETIME
        );
    """)

    conn.commit()
    conn.close()
    print("Edge SQLite database schema successfully updated and ready.")

if __name__ == "__main__":
    initialize_edge_db()