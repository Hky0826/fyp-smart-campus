# edge/edge_sync_client.py
"""Unified database synchronization client engine for Edge Devices."""

import os
import sys
import sqlite3
import base64
import logging
import time
import threading
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import requests

import uvicorn
from fastapi import FastAPI, APIRouter, HTTPException, status
from pydantic import BaseModel

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EdgeSyncEngine")

# =====================================================================
# Database Interfaces & SQLite Unified Implementation
# =====================================================================

class AbstractEdgeDB(ABC):
    @abstractmethod
    def initialize_schema(self) -> None:
        pass

    @abstractmethod
    def save_users_delta(self, users: List[Dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def save_roles_delta(self, roles: List[Dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def save_rbac_delta(self, rbac: List[Dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def deactivate_user_instantly(self, user_id: int) -> bool:
        pass

    @abstractmethod
    def delete_users_locally(self, user_ids: List[int]) -> None:
        pass

    @abstractmethod
    def get_last_sync_timestamp(self) -> Optional[str]:
        pass

    @abstractmethod
    def update_last_sync_timestamp(self, timestamp: str) -> None:
        pass

    @abstractmethod
    def log_authentication_event(self, user_id: Optional[int], auth_status: str, confidence_score: Optional[float], timestamp: Any) -> int:
        pass

    @abstractmethod
    def get_unsynced_logs(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def mark_logs_as_synced(self, log_ids: List[int]) -> None:
        pass


class SQLiteEdgeDB(AbstractEdgeDB):
    """
    Consolidated SQLite storage and transaction system.
    Supports thread safety locks and WAL optimization mode.
    """
    def __init__(self, db_path: str = "device_local.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.initialize_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def initialize_schema(self) -> None:
        """
        Creates all 6 SQLite tables detailed in reference specifications.
        """
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # 1. device_users
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS device_users (
                        user_id INTEGER PRIMARY KEY NOT NULL,
                        face_vector BLOB NOT NULL,
                        is_active INTEGER DEFAULT 1 NOT NULL,
                        last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # 2. device_roles
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS device_roles (
                        role_id INTEGER PRIMARY KEY NOT NULL,
                        role_name TEXT NOT NULL,
                        last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # 3. device_user_roles
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS device_user_roles (
                        user_id INTEGER NOT NULL,
                        role_id INTEGER NOT NULL,
                        last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (user_id, role_id),
                        FOREIGN KEY (role_id) REFERENCES device_roles(role_id) ON DELETE CASCADE
                    );
                """)
                # 4. device_auth_logs
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS device_auth_logs (
                        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        auth_status TEXT NOT NULL,
                        confidence_score REAL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        sync_status INTEGER DEFAULT 0 NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES device_users(user_id) ON DELETE SET NULL
                    );
                """)
                # 5. device_info
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS device_info (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL,
                        device_name TEXT NOT NULL,
                        node_id INTEGER NOT NULL,
                        location_name TEXT NOT NULL,
                        last_cloud_sync DATETIME
                    );
                """)
                # 6. device_node_rbac
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS device_node_rbac (
                        node_id INTEGER NOT NULL,
                        role_id INTEGER NOT NULL,
                        last_synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (node_id, role_id)
                    );
                """)
                # Metadata
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sync_metadata (
                        key TEXT PRIMARY KEY,
                        val TEXT
                    );
                """)
                conn.commit()
                logger.info("SQLite storage schemas initialized successfully.")
            except Exception as e:
                conn.rollback()
                logger.error(f"Error initializing SQLite schema: {str(e)}")
                raise e
            finally:
                conn.close()

    # Downstream Sync Operations
    def save_users_delta(self, users: List[Dict[str, Any]]) -> None:
        if not users:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                for u in users:
                    user_id = u["user_id"]
                    is_active = u["is_active"]
                    face_vector_b64 = u["face_vector_b64"]
                    
                    if face_vector_b64:
                        face_bytes = base64.b64decode(face_vector_b64)
                        cursor.execute("""
                            INSERT INTO device_users (user_id, face_vector, is_active, last_synced_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_id) DO UPDATE SET
                                face_vector=excluded.face_vector,
                                is_active=excluded.is_active,
                                last_synced_at=CURRENT_TIMESTAMP
                        """, (user_id, face_bytes, is_active))
                    else:
                        cursor.execute("""
                            INSERT INTO device_users (user_id, face_vector, is_active, last_synced_at)
                            VALUES (?, x'', ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_id) DO UPDATE SET
                                is_active=excluded.is_active,
                                last_synced_at=CURRENT_TIMESTAMP
                        """, (user_id, is_active))
                conn.commit()
                logger.info(f"Successfully processed delta update for {len(users)} users.")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to commit users delta: {str(e)}")
                raise e
            finally:
                conn.close()

    def save_roles_delta(self, roles: List[Dict[str, Any]]) -> None:
        if not roles:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                for r in roles:
                    cursor.execute("""
                        INSERT INTO device_roles (role_id, role_name, last_synced_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(role_id) DO UPDATE SET
                            role_name=excluded.role_name,
                            last_synced_at=CURRENT_TIMESTAMP
                    """, (r["role_id"], r["role_name"]))
                conn.commit()
                logger.info(f"Processed delta update for {len(roles)} roles.")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to commit roles delta: {str(e)}")
                raise e
            finally:
                conn.close()

    def save_rbac_delta(self, rbac: List[Dict[str, Any]]) -> None:
        if not rbac:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM device_node_rbac")
                for rb in rbac:
                    cursor.execute("""
                        INSERT INTO device_node_rbac (node_id, role_id, last_synced_at)
                        VALUES (?, ?, CURRENT_TIMESTAMP)
                    """, (rb["node_id"], rb["role_id"]))
                conn.commit()
                logger.info(f"Processed delta update for {len(rbac)} RBAC entries.")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to commit RBAC delta: {str(e)}")
                raise e
            finally:
                conn.close()

    def deactivate_user_instantly(self, user_id: int) -> bool:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE device_users 
                    SET is_active = 0, last_synced_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (user_id,))
                success = cursor.rowcount > 0
                conn.commit()
                if success:
                    logger.info(f"User {user_id} INSTANTLY deactivated in local SQLite.")
                else:
                    logger.warning(f"Deactivation failed: User {user_id} not cached locally.")
                return success
            except Exception as e:
                conn.rollback()
                logger.error(f"Database error during instant deactivation: {str(e)}")
                return False
            finally:
                conn.close()

    def delete_users_locally(self, user_ids: List[int]) -> None:
        if not user_ids:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in user_ids)
                cursor.execute(f"DELETE FROM device_users WHERE user_id IN ({placeholders})", user_ids)
                cursor.execute(f"DELETE FROM device_user_roles WHERE user_id IN ({placeholders})", user_ids)
                conn.commit()
                logger.info(f"Deleted {len(user_ids)} users from local database: {user_ids}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to delete local users: {str(e)}")
                raise e
            finally:
                conn.close()

    def get_last_sync_timestamp(self) -> Optional[str]:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT val FROM sync_metadata WHERE key = 'last_synced_at'")
                row = cursor.fetchone()
                return row[0] if row else None
            finally:
                conn.close()

    def update_last_sync_timestamp(self, timestamp: str) -> None:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO sync_metadata (key, val) VALUES ('last_synced_at', ?)
                    ON CONFLICT(key) DO UPDATE SET val = excluded.val
                """, (timestamp,))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to save sync timestamp: {str(e)}")
            finally:
                conn.close()

    # Upstream Sync Operations
    def log_authentication_event(self, user_id: Optional[int], auth_status: str, confidence_score: Optional[float], timestamp: Any) -> int:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                ts_str = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
                cursor.execute("""
                    INSERT INTO device_auth_logs (user_id, auth_status, confidence_score, timestamp, sync_status)
                    VALUES (?, ?, ?, ?, 0)
                """, (user_id, auth_status.upper(), confidence_score, ts_str))
                conn.commit()
                last_id = cursor.lastrowid
                logger.info(f"Buffered auth event locally: User {user_id}, Status {auth_status}, Log ID {last_id}")
                return last_id
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to buffer authentication log locally: {str(e)}")
                raise e
            finally:
                conn.close()

    def get_unsynced_logs(self) -> List[Dict[str, Any]]:
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT log_id, user_id, auth_status, confidence_score, timestamp
                    FROM device_auth_logs
                    WHERE sync_status = 0
                    ORDER BY timestamp ASC
                """)
                rows = cursor.fetchall()
                logs = []
                for r in rows:
                    logs.append({
                        "log_id": r[0],
                        "user_id": r[1],
                        "auth_status": r[2],
                        "confidence_score": r[3],
                        "timestamp": r[4]
                    })
                return logs
            except Exception as e:
                logger.error(f"Error fetching unsynced logs: {str(e)}")
                return []
            finally:
                conn.close()

    def mark_logs_as_synced(self, log_ids: List[int]) -> None:
        if not log_ids:
            return
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                placeholders = ",".join("?" for _ in log_ids)
                cursor.execute(f"""
                    UPDATE device_auth_logs
                    SET sync_status = 1
                    WHERE log_id IN ({placeholders})
                """, log_ids)
                conn.commit()
                logger.debug(f"Flipped local sync status for logs: {log_ids}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to commit local sync status update: {str(e)}")
                raise e
            finally:
                conn.close()


# =====================================================================
# Push Notification Listener (Uvicorn Endpoint on Edge Device)
# =====================================================================

class DeactivatePayload(BaseModel):
    user_id: int
    is_active: int

def create_edge_app(db: AbstractEdgeDB) -> FastAPI:
    app = FastAPI(title="Edge Device Receiver Daemon")
    
    @app.post("/api/edge/deactivate")
    def handle_deactivation(payload: DeactivatePayload):
        if payload.is_active == 0:
            success = db.deactivate_user_instantly(payload.user_id)
            if success:
                return {"status": "success", "message": f"User {payload.user_id} deactivated locally"}
            else:
                return {"status": "not_found", "message": f"User {payload.user_id} not cached locally"}
        raise HTTPException(status_code=400, detail="Invalid sync command payload")
        
    return app


# =====================================================================
# Background Sync Worker Daemons (Polling + Upstream Sync Clients)
# =====================================================================

class DownstreamSyncWorker:
    """Threaded worker polling cloud for delta modifications."""
    def __init__(self, db: AbstractEdgeDB, cloud_url: str, poll_interval_sec: int = 60):
        self.db = db
        self.cloud_url = cloud_url.rstrip("/")
        self.poll_interval = poll_interval_sec
        self.running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        try:
            self.perform_startup_cleanup()
        except Exception as e:
            logger.error(f"Error performing startup cleanup: {str(e)}")
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def perform_startup_cleanup(self) -> None:
        """
        Queries all user IDs currently in the cloud database and deletes any
        locally cached users that no longer exist on the cloud database.
        """
        url = f"{self.cloud_url}/api/sync/downstream/user-ids"
        try:
            logger.info("Syncing cloud database baseline for deleted users at startup...")
            response = requests.get(url, timeout=10.0)
            if response.status_code == 200:
                cloud_user_ids = set(response.json())
                
                # Query local user IDs from SQLite
                local_user_ids = []
                with self.db.lock:
                    conn = self.db._get_connection()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("SELECT user_id FROM device_users")
                        local_user_ids = [row[0] for row in cursor.fetchall()]
                    except Exception as e:
                        logger.error(f"Failed to query local user IDs during startup cleanup: {e}")
                    finally:
                        conn.close()
                
                # Find IDs that exist locally but not on the cloud
                orphaned_ids = [uid for uid in local_user_ids if uid not in cloud_user_ids]
                if orphaned_ids:
                    logger.info(f"Startup clean: found {len(orphaned_ids)} orphaned users locally. Deleting: {orphaned_ids}")
                    self.db.delete_users_locally(orphaned_ids)
                else:
                    logger.info("Startup clean: local database is in sync with cloud users (no orphaned users).")
            else:
                logger.warning(f"Could not perform startup cleanup, cloud returned code {response.status_code}")
        except Exception as e:
            logger.error(f"Network error during startup user validation: {e}")

    def stop(self) -> None:
        self.running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _run_loop(self) -> None:
        while self.running:
            try:
                self.perform_sync()
            except Exception as e:
                logger.error(f"Sync error in background downstream loop: {str(e)}")
            time.sleep(self.poll_interval)

    def perform_sync(self) -> None:
        last_sync = self.db.get_last_sync_timestamp()
        params = {}
        if last_sync:
            params["last_synced_at"] = last_sync

        url = f"{self.cloud_url}/api/sync/downstream/delta"
        try:
            response = requests.get(url, params=params, timeout=10.0)
            if response.status_code != 200:
                logger.error(f"Cloud returned downstream sync error {response.status_code}")
                return
            data = response.json()

            # Execute transactional updates
            self.db.save_roles_delta(data.get("roles", []))
            self.db.save_users_delta(data.get("users", []))
            self.db.save_rbac_delta(data.get("node_rbac", []))
            
            # Execute local deletions
            deleted_ids = data.get("deleted_user_ids", [])
            if deleted_ids:
                self.db.delete_users_locally(deleted_ids)

            new_timestamp = data.get("timestamp")
            if new_timestamp:
                self.db.update_last_sync_timestamp(new_timestamp)
        except Exception as e:
            logger.error(f"Downstream sync network failure: {str(e)}")


class UpstreamSyncClient:
    """Threaded worker broadcasting keep-alive and replaying offline authentication loops."""
    def __init__(self, db: AbstractEdgeDB, cloud_url: str, device_id: str, device_name: str, local_ip: str, local_port: int = 8000):
        self.db = db
        self.cloud_url = cloud_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.local_ip = local_ip
        self.local_port = local_port
        
        self.is_online = False
        self.running = False
        
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._replay_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.running = True
        self._heartbeat_thread = threading.Thread(target=self._run_heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
        
        self._replay_thread = threading.Thread(target=self._run_replay_loop, daemon=True)
        self._replay_thread.start()

    def stop(self) -> None:
        self.running = False

    def _run_heartbeat_loop(self) -> None:
        while self.running:
            self._check_connection_and_heartbeat()
            time.sleep(30)

    def _check_connection_and_heartbeat(self) -> None:
        url = f"{self.cloud_url}/api/sync/upstream/heartbeat"
        payload = {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "ip_address": f"{self.local_ip}:{self.local_port}"
        }
        try:
            response = requests.post(url, json=payload, timeout=5.0)
            if response.status_code == 200:
                if not self.is_online:
                    logger.info("LAN Link restored. Status: ONLINE")
                self.is_online = True
            else:
                self.is_online = False
        except Exception:
            if self.is_online:
                logger.warning("LAN Connection dropped. Status: OFFLINE")
            self.is_online = False

    def _run_replay_loop(self) -> None:
        while self.running:
            if self.is_online:
                try:
                    self.replay_pending_logs()
                except Exception as e:
                    logger.error(f"Error in chronological log replay queue: {str(e)}")
            time.sleep(5)

    def replay_pending_logs(self) -> None:
        pending_logs = self.db.get_unsynced_logs()
        if not pending_logs:
            return

        logger.info(f"Replay Engine: Uploading {len(pending_logs)} pending logs upstream...")

        payload_logs = []
        log_id_mapping = {}
        for idx, log in enumerate(pending_logs):
            payload_logs.append({
                "user_id": log["user_id"],
                "device_id": self.device_id,
                "auth_status": log["auth_status"],
                "confidence_score": log["confidence_score"],
                "timestamp": log["timestamp"]
            })
            log_id_mapping[idx] = log["log_id"]

        url = f"{self.cloud_url}/api/sync/upstream/logs"
        try:
            response = requests.post(url, json={"logs": payload_logs}, timeout=15.0)
            if response.status_code == 200:
                result = response.json()
                successful_indices = result.get("successful_indices", [])
                synced_db_ids = [log_id_mapping[idx] for idx in successful_indices if idx in log_id_mapping]
                
                if synced_db_ids:
                    self.db.mark_logs_as_synced(synced_db_ids)
                    logger.info(f"Replay Engine: Sync completed for {len(synced_db_ids)} entries.")
        except Exception as e:
            logger.error(f"Upstream transmission timeout during log replay: {str(e)}")
