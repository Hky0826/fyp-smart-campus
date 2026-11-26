"""Unified Cloud Services Launcher.

Campus Mapping, Navigation, Kiosk Wayfinding, Notifications, and AI Floorplan
Computer Vision are now natively integrated into the central FastAPI backend.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AI_SERVICES_DIR = REPO_ROOT / "mapping_and_notification" / "ai-services"


def _build_pythonpath(existing: str | None) -> str:
    entries = [
        str(REPO_ROOT),
        str(REPO_ROOT / "cloud"),
        str(REPO_ROOT / "cloud" / "dashboard" / "backend"),
        str(AI_SERVICES_DIR),
    ]
    if existing:
        for item in existing.split(os.pathsep):
            if item and item not in entries:
                entries.append(item)
    return os.pathsep.join(entries)


def _terminate_processes(processes: list[subprocess.Popen]) -> None:
    for proc in processes:
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    deadline = time.monotonic() + 5.0
    for proc in processes:
        remaining = max(0.1, deadline - time.monotonic())
        if proc.poll() is None:
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass


def main() -> int:
    port = os.getenv("PORT", "8080")

    print("=" * 60)
    print(f"[Supervisor] Starting Unified Smart Campus Cloud API (Port: {port})")
    print("=" * 60)

    fastapi_env = os.environ.copy()
    fastapi_env["PYTHONPATH"] = _build_pythonpath(fastapi_env.get("PYTHONPATH"))

    fastapi_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "cloud.dashboard.backend.app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ],
        cwd=str(REPO_ROOT),
        env=fastapi_env,
    )
    managed_processes = [fastapi_proc]

    shutdown_requested = False

    def handle_shutdown(signum, _frame):
        nonlocal shutdown_requested
        if not shutdown_requested:
            shutdown_requested = True
            print(f"\n[Supervisor] Received signal {signum}. Terminating FastAPI...")
            _terminate_processes(managed_processes)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    exit_code = 0
    try:
        exit_code = fastapi_proc.wait()
        print(f"[Supervisor] FastAPI exited with code {exit_code}")
    except KeyboardInterrupt:
        print("\n[Supervisor] Interrupted by user. Terminating services...")
        exit_code = 0
    finally:
        _terminate_processes(managed_processes)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
