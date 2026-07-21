"""Unified launcher for the access-control backend API, native QML GUI, or both."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from access_control.facial_recognition.src.config import AccessControlConfig

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch access-control FastAPI backend server, PySide6 GUI, or both."
    )
    parser.add_argument(
        "mode",
        choices=("all", "api", "gui", "ui"),
        nargs="?",
        default="all",
        help="Execution mode: 'all' (API + GUI, default), 'api' (FastAPI only), or 'gui' (PySide6 UI only).",
    )
    parser.add_argument("--host", default=None, help="API host (default from .env or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="API port (default from .env or 8080)")
    return parser.parse_args()


def serve_api(host: str, port: int, server_holder: list | None = None) -> None:
    """Run uvicorn server for the access control FastAPI application."""
    import uvicorn
    from access_control.facial_recognition.src.api.main import app

    log_level = os.getenv("EDGE_LOG_LEVEL", "info").lower()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=False,
    )
    server = uvicorn.Server(config)
    if server_holder is not None:
        server_holder.append(server)
    server.run()


def main() -> int:
    args = parse_args()
    config = AccessControlConfig()

    host = args.host or os.getenv("ACCESS_API_HOST") or "0.0.0.0"
    port = args.port or config.sync_local_port or 8080

    mode = args.mode.lower()
    if mode in ("gui", "ui"):
        from access_control.ui.access_control_gui.main import main as gui_main
        print("Starting Access Control GUI...")
        return gui_main()

    if mode == "api":
        print(f"Starting Access Control API server at http://{host}:{port}...")
        serve_api(host, port)
        return 0

    # Mode: 'all' -> Launch API in background thread and GUI in main thread
    print(f"Starting Access Control Backend API at http://{host}:{port}...")
    server_holder: list = []
    api_thread = threading.Thread(
        target=serve_api,
        args=(host, port, server_holder),
        daemon=True,
        name="access-control-api",
    )
    api_thread.start()

    # Wait up to 10 seconds for the uvicorn server to start listening
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and (not server_holder or not getattr(server_holder[0], "started", False)):
        time.sleep(0.05)

    if not server_holder or not getattr(server_holder[0], "started", False):
        logger.warning("API server startup wait timed out; launching GUI anyway...")
    else:
        print("Backend API is ready! Starting Access Control GUI...")

    try:
        from access_control.ui.access_control_gui.main import main as gui_main
        return gui_main()
    finally:
        print("GUI closed. Shutting down backend API...")
        if server_holder:
            server_holder[0].should_exit = True
        api_thread.join(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
