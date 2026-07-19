PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS device_users(
 user_id INTEGER PRIMARY KEY NOT NULL,
 display_name TEXT,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN(0,1)),
 last_synced_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS device_user_face_embeddings(
 embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 template_name TEXT NOT NULL,
 model_name TEXT NOT NULL,
 model_version TEXT NOT NULL,
 embedding_dimension INTEGER NOT NULL,
 embedding BLOB NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 quality_metadata_json TEXT,
 last_synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(user_id,template_name,model_name,model_version),
 FOREIGN KEY(user_id) REFERENCES device_users(user_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS device_roles(role_id INTEGER PRIMARY KEY,role_name TEXT NOT NULL,last_synced_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS device_user_roles(user_id INTEGER NOT NULL,role_id INTEGER NOT NULL,last_synced_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,role_id),FOREIGN KEY(user_id) REFERENCES device_users(user_id) ON DELETE CASCADE,FOREIGN KEY(role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS device_node_rbac(node_id INTEGER NOT NULL,role_id INTEGER NOT NULL,last_synced_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(node_id,role_id),FOREIGN KEY(role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS device_info(id INTEGER PRIMARY KEY AUTOINCREMENT,device_id TEXT NOT NULL,device_name TEXT NOT NULL,node_id INTEGER,location_name TEXT,last_cloud_sync TEXT);
CREATE TABLE IF NOT EXISTS device_auth_logs(
 log_id INTEGER PRIMARY KEY AUTOINCREMENT,sync_key TEXT UNIQUE NOT NULL,user_id INTEGER,
 auth_status TEXT NOT NULL CHECK(auth_status IN('SUCCESS','FAILED','SPOOFING','ERROR')),
 confidence_score REAL,face_count INTEGER NOT NULL DEFAULT 1,reason TEXT,
 spoofing_checked INTEGER NOT NULL DEFAULT 0,spoofing_passed INTEGER,image_path TEXT,
 timestamp TEXT DEFAULT CURRENT_TIMESTAMP,sync_status INTEGER NOT NULL DEFAULT 0 CHECK(sync_status IN(0,1)),synced_at TEXT,
 FOREIGN KEY(user_id) REFERENCES device_users(user_id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS sync_metadata(key TEXT PRIMARY KEY,val TEXT);
CREATE INDEX IF NOT EXISTS idx_embeddings_user ON device_user_face_embeddings(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_unsynced ON device_auth_logs(sync_status,timestamp);