"""Surveillance FastAPI service daemon."""

from __future__ import annotations

import os
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import SurveillanceConfig
from .database import SurveillanceUserRepository
from .sync import SurveillanceSyncEngine, create_surveillance_app

config = SurveillanceConfig()
repository = SurveillanceUserRepository(config.database_path)

sync_engine = SurveillanceSyncEngine.from_config(config, repository)
app = create_surveillance_app(repository, sync_engine=sync_engine)


@app.get("/")
def root():
    return {
        "service": "Surveillance Service Daemon",
        "models": {
            "person_detector": "YOLOX-M",
            "face_detector": "YuNet",
            "face_embedder": "AuraFace",
            "tracker": "ByteTrack",
        },
        "status": "running",
    }
