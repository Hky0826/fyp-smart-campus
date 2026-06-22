"""FastAPI service for the Hailo access-control and surveillance pipelines."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from ..config import AccessControlConfig, SurveillanceConfig
from ..face.database import DeviceUserDatabaseError, DeviceUserRepository
from ..pipelines.access_control import build_pipeline as build_access_pipeline
from ..pipelines.surveillance import build_pipeline as build_surveillance_pipeline
from ..utils.logging import configure_logging

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


logger = logging.getLogger(__name__)
configure_logging("INFO")

app = FastAPI(title="Edge Hailo Face Recognition", version="0.1.0")


@lru_cache(maxsize=1)
def access_config() -> AccessControlConfig:
    return AccessControlConfig()


@lru_cache(maxsize=1)
def surveillance_config() -> SurveillanceConfig:
    return SurveillanceConfig()


@lru_cache(maxsize=1)
def access_pipeline():
    return build_access_pipeline(access_config())


@lru_cache(maxsize=1)
def surveillance_pipeline():
    return build_surveillance_pipeline(surveillance_config())


@app.get("/health")
def health() -> dict:
    return {"success": True, "service": "edge_hailo", "status": "ok"}


@app.get("/models/status")
def models_status() -> dict:
    access = access_config()
    surveillance = surveillance_config()
    models = [
        ("access_detector", access.detector_model_path),
        ("access_embedder", access.embedding_model_path),
        ("surveillance_detector", surveillance.detector_model_path),
        ("surveillance_embedder", surveillance.embedding_model_path),
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


@app.post("/surveillance/frame")
async def surveillance_frame(file: UploadFile = File(...)) -> dict:
    frame = await _decode_upload(file)
    try:
        return surveillance_pipeline().process_frame(frame)
    except Exception as exc:
        logger.exception("Surveillance frame processing failed")
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
