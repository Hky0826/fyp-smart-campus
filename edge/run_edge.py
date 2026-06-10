# edge/run_edge.py
"""Unified runner script executing both database synchronization and facial recognition loops."""

import os
import sys
import time
import logging
import threading
import socket
import uvicorn
import mysql.connector
from dotenv import dotenv_values

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("EdgeRunner")

# Configure path so python can find local imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Project root path insertion
project_root = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from edge_sync_client import SQLiteEdgeDB, create_edge_app, DownstreamSyncWorker, UpstreamSyncClient
from edge_kiosk_app import main_loop

def fetch_device_ip_from_db(device_id: str, db_host: str) -> str:
    """
    Connects to the central cloud MySQL database and retrieves the configured 
    IP address for the given device_id.
    """
    # Locate .env file in the backend
    env_path = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "cloud", "dashboard", "backend", ".env"))
    
    if not os.path.exists(env_path):
        logger.warning(f"Could not find backend .env configuration at {env_path}")
        return None

    config = dotenv_values(env_path)
    db_user = config.get("DB_USER", "root")
    db_password = config.get("DB_PASSWORD", "")
    db_name = config.get("DB_NAME", "smart_campus_db")
    try:
        db_port = int(config.get("DB_PORT", 3306))
    except ValueError:
        db_port = 3306

    logger.info(f"Connecting to cloud database at {db_host}:{db_port} to fetch IP for device '{device_id}'...")
    try:
        conn = mysql.connector.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            database=db_name,
            connect_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute("SELECT ip_address, device_name FROM devices WHERE device_id = %s", (device_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if row:
            ip_val = row[0]
            dev_name = row[1]
            logger.info(f"Database lookup succeeded. Device: {device_id} ({dev_name}), IP from DB: {ip_val}")
            if ip_val:
                # If ip_val contains port (e.g. 10.178.101.2:8000), strip it
                if ":" in ip_val:
                    return ip_val.split(":")[0]
                return ip_val
        else:
            logger.warning(f"Device '{device_id}' not found in cloud database.")
    except Exception as e:
        logger.error(f"Failed to fetch device IP from cloud database: {str(e)}")
    
    return None

def get_local_ip(target_host: str) -> str:
    """
    Discovers the local interface IP address that routes to target_host.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_host, 80))
        ip = s.getsockname()[0]
        s.close()
        logger.info(f"Socket dynamic discovery resolved local IP to: {ip}")
        return ip
    except Exception as e:
        logger.warning(f"Socket discovery failed: {str(e)}. Defaulting to loopback.")
        return "127.0.0.1"

def start_uvicorn(app, port):
    """Utility to run the uvicorn push listener in a background thread."""
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    except Exception as e:
        logger.error(f"Failed to start local push receiver uvicorn server: {str(e)}")

def main():
    # Configurations
    CLOUD_HOST = "10.178.101.3"
    CLOUD_URL = f"http://{CLOUD_HOST}:8000"          # Central Cloud API gateway address
    DEVICE_ID = "EDGE-0001"                       # Unique local hardware identifier
    DEVICE_NAME = "Main Door"                    # Human-readable equipment label
    LOCAL_PORT = 8000                            # Port for receiving cloud deactivation pushes
    DB_PATH = os.path.join(SCRIPT_DIR, "device_local.db") # Shared SQLite DB path
    CAM_INDEX = 0                                # Camera input index (0 = default webcam, e.g. 4 for external)

    logger.info("Initializing unified Edge Service...")

    # Resolve local IP address using database or fallback
    db_ip = fetch_device_ip_from_db(DEVICE_ID, CLOUD_HOST)
    if db_ip:
        LOCAL_IP = db_ip
    else:
        logger.info("Falling back to local network interface discovery...")
        LOCAL_IP = get_local_ip(CLOUD_HOST)

    logger.info(f"Device: {DEVICE_ID} ({DEVICE_NAME}) | Cloud URL: {CLOUD_URL} | Resolved Local IP: {LOCAL_IP}")

    # 1. Initialize SQLite Database schemas
    db = SQLiteEdgeDB(DB_PATH)

    # 2. Run upstream sync daemon thread (heartbeats & log replays)
    upstream_client = UpstreamSyncClient(
        db=db,
        cloud_url=CLOUD_URL,
        device_id=DEVICE_ID,
        device_name=DEVICE_NAME,
        local_ip=LOCAL_IP,
        local_port=LOCAL_PORT
    )
    upstream_client.start()

    # 3. Run downstream polling worker thread (delta pulls)
    downstream_poller = DownstreamSyncWorker(db, cloud_url=CLOUD_URL, poll_interval_sec=30)
    downstream_poller.start()

    # 4. Run uvicorn push notification server in a background thread
    app = create_edge_app(db)
    uvicorn_thread = threading.Thread(target=start_uvicorn, args=(app, LOCAL_PORT), daemon=True)
    uvicorn_thread.start()
    logger.info(f"Local push receiver listening on port {LOCAL_PORT} in background thread.")

    # 5. Launch the blocking OpenCV camera capture and liveness detection loop on the main thread
    logger.info("Launching face detection and liveness loop on main thread...")
    try:
        main_loop(db_path=DB_PATH, cam_index=CAM_INDEX)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt captured. Shutting down Edge Service...")
    except Exception as e:
        logger.error(f"Fatal error in facial recognition main loop: {str(e)}")
    finally:
        # Clean shutdown
        upstream_client.stop()
        downstream_poller.stop()
        logger.info("Unified Edge Service terminated cleanly.")

if __name__ == "__main__":
    main()
