-- =========================================================================
-- EDGE DEVICE SQLITE DATABASE SETUP SCRIPT
-- Target Engine: SQLite 3.x
-- Source: database.docx updated Edge SQLite schema
-- =========================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Table 3.41: device_users
CREATE TABLE IF NOT EXISTS device_users (
    user_id INTEGER PRIMARY KEY NOT NULL,
    is_active INTEGER DEFAULT 1 NOT NULL CHECK (is_active IN (0, 1)),
    visitor_start DATETIME NULL,
    visitor_expiry DATETIME NULL,
    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Table 3.48: device_roles
CREATE TABLE IF NOT EXISTS device_roles (
    role_id INTEGER PRIMARY KEY NOT NULL,
    role_name TEXT NOT NULL,
    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Table 3.42: device_user_face_embeddings
CREATE TABLE IF NOT EXISTS device_user_face_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    user_id INTEGER NOT NULL,
    template_name TEXT NOT NULL,
    model_name TEXT NOT NULL CHECK (model_name IN ('openvc_sface', 'opencv_sface', 'sface', 'arcface_mobilefacenet', 'arcface_r50')),
    embedding BLOB NOT NULL,
    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, template_name, model_name),
    FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE CASCADE ON UPDATE CASCADE
);

-- Table 3.43: device_user_roles
CREATE TABLE IF NOT EXISTS device_user_roles (
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE ON UPDATE CASCADE
);

-- Table 3.44: device_auth_logs
CREATE TABLE IF NOT EXISTS device_auth_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    sync_key TEXT UNIQUE NOT NULL,
    user_id INTEGER NULL,
    auth_status TEXT NOT NULL CHECK (auth_status IN ('SUCCESS', 'FAILED', 'SPOOFING')),
    confidence_score REAL NULL,
    face_count INTEGER DEFAULT 1 NOT NULL,
    reason TEXT NULL,
    spoofing_checked INTEGER DEFAULT 1 NOT NULL CHECK (spoofing_checked IN (0, 1)),
    spoofing_passed INTEGER NULL CHECK (spoofing_passed IS NULL OR spoofing_passed IN (0, 1)),
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    image_path TEXT NULL,
    node_id INTEGER NULL,
    policy_version TEXT NULL,
    decision_reason TEXT NULL,
    correlation_id TEXT NULL,
    sync_status INTEGER DEFAULT 0 NOT NULL CHECK (sync_status IN (0, 1)),
    synced_at DATETIME NULL,
    FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE SET NULL ON UPDATE CASCADE
);

-- Table 3.45: device_surveillance_logs
CREATE TABLE IF NOT EXISTS device_surveillance_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    sync_key TEXT UNIQUE NOT NULL,
    user_id INTEGER NULL,
    recognition_status TEXT NOT NULL CHECK (recognition_status IN ('RECOGNIZED', 'UNKNOWN')),
    confidence_score REAL NULL,
    matched_template TEXT NULL,
    face_count INTEGER DEFAULT 1 NOT NULL,
    bbox TEXT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    image_path TEXT NULL,
    sync_status INTEGER DEFAULT 0 NOT NULL CHECK (sync_status IN (0, 1)),
    synced_at DATETIME NULL,
    FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE SET NULL ON UPDATE CASCADE
);

-- Table 3.46: device_info
CREATE TABLE IF NOT EXISTS device_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    device_name TEXT NOT NULL,
    node_id INTEGER NOT NULL,
    location_name TEXT NOT NULL,
    last_cloud_sync DATETIME NULL,
    policy_version TEXT NULL
);

-- Table 3.47: device_node_rbac
CREATE TABLE IF NOT EXISTS device_node_rbac (
    node_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (node_id, role_id),
    FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE ON UPDATE CASCADE
);

-- Table 3.49: device_rbac (Device-level Access Control)
CREATE TABLE IF NOT EXISTS device_rbac (
    device_id TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (device_id, role_id),
    FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE ON UPDATE CASCADE
);

-- Local sync worker bookkeeping; not synced to the cloud database.
CREATE TABLE IF NOT EXISTS sync_metadata (
    key TEXT PRIMARY KEY,
    val TEXT
);

-- Replay protection for authenticated cloud-to-edge control requests.
CREATE TABLE IF NOT EXISTS edge_control_nonces (
    nonce TEXT PRIMARY KEY,
    expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_device_user_face_embeddings_user_id
    ON device_user_face_embeddings(user_id);

CREATE INDEX IF NOT EXISTS idx_device_user_roles_role_id
    ON device_user_roles(role_id);

CREATE INDEX IF NOT EXISTS idx_device_auth_logs_sync_status
    ON device_auth_logs(sync_status);

CREATE INDEX IF NOT EXISTS idx_device_auth_logs_timestamp
    ON device_auth_logs(timestamp);

CREATE INDEX IF NOT EXISTS idx_device_surveillance_logs_sync_status
    ON device_surveillance_logs(sync_status);

CREATE INDEX IF NOT EXISTS idx_device_surveillance_logs_timestamp
    ON device_surveillance_logs(timestamp);

CREATE INDEX IF NOT EXISTS idx_device_node_rbac_role_id
    ON device_node_rbac(role_id);

CREATE INDEX IF NOT EXISTS idx_device_rbac_role_id
    ON device_rbac(role_id);
