"""Unified launcher for the access-control backend API, native QML GUI, or both."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

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


def find_available_port(host: str, preferred_port: int, max_attempts: int = 20) -> int:
    """Find an open TCP port starting from preferred_port."""
    bind_host = "" if host == "0.0.0.0" else host
    for p in range(preferred_port, preferred_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((bind_host, p))
                return p
        except OSError:
            continue
    return preferred_port


def diagnose_cloud_connectivity(cloud_url: str) -> None:
    """Test TCP connectivity to the configured cloud backend URL."""
    try:
        parsed = urlparse(cloud_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 8000)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.5)
            s.connect((host, port))
            print(f"[Cloud Diagnostic] Cloud backend at {cloud_url} is ONLINE and accepting connections.")
    except Exception as exc:
        print(
            f"\n[Cloud Diagnostic WARNING] Cannot establish TCP connection to Cloud URL '{cloud_url}' ({exc}).\n"
            f"  - Note: ICMP ping may succeed even if TCP port is closed or blocked.\n"
            f"  - Fix: Ensure the cloud backend server is running and listening on 0.0.0.0:{port} (not 127.0.0.1:{port}).\n"
            f"  - Check: Verify firewall rules allow incoming TCP traffic on port {port}.\n"
        )


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
        server_holder.append({"server": server, "error": None})
    try:
        server.run()
    except Exception as exc:
        if server_holder is not None and server_holder:
            server_holder[0]["error"] = exc
        logger.error("Failed to run API server on %s:%s: %s", host, port, exc)


def main() -> int:
    args = parse_args()
    config = AccessControlConfig()

    # Cloud connectivity diagnostic
    diagnose_cloud_connectivity(config.sync_cloud_url)

    requested_host = args.host or os.getenv("ACCESS_API_HOST") or "0.0.0.0"
    requested_api_port = args.port or int(os.getenv("ACCESS_API_PORT", "8080"))

    actual_api_port = find_available_port(requested_host, requested_api_port)
    if actual_api_port != requested_api_port:
        print(f"[Port Manager] API Port {requested_api_port} is occupied or restricted. Automatically bound to free port {actual_api_port}.")

    os.environ["ACCESS_API_PORT"] = str(actual_api_port)

    mode = args.mode.lower()
    if mode in ("gui", "ui"):
        from access_control.ui.access_control_gui.main import main as gui_main
        print("Starting Access Control GUI...")
        return gui_main()

    if mode == "api":
        print(f"Starting Access Control API server at http://{requested_host}:{actual_api_port}...")
        serve_api(requested_host, actual_api_port)
        return 0

    # Mode: 'all' -> Launch API in background thread and GUI in main thread
    print(f"Starting Access Control Backend API at http://{requested_host}:{actual_api_port}...")
    server_holder: list = []
    api_thread = threading.Thread(
        target=serve_api,
        args=(requested_host, actual_api_port, server_holder),
        daemon=True,
        name="access-control-api",
    )
    api_thread.start()

    # Wait for uvicorn server startup
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if server_holder:
            err = server_holder[0].get("error")
            if err is not None:
                print(f"[API Startup Error] API server failed to start: {err}")
                break
            srv = server_holder[0].get("server")
            if srv and getattr(srv, "started", False):
                break
        time.sleep(0.05)

    srv = server_holder[0].get("server") if server_holder else None
    if srv and getattr(srv, "started", False):
        print(f"Backend API is ready at http://127.0.0.1:{actual_api_port}! Starting Access Control GUI...")
    else:
        print("[Warning] API server did not signal ready state; launching GUI anyway...")

    try:
        from access_control.ui.access_control_gui.main import main as gui_main
        return gui_main()
    finally:
        print("GUI closed. Shutting down backend API...")
        if srv:
            srv.should_exit = True
        api_thread.join(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
