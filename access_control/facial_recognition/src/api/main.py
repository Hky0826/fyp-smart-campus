"""FastAPI service for the access-control pipeline."""

from __future__ import annotations

import logging
import asyncio
import hmac
import os
import socket
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from pydantic import BaseModel, Field

from ..config import (
    AccessControlConfig,
    RuntimeConfig,
    default_cloud_url,
    default_sync_local_ip,
    detect_local_ip,
    persist_runtime_configuration,
)
from ..face.database import DeviceUserDatabaseError, DeviceUserRepository
from ..pipelines.access_control import build_pipeline as build_access_pipeline
from ...setup_sqlite import initialize_sqlite_database
from ..sync import SQLiteEdgeDB, SyncEngine
from ..utils.logging import configure_logging
from .chatbot_client import ChatbotClient, ChatbotClientError
from .kiosk import create_kiosk_router

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


logger = logging.getLogger(__name__)
configure_logging("INFO")

_sync_engine: SyncEngine | None = None

app = FastAPI(title="Access Control Face Recognition API", version="0.1.0")

_LOCAL_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _runtime_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class InstallationAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        config = access_config()
        client_host = request.client.host if request.client else ""
        is_local_client = client_host in _LOCAL_CLIENT_HOSTS
        if (
            config.remote_api_enabled
            and not is_local_client
            and request.url.path not in {"/health", "/docs", "/openapi.json"}
        ):
            supplied = request.headers.get("X-Installation-Credential", "")
            if not config.installation_credential or not hmac.compare_digest(supplied, config.installation_credential):
                return JSONResponse({"detail": "Installation authentication required"}, status_code=401)
        return await call_next(request)


app.add_middleware(InstallationAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bearer token extractor for the chatbot proxy
_bearer_scheme = HTTPBearer(auto_error=False)
_frame_semaphore = asyncio.Semaphore(2)
_MAX_FRAME_BYTES = 8 * 1024 * 1024


@lru_cache(maxsize=1)
def runtime_config() -> RuntimeConfig:
    # These values can be supplied by the setup wizard while the process is
    # running, so read the provisioning fields when the cache is rebuilt.
    return RuntimeConfig(
        sync_cloud_url=os.getenv("EDGE_SYNC_CLOUD_URL", default_cloud_url()),
        sync_device_id=os.getenv("EDGE_SYNC_DEVICE_ID", "entry-gate-01"),
        sync_device_secret=os.getenv("EDGE_SYNC_DEVICE_SECRET", ""),
        sync_local_ip=os.getenv("EDGE_SYNC_LOCAL_IP", default_sync_local_ip()),
        remote_api_enabled=_runtime_bool("EDGE_REMOTE_API_ENABLED"),
        installation_credential=os.getenv("EDGE_INSTALLATION_CREDENTIAL", ""),
    )


@lru_cache(maxsize=1)
def access_config() -> AccessControlConfig:
    return AccessControlConfig(
        sync_cloud_url=os.getenv("EDGE_SYNC_CLOUD_URL", default_cloud_url()),
        sync_device_id=os.getenv("EDGE_SYNC_DEVICE_ID", "entry-gate-01"),
        sync_device_secret=os.getenv("EDGE_SYNC_DEVICE_SECRET", ""),
        sync_local_ip=os.getenv("EDGE_SYNC_LOCAL_IP", default_sync_local_ip()),
        remote_api_enabled=_runtime_bool("EDGE_REMOTE_API_ENABLED"),
        installation_credential=os.getenv("EDGE_INSTALLATION_CREDENTIAL", ""),
    )


def _ensure_local_database(config: AccessControlConfig) -> None:
    """Create/migrate the local SQLite database before the setup UI is shown.

    First-run setup must be usable without an edge ``.env`` file.  A normal
    SQLite database can be initialized directly; an explicitly configured
    SQLCipher database is initialized through ``SQLiteEdgeDB`` so the same
    encryption path is used for creation and later access.
    """
    if config.database_encryption_key:
        SQLiteEdgeDB(config.database_path, encryption_key=config.database_encryption_key)
    else:
        initialize_sqlite_database(config.database_path)


def _setup_is_pending(config: AccessControlConfig) -> bool:
    return (
        not config.setup_marker_path.is_file()
        or not config.database_path.expanduser().resolve().is_file()
        or not config.sync_device_secret.strip()
    )


@lru_cache(maxsize=1)
def access_pipeline():
    return build_access_pipeline(access_config())


@lru_cache(maxsize=1)
def _chatbot_client() -> ChatbotClient:
    """Return a shared ChatbotClient instance backed by the runtime config."""
    return ChatbotClient(runtime_config())


app.include_router(
    create_kiosk_router(
        runtime_config=runtime_config,
        access_pipeline=access_pipeline,
        chatbot_client=_chatbot_client,
        sync_status=lambda: "disabled"
        if not access_config().sync_enabled
        else ("connected" if _sync_engine and _sync_engine._running else "starting"),
    )
)


@app.on_event("startup")
def start_sync_engine() -> None:
    """Start cloud sync for kiosk/API deployments."""
    global _sync_engine
    if _sync_engine is not None:
        return

    config = access_config()
    if _setup_is_pending(config):
        _ensure_local_database(config)
        logger.warning(
            "First-time setup is pending. SQLite is ready at %s; complete setup from the access-control display.",
            config.database_path,
        )
        return
    config.validate_security()
    _ensure_local_database(config)
    _sync_engine = SyncEngine.from_config(config)
    _sync_engine.start()
    logger.info(
        "Edge sync configured: enabled=%s cloud_url=%s device_id=%s db=%s",
        config.sync_enabled,
        config.sync_cloud_url,
        config.sync_device_id,
        config.database_path,
    )


@app.on_event("shutdown")
def stop_sync_engine() -> None:
    global _sync_engine
    if _sync_engine is None:
        return
    _sync_engine.stop()
    _sync_engine = None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"success": True, "service": "access_control", "status": "ok"}


@app.get("/sync/status")
def sync_status() -> dict:
    config = access_config()
    return {
        "success": True,
        "enabled": config.sync_enabled,
        "running": bool(_sync_engine and _sync_engine._running),
        "cloud_url": config.sync_cloud_url,
        "device_id": config.sync_device_id,
        "device_name": config.sync_device_name,
        "database_path": str(config.database_path),
        "local_ip": config.sync_local_ip,
        "configured_local_port": config.sync_local_port,
        "local_port": (_sync_engine.actual_sync_port if _sync_engine and _sync_engine.actual_sync_port else config.sync_local_port),
        "downstream_poll_seconds": config.sync_downstream_poll_seconds,
        "log_push_interval_seconds": config.sync_log_push_interval_seconds,
    }


@app.get("/models/status")
def models_status() -> dict:
    access = access_config()
    models = [
        ("access_detector", access.detector_model_path),
        ("access_embedder", access.embedding_model_path),
    ]
    return {
        "success": True,
        "models": [
            {"name": name, "path": str(path), "exists": path.exists()}
            for name, path in models
        ],
    }


@app.get("/database/status")
def database_status() -> dict:
    repo = DeviceUserRepository(access_config().database_path)
    try:
        return {"success": True, **repo.get_status()}
    except (FileNotFoundError, DeviceUserDatabaseError) as exc:
        return {"success": False, "ok": False, "path": str(repo.db_path), "error": str(exc)}


def _setup_local_address(config: AccessControlConfig) -> str:
    host = (config.sync_local_ip or "").strip()
    if config.remote_api_enabled and host in {"", "127.0.0.1", "localhost", "::1"}:
        host = detect_local_ip(config.sync_cloud_url)
    if not host or host == "0.0.0.0":
        try:
            host = detect_local_ip(config.sync_cloud_url)
        except OSError:
            host = "127.0.0.1"
    return f"{host}:{config.sync_local_port}"


@app.get("/setup/status")
def setup_status() -> dict:
    config = access_config()
    database_path = config.database_path.expanduser().resolve()
    database_error = ""
    try:
        _ensure_local_database(config)
        database_initialized = DeviceUserRepository(database_path).get_status().get("ok", False)
    except (OSError, RuntimeError, sqlite3.Error, DeviceUserDatabaseError) as exc:
        database_initialized = False
        database_error = str(exc)
    setup_complete = config.setup_marker_path.is_file() and database_initialized and bool(config.sync_device_secret.strip())
    return {
        "success": True,
        "first_time_setup": not setup_complete,
        "setup_complete": setup_complete,
        "database_initialized": database_initialized,
        "database_error": database_error,
        "device_id": config.sync_device_id,
        # This value is intentionally omitted after acknowledgement. It is
        # supplied through the edge deployment environment, not generated by
        # or persisted in the GUI.
        "device_secret": config.sync_device_secret if not setup_complete else "",
        "local_ip": config.sync_local_ip,
        "local_address": _setup_local_address(config),
        "detected_lan_address": f"{detect_local_ip(config.sync_cloud_url)}:{config.sync_local_port}",
        "cloud_url": config.sync_cloud_url,
        "configured": bool(config.sync_device_secret),
        "instructions": [
            "Keep this access-control display open during first-time setup.",
            "On the administrator computer, open the cloud dashboard on the same Wi-Fi network.",
            "Go to Infrastructure > Devices > Add Device and leave Device ID blank so it is generated automatically.",
            "Copy the one-time Device ID and device secret from the dashboard provisioning dialog.",
            "Enter the cloud URL, generated Device ID, and one-time secret on this screen, then select Apply and start.",
            "For separate computers on Wi-Fi, select secure cloud-to-edge push; this device will detect and save its LAN IP automatically.",
            "The local SQLite database is initialized automatically; no edge .env file is required.",
        ],
    }


class SetupProvisionRequest(BaseModel):
    """Values copied from the one-time dashboard provisioning screen."""

    cloud_url: str = Field(..., min_length=8, max_length=500)
    device_id: str = Field(..., min_length=3, max_length=100)
    device_secret: str = Field(..., min_length=32, max_length=500)
    remote_push: bool = False


@app.post("/setup/provision")
def provision_setup(payload: SetupProvisionRequest) -> dict:
    """Apply dashboard provisioning without requiring manual .env editing."""
    global _sync_engine
    current = access_config()
    if current.setup_marker_path.is_file() and current.sync_device_secret:
        raise HTTPException(status_code=409, detail="This device is already provisioned")

    try:
        remote_api_enabled = bool(payload.remote_push)
        local_ip = detect_local_ip(payload.cloud_url) if remote_api_enabled else "127.0.0.1"
        candidate = AccessControlConfig(
            sync_cloud_url=payload.cloud_url.strip(),
            sync_device_id=payload.device_id.strip(),
            sync_device_secret=payload.device_secret.strip(),
            sync_local_ip=local_ip,
            remote_api_enabled=remote_api_enabled,
        )
        candidate.validate_security()
        persist_runtime_configuration(
            cloud_url=payload.cloud_url,
            device_id=payload.device_id,
            device_secret=payload.device_secret,
            local_ip=local_ip,
            remote_api_enabled=remote_api_enabled,
        )
        os.environ["EDGE_SYNC_CLOUD_URL"] = payload.cloud_url.strip()
        os.environ["EDGE_SYNC_DEVICE_ID"] = payload.device_id.strip()
        os.environ["EDGE_SYNC_DEVICE_SECRET"] = payload.device_secret.strip()
        os.environ["EDGE_SYNC_LOCAL_IP"] = local_ip
        os.environ["EDGE_REMOTE_API_ENABLED"] = "true" if remote_api_enabled else "false"

        if _sync_engine is not None:
            _sync_engine.stop()
            _sync_engine = None
        access_config.cache_clear()
        runtime_config.cache_clear()
        _chatbot_client.cache_clear()
        new_config = access_config()
        _sync_engine = SyncEngine.from_config(new_config)
        _sync_engine.start()

        marker = new_config.setup_marker_path
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Edge UI provisioning failed")
        raise HTTPException(status_code=503, detail="Device provisioning could not be started") from exc

    return {
        "success": True,
        "setup_complete": True,
        "device_id": new_config.sync_device_id,
        "cloud_url": new_config.sync_cloud_url,
        "local_address": _setup_local_address(new_config),
    }


@app.post("/setup/complete")
def complete_setup() -> dict:
    config = access_config()
    if not config.sync_device_secret:
        raise HTTPException(status_code=400, detail="Provision the device before completing setup")
    marker = config.setup_marker_path
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        with marker.open("x", encoding="utf-8") as handle:
            handle.write(datetime.now(timezone.utc).isoformat())
    except FileExistsError:
        pass
    return {"success": True, "setup_complete": True}


# ── Face Recognition ──────────────────────────────────────────────────────────

@app.post("/access-control/frame")
async def access_control_frame(
    file: UploadFile = File(...),
    target_user_id: Optional[str] = Form(default=None),
) -> dict:
    async with _frame_semaphore:
        frame = await _decode_upload(file)
        try:
            return access_pipeline().process_frame(frame, target_user_id=target_user_id)
        except Exception as exc:
            logger.exception("Access-control frame processing failed")
            raise HTTPException(status_code=503, detail="Frame processing unavailable") from exc


async def _decode_upload(file: UploadFile) -> np.ndarray:
    if cv2 is None:
        raise HTTPException(status_code=500, detail="OpenCV is required to decode uploaded images")
    data = await file.read()
    if len(data) > _MAX_FRAME_BYTES:
        raise HTTPException(status_code=413, detail="Frame exceeds the configured size limit")
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image")
    return frame


# ── RAG Chatbot Proxy ─────────────────────────────────────────────────────────

class EdgeChatRequest(BaseModel):
    """Request body for the edge chatbot proxy endpoint."""

    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[int] = Field(None, description="JWT session ID from the cloud.")


@app.get("/chatbot/health")
def chatbot_health_passthrough() -> dict:
    """
    Check if the cloud RAG chatbot service is reachable and configured.
    Does not require authentication.
    """
    try:
        result = _chatbot_client().health_check()
        return {"success": True, **result}
    except ChatbotClientError as exc:
        return {
            "success": False,
            "status": "unreachable",
            "error": str(exc),
        }


@app.post("/chatbot/chat")
def chatbot_chat(
    body: EdgeChatRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """Proxy a user chat query to the cloud RAG chatbot."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please authenticate via face recognition first.",
        )

    jwt_token = credentials.credentials
    config = runtime_config()

    try:
        response = _chatbot_client().chat(
            query=body.query,
            jwt_token=jwt_token,
            device_id=config.sync_device_id,
            session_id=body.session_id,
        )
        return {"success": True, **response}

    except ChatbotClientError as exc:
        status_map = {
            401: 401,
            403: 403,
            422: 422,
            503: 503,
        }
        http_code = status_map.get(exc.status_code or 0, 502)
        raise HTTPException(status_code=http_code, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error in chatbot proxy")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while contacting the chatbot service.",
        )
