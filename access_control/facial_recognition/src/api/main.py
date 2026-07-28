"""FastAPI service for the access-control pipeline."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from ..config import AccessControlConfig, RuntimeConfig
from ..face.database import DeviceUserDatabaseError, DeviceUserRepository
from ..pipelines.access_control import build_pipeline as build_access_pipeline
from ..sync import SyncEngine
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


@lru_cache(maxsize=1)
def runtime_config() -> RuntimeConfig:
    return RuntimeConfig()


@lru_cache(maxsize=1)
def access_config() -> AccessControlConfig:
    return AccessControlConfig()


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


# ── Face Recognition ──────────────────────────────────────────────────────────

@app.post("/access-control/frame")
async def access_control_frame(
    file: UploadFile = File(...),
    target_user_id: Optional[str] = Form(default=None),
) -> dict:
    frame = await _decode_upload(file)
    try:
        return access_pipeline().process_frame(frame, target_user_id=target_user_id)
    except Exception as exc:
        logger.exception("Access-control frame processing failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _decode_upload(file: UploadFile) -> np.ndarray:
    if cv2 is None:
        raise HTTPException(status_code=500, detail="OpenCV is required to decode uploaded images")
    data = await file.read()
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
