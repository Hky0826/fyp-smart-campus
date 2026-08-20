import os
import sys
import subprocess
import signal
import time

port = os.getenv("PORT", "8080")

print("=" * 60)
print(f"[Supervisor] Starting Smart Campus Cloud Services (Port: {port})")
print("=" * 60)

# 1. Start Node.js Mapping & Notification Microservice on Port 5000
print("[Supervisor] Starting Mapping & Notification Microservice (port 5000)...")
node_env = os.environ.copy()
node_env["PORT"] = "5000"
node_env["AI_SERVICE_URL"] = f"http://127.0.0.1:{port}"
node_proc = subprocess.Popen(
    ["node", "index.js"],
    cwd="/app/mapping_and_notification/backend",
    env=node_env
)

# Allow microservice 2 seconds to bind to port 5000
time.sleep(2)

# 2. Start FastAPI Central Backend on Port $PORT (8080)
print(f"[Supervisor] Starting FastAPI Central Backend (port {port})...")
fastapi_proc = subprocess.Popen(
    [
        "uvicorn",
        "cloud.dashboard.backend.app.main:app",
        "--host", "0.0.0.0",
        "--port", str(port)
    ],
    cwd="/app"
)

def handle_shutdown(signum, frame):
    print("\n[Supervisor] Received shutdown signal. Terminating services...")
    try:
        fastapi_proc.terminate()
    except Exception:
        pass
    try:
        node_proc.terminate()
    except Exception:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# Wait for FastAPI process
try:
    exit_code = fastapi_proc.wait()
    print(f"[Supervisor] FastAPI exited with code {exit_code}")
except KeyboardInterrupt:
    handle_shutdown(None, None)
finally:
    try:
        node_proc.terminate()
    except Exception:
        pass
