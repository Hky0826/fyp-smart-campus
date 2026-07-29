from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class PADResult:
    state: str
    score: float
    model_version: str
    threshold: float
    reason: str = ""


class PresentationAttackDetector(Protocol):
    model_version: str

    def check(self, frame: Any, face: Any) -> PADResult: ...


class UnavailablePAD:
    model_version = "unavailable"

    def check(self, frame: Any, face: Any) -> PADResult:
        return PADResult("unknown", 0.0, self.model_version, 0.0, "pad_model_unavailable")


def load_pad(config: Any) -> PresentationAttackDetector:
    path = getattr(config, "pad_model_path", None)
    if path and str(path) not in {"", "."} and Path(path).is_file():
        # Deployments can provide a small adapter module/class.  The adapter
        # remains behind this interface so the access decision never silently
        # falls back to motion heuristics in production.
        adapter = importlib.import_module("access_control.facial_recognition.src.face.pad_model_adapter")
        return adapter.PADModel(Path(path), getattr(config, "pad_model_version", "configured"))
    if getattr(config, "pad_required", False) and os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("Configured PAD model is unavailable")
    return UnavailablePAD()
