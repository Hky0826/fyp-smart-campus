# edge_db_setup.py  — run once on the edge device
import sqlite3

conn = sqlite3.connect("edge_local.db")   # creates the file if not exists
cur = conn.cursor()

cur.executescript("""
    PRAGMA journal_mode = WAL;    -- better for concurrent reads
    PRAGMA foreign_keys = ON;

    -- Minimal user table for offline face matching
    CREATE TABLE IF NOT EXISTS users (
        user_id    INTEGER PRIMARY KEY,
        full_name  TEXT NOT NULL,
        role_name  TEXT NOT NULL
    );

    -- Synced face embeddings from MySQL (pulled during enrollment)
    CREATE TABLE IF NOT EXISTS face_embeddings (
        embedding_id   INTEGER PRIMARY KEY,
        user_id        INTEGER NOT NULL REFERENCES users(user_id),
        embedding_blob BLOB NOT NULL,
        synced_at      TEXT DEFAULT (datetime('now'))
    );

    -- Local auth events buffered until cloud sync
    CREATE TABLE IF NOT EXISTS auth_events_buffer (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER,
        event_type   TEXT NOT NULL,
        similarity   REAL,
        logged_at    TEXT DEFAULT (datetime('now')),
        synced       INTEGER DEFAULT 0    -- 0 = pending, 1 = pushed to MySQL
    );
""")

conn.commit()
conn.close()
print("Edge SQLite database ready.")