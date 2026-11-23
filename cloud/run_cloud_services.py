import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NODE_BACKEND_DIR = REPO_ROOT / "mapping_and_notification" / "backend"
AI_SERVICES_DIR = REPO_ROOT / "mapping_and_notification" / "ai-services"


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _wait_for_http_ready(
    url: str,
    process: subprocess.Popen,
    *,
    timeout_seconds: float = 15.0,
    poll_interval: float = 0.25,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if 200 <= resp.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(poll_interval)
    return False


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
    node_port = os.getenv("MAPPING_PORT", "5000")
    skip_worker = _is_truthy(os.getenv("SKIP_NOTIFICATION_WORKER"))

    print("=" * 60)
    print(f"[Supervisor] Starting Smart Campus Cloud Services (Port: {port})")
    print("=" * 60)

    node_env = os.environ.copy()
    node_env["PORT"] = str(node_port)
    node_env.setdefault("AI_SERVICE_URL", f"http://127.0.0.1:{port}")

    managed_processes: list[subprocess.Popen] = []

    print(f"[Supervisor] Starting Mapping & Notification Microservice (port {node_port})...")
    node_proc = subprocess.Popen(
        ["node", str(NODE_BACKEND_DIR / "index.js")],
        cwd=str(NODE_BACKEND_DIR),
        env=node_env,
    )
    managed_processes.append(node_proc)

    consumer_proc: subprocess.Popen | None = None
    if not skip_worker:
        print("[Supervisor] Starting Notification Consumer Worker...")
        consumer_proc = subprocess.Popen(
            ["node", str(NODE_BACKEND_DIR / "consumer.js")],
            cwd=str(NODE_BACKEND_DIR),
            env=node_env,
        )
        managed_processes.append(consumer_proc)

    node_health_url = f"http://127.0.0.1:{node_port}/health"
    if _wait_for_http_ready(node_health_url, node_proc, timeout_seconds=15.0):
        print(f"[Supervisor] Mapping Microservice ready at {node_health_url}")
    elif node_proc.poll() is not None:
        print(f"[Supervisor] Mapping Microservice exited prematurely with code {node_proc.returncode}")
        _terminate_processes(managed_processes)
        return node_proc.returncode or 1
    else:
        print(f"[Supervisor] Warning: Mapping Microservice did not become ready at {node_health_url} within timeout")

    fastapi_env = os.environ.copy()
    fastapi_env["PYTHONPATH"] = _build_pythonpath(fastapi_env.get("PYTHONPATH"))
    fastapi_env.setdefault("MAPPING_MICROSERVICE_URL", f"http://127.0.0.1:{node_port}")

    print(f"[Supervisor] Starting FastAPI Central Backend (port {port})...")
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
    managed_processes.append(fastapi_proc)

    shutdown_requested = False

    def handle_shutdown(signum, _frame):
        nonlocal shutdown_requested
        if not shutdown_requested:
            shutdown_requested = True
            print(f"\n[Supervisor] Received signal {signum}. Terminating services...")
            _terminate_processes(managed_processes)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    exit_code = 0
    try:
        while True:
            fastapi_code = fastapi_proc.poll()
            if fastapi_code is not None:
                print(f"[Supervisor] FastAPI exited with code {fastapi_code}")
                exit_code = fastapi_code
                break

            node_code = node_proc.poll()
            if node_code is not None:
                print(f"[Supervisor] Mapping Microservice exited unexpectedly with code {node_code}")
                exit_code = node_code or 1
                break

            if consumer_proc is not None and consumer_proc.poll() is not None:
                print(
                    f"[Supervisor] Warning: Notification consumer exited with code {consumer_proc.returncode}; continuing without background consumer."
                )
                consumer_proc = None

            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[Supervisor] Interrupted by user. Terminating services...")
        exit_code = 0
    finally:
        _terminate_processes(managed_processes)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
