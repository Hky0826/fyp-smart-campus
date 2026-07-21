"""Pydantic response models for API documentation."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ModelStatus(BaseModel):
    name: str
    path: str
    exists: bool


class DatabaseStatus(BaseModel):
    ok: bool
    path: str
    registered_users: int = 0
    templates: int = 0


class SurveillanceFaceResult(BaseModel):
    bbox: List[int]
    detection_confidence: float
    identity: str
    similarity: float
    matched_template: Optional[str] = None
    status: str
    timestamp: Optional[str] = None
