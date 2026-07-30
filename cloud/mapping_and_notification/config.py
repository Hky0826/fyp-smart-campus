from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MappingSettings:
    stale_location_minutes: int = int(os.getenv("MAP_STALE_LOCATION_MINUTES", "15"))
    default_walking_speed: float = float(os.getenv("MAP_DEFAULT_WALKING_SPEED", "1.2"))
    transition_seconds: float = float(os.getenv("MAP_TRANSITION_SECONDS", "30"))
    wall_detection_concurrency: int = max(1, int(os.getenv("MAX_AI_CONCURRENCY", "8")))
    floorplan_max_bytes: int = int(os.getenv("MAX_FLOORPLAN_BYTES", str(25 * 1024 * 1024)))
    visualisation_retention_hours: int = int(os.getenv("VISUALISATION_RETENTION_HOURS", "24"))


settings = MappingSettings()
