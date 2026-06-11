# edge/run_edge.py
"""Unified runner script executing both database synchronization and facial recognition loops."""

import os
import sys
import time
import logging
import threading
import uvicorn

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

def start_uvicorn(app, port):
    """Utility to run the uvicorn push listener in a background thread."""
    try:
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    except Exception as e:
        logger.error(f"Failed to start local push receiver uvicorn server: {str(e)}")

def main():
    # Configurations
    CLOUD_URL = "http://10.178.101.3:8000"          # Central Cloud API gateway address
    DEVICE_ID = "entry-gate-01"                  # Unique local hardware identifier
    DEVICE_NAME = "North Entry Gate Kiosk"       # Human-readable equipment label
    LOCAL_IP = "10.178.101.2"                       # Local LAN IP address of this edge device
    LOCAL_PORT = 8001                            # Port for receiving cloud deactivation pushes
    DB_PATH = os.path.join(SCRIPT_DIR, "device_local.db") # Shared SQLite DB path
    CAM_INDEX = 0                                # Camera input index (0 = default webcam, e.g. 4 for external)

    logger.info("Initializing unified Edge Service...")
    logger.info(f"Device: {DEVICE_ID} ({DEVICE_NAME}) | Cloud URL: {CLOUD_URL}")

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
    # Pass downstream_poller so the /api/edge/trigger-sync endpoint can call perform_sync() directly
    app = create_edge_app(db, downstream_worker=downstream_poller)
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
