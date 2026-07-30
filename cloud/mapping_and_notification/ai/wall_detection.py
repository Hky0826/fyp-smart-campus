from __future__ import annotations

import hashlib
import io
import threading
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageOps


@dataclass(frozen=True)
class WallResult:
    grid: list[list[int]]
    grid_width: int
    grid_height: int
    canvas_width: int
    canvas_height: int
    grid_scale: int
    sensitivity_used: int
    processing_time_ms: float
    wall_cell_count: int
    total_cells: int

    @property
    def wall_ratio(self) -> float:
        return round(self.wall_cell_count / self.total_cells, 4) if self.total_cells else 0.0

    def as_dict(self) -> dict:
        payload = self.__dict__.copy()
        payload["status"] = "success"
        payload["wallGrid"] = self.grid
        return payload


class WallDetector:
    """Small dependency-light implementation of the legacy 800x600 contract."""

    def detect(self, image_bytes: bytes, *, sensitivity: int = 120, canvas_width: int = 800, canvas_height: int = 600, grid_scale: int = 8) -> WallResult:
        if not 0 <= sensitivity <= 255 or min(canvas_width, canvas_height, grid_scale) <= 0:
            raise ValueError("invalid wall detection parameters")
        source = Image.open(io.BytesIO(image_bytes)).convert("L").resize((canvas_width, canvas_height))
        # A light blur suppresses isolated text pixels while preserving the
        # broad wall strokes detected by the former OpenCV service.
        source = source.filter(ImageFilter.MedianFilter(size=3))
        pixels = source.load()
        width, height = canvas_width // grid_scale, canvas_height // grid_scale
        grid: list[list[int]] = []
        for gy in range(height):
            row = []
            for gx in range(width):
                wall = any(pixels[x, y] < sensitivity for y in range(gy * grid_scale, min((gy + 1) * grid_scale, canvas_height)) for x in range(gx * grid_scale, min((gx + 1) * grid_scale, canvas_width)))
                row.append(1 if wall else 0)
            grid.append(row)
        count = sum(sum(row) for row in grid)
        return WallResult(grid, width, height, canvas_width, canvas_height, grid_scale, sensitivity, 0.0, count, width * height)


class WallDetectionCache:
    def __init__(self):
        self._values: dict[tuple, dict] = {}
        self._lock = threading.Lock()

    def get_or_detect(self, image_bytes: bytes, *, asset_version: str = "", **params) -> dict:
        digest = hashlib.sha256(image_bytes).hexdigest()
        key = (digest, asset_version, tuple(sorted(params.items())))
        with self._lock:
            if key in self._values:
                return self._values[key]
        result = WallDetector().detect(image_bytes, **params).as_dict()
        with self._lock:
            self._values[key] = result
        return result

    def invalidate(self, asset_version: str):
        with self._lock:
            self._values = {key: value for key, value in self._values.items() if key[1] != asset_version}


wall_cache = WallDetectionCache()
